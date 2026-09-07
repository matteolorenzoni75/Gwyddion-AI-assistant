"""
The whole path on a folder, which is the normal way this is used.

Gwyddion is not required here: cleaning is the one stage that needs it, and
losing it must not cost the rest of the report -- so these run with cleaning
switched off and check everything around it.
"""

from pathlib import Path

import numpy as np
import pytest

from afm_copilot import batch
from afm_copilot.gwy_io import Channel, load_height, save_height

SIZE = 128


def surface(seed=1, roughness=5e-9, smoothness=20):
    data = np.random.default_rng(seed).normal(0, roughness, (SIZE, SIZE))
    for _ in range(smoothness):
        data = (data + np.roll(data, 1, 0) + np.roll(data, 1, 1)) / 3.0
    return data * (roughness / max(data.std(), 1e-18))


def write(folder, name, data, xreal=10e-6, yreal=10e-6):
    return save_height(Channel(name="Height", data=data, xreal=xreal,
                               yreal=yreal), folder / f"{name}.gwy")


def test_a_folder_of_good_scans_is_all_kept(tmp_path):
    source = tmp_path / "in"
    for i in range(3):
        write(source, f"scan{i}", surface(seed=i))
    summary = batch.run([source], tmp_path / "out", do_clean=False)
    assert summary["scans_read"] == 3
    assert summary["kept"] == 3
    assert summary["discarded"] == 0


def test_one_scan_is_as_normal_as_a_hundred(tmp_path):
    """The batch path is the ordinary path, not a bulk special case."""
    source = tmp_path / "in"
    write(source, "only", surface())
    summary = batch.run([source], tmp_path / "out", do_clean=False)
    assert summary["scans_read"] == 1
    assert summary["kept"] == 1


def test_repeats_of_the_same_area_are_set_aside(tmp_path):
    """
    Trace and retrace differ slightly, so an exact match never fires.

    Twenty-nine pairs in the real training set were being measured, and
    offered for labelling, twice over.
    """
    source = tmp_path / "in"
    data = surface()
    write(source, "trace", data)
    write(source, "retrace", data + np.random.default_rng(9).normal(
        0, 1e-11, data.shape))
    summary = batch.run([source], tmp_path / "out", do_clean=False)
    assert summary["duplicates"] == 1
    assert summary["kept"] == 1


def test_an_unusable_scan_is_recorded_not_deleted(tmp_path):
    source = tmp_path / "in"
    write(source, "fine", surface())
    empty = surface()
    empty[20:, :] = empty[19, 0]
    write(source, "stopped", empty)

    summary = batch.run([source], tmp_path / "out", do_clean=False)
    assert summary["discarded"] == 1
    aside = [r for r in summary["results"] if r["verdict"] == "discard"]
    assert aside[0]["name"] == "stopped"
    assert aside[0]["why"], "a scan set aside must carry its reason"
    assert (source / "stopped.gwy").exists(), "nothing may be deleted"


def test_a_cropped_scan_is_written_back_for_cleaning(tmp_path):
    """
    The two runtimes divide the work, so the trimmed frame has to reach disk.

    Without this the recipes would go on levelling with the empty band still
    in the image -- fitting a background to where the tip measured nothing.
    """
    source = tmp_path / "in"
    data = surface()
    data[100:, :] = data[99, 0]                 # last 22% empty
    write(source, "partial", data)

    out = tmp_path / "out"
    summary = batch.run([source], out, do_clean=False)
    prepared = out / "prepared" / "partial.gwy"
    assert prepared.exists()

    trimmed = load_height(prepared)
    assert trimmed.yres < SIZE
    # The physical height must shrink with the pixels, or every distance
    # measured afterwards is stretched.
    assert trimmed.yreal == pytest.approx(10e-6 * trimmed.yres / SIZE, rel=0.02)
    assert summary["cropped"] == 1


def test_measurements_ride_along_with_each_kept_scan(tmp_path):
    source = tmp_path / "in"
    write(source, "scan", surface())
    summary = batch.run([source], tmp_path / "out", do_clean=False)
    kept = [r for r in summary["results"] if r["kept"]][0]
    assert kept["measurements"]["rms"] > 0
    assert kept["recipe"]


def test_the_report_is_written_where_it_was_asked_for(tmp_path):
    source = tmp_path / "in"
    write(source, "scan", surface())
    out = tmp_path / "out"
    batch.run([source], out, do_clean=False)
    assert (out / "batch.json").is_file()


def test_over_flattening_is_measured_against_what_the_background_explains():
    """
    Removing a background costs roughness, and the amount is predictable.

    If the background explains a fraction f of the variance, sqrt(1 - f) of the
    RMS should survive. Far below that means surface was removed, not artifact
    -- seven scans in a real batch of 128, where row alignment on a nearly flat
    surface ate the small features along with the line offsets.
    """
    from afm_copilot.batch import ScanResult, lost_too_much

    mostly_tilt = ScanResult(
        name="tilted", source="", kept=True, verdict="good",
        rms_before_nm=100.0, rms_after_nm=5.0,
        measurements={"background_order": 1,
                      "explained_by_degree": {1: 0.997}})
    assert not lost_too_much(mostly_tilt), "losing the tilt is not a loss"

    flat_surface_scrubbed = ScanResult(
        name="scrubbed", source="", kept=True, verdict="good",
        rms_before_nm=100.0, rms_after_nm=7.0,
        measurements={"background_order": 2,
                      "explained_by_degree": {2: 0.06}})
    assert lost_too_much(flat_surface_scrubbed)


def test_a_file_that_will_not_convert_is_listed_not_lost(tmp_path):
    """
    Files must not go missing between the folder and the report.

    A real folder had grown to 191 files while the batch read 166, and the
    difference vanished without a word because conversion returned only its
    successes.
    """
    source = tmp_path / "in"
    source.mkdir(parents=True, exist_ok=True)
    write(source, "readable", surface())
    (source / "not-really.ibw").write_bytes(b"nonsense")

    summary = batch.run([source], tmp_path / "out", do_clean=False)
    assert summary["scans_read"] == 2, "every input file must appear"
    missing = [r for r in summary["results"] if r["verdict"] == "unreadable"]
    assert len(missing) == 1
    assert missing[0]["why"], "and must say why"


def test_one_crashing_file_does_not_take_its_whole_group(tmp_path):
    """
    A crash is not a verdict on the group.

    Some files kill the Gwyddion subprocess outright instead of returning an
    error, and a batch of forty then lost forty -- including files that had
    converted perfectly the run before. Halving isolates the culprit.
    """
    from afm_copilot.batch import _convert_group

    poison = Path("poison.ibw")
    files = [Path(f"good{i}.ibw") for i in range(7)]
    files.insert(4, poison)

    class Bridge:
        """Dies whenever the poison file is in the group, like the real one."""

        def convert_raw(self, group, into):
            from afm_copilot.bridge import BridgeError
            if poison in group:
                raise BridgeError("subprocess crashed")
            return {"results": [{"stem": p.stem, "ok": True,
                                 "gwy": str(into / (p.stem + ".gwy"))}
                                for p in group]}

    done, failed = [], []
    _convert_group(Bridge(), files, tmp_path, done, failed)

    assert len(done) == 7, "every healthy file must still convert"
    assert [p for p, _ in failed] == [poison]


def test_a_phase_map_is_not_called_unreadable(tmp_path):
    """
    A file with no height channel is not damaged.

    Eight phase maps in one batch were filed under "could not read", which
    reads as an accusation against perfectly good files. They are simply not
    topography, and this is a height-only pipeline for now.
    """
    from gwyfile.objects import GwyContainer, GwyDataField

    source = tmp_path / "in"
    source.mkdir(parents=True, exist_ok=True)
    write(source, "height", surface())

    field = GwyDataField(np.asarray(surface(), dtype=float),
                         xreal=1e-5, yreal=1e-5,
                         si_unit_xy="m", si_unit_z="deg")
    GwyContainer({"/0/data": field,
                  "/0/data/title": "Phase"}).tofile(str(source / "phase.gwy"))

    summary = batch.run([source], tmp_path / "out", do_clean=False)
    assert summary["unreadable"] == 0
    assert summary["not_topography"] == 1
    aside = [r for r in summary["results"]
             if r["verdict"] == "not topography"][0]
    assert "no height channel" in aside["why"][0]


def test_over_flattening_needs_both_numbers():
    from afm_copilot.batch import ScanResult, lost_too_much

    assert not lost_too_much(ScanResult(name="x", source="", kept=True,
                                        verdict="good"))


def test_an_unreadable_file_does_not_stop_the_batch(tmp_path):
    source = tmp_path / "in"
    source.mkdir(parents=True, exist_ok=True)
    write(source, "good", surface())
    (source / "rubbish.gwy").write_bytes(b"not a gwyddion file")

    summary = batch.run([source], tmp_path / "out", do_clean=False)
    assert summary["kept"] == 1
    assert summary["unreadable"] == 1
