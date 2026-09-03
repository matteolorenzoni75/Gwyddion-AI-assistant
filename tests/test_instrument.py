"""
Reading what the instrument wrote beside the pixels.

The point of this module is that it removes work rather than adding it: the
scan note is read in Python 3 straight from the original file, so the Python
2.7 bridge never has to learn to carry metadata across.
"""

from pathlib import Path

import pytest

from afm_copilot.instrument import Acquisition, find_original, read

REAL = Path(r"C:\AFM_Automation\OLD input IMAGES")
real_files = sorted(REAL.glob("*.ibw")) if REAL.is_dir() else []
needs_real = pytest.mark.skipif(not real_files,
                                reason="instrument files not on this machine")


def test_missing_metadata_is_not_an_error():
    """A batch must never stop because a file has no note."""
    acquisition = read(Path("nowhere/at/all.tiff"))
    assert isinstance(acquisition, Acquisition)
    assert not acquisition.known
    assert acquisition.noise_spacings() == []


def test_a_damaged_file_returns_nothing_rather_than_raising(tmp_path):
    broken = tmp_path / "broken.ibw"
    broken.write_bytes(b"not an igor wave at all")
    assert not read(broken).known


def test_mains_spacing_is_speed_over_frequency():
    """
    The arithmetic that turns "pattern or noise?" into a comparison.

    3.744 um/s at 50 Hz is 74.9 nm, with harmonics at 37.4 and 25.0.
    """
    acquisition = Acquisition(scan_speed=3.744e-6, raw={"x": "y"})
    spacings = acquisition.noise_spacings(harmonics=3)
    assert spacings[0] == pytest.approx(74.88e-9, rel=1e-3)
    assert spacings[1] == pytest.approx(37.44e-9, rel=1e-3)
    assert spacings[2] == pytest.approx(24.96e-9, rel=1e-3)


def test_no_speed_means_no_claim():
    assert Acquisition(raw={"x": "y"}).noise_spacings() == []


def test_closed_loop_is_reported_as_unknown_when_unsaid():
    assert Acquisition().closed_loop is None
    assert Acquisition(scan_mode="Closed Loop").closed_loop is True
    assert Acquisition(scan_mode="Open Loop").closed_loop is False


@needs_real
def test_reads_a_real_scan_note():
    acquisition = read(real_files[0])
    assert acquisition.known
    assert acquisition.scan_speed and acquisition.scan_speed > 0
    assert acquisition.points and acquisition.lines
    assert acquisition.channels


@needs_real
def test_every_readable_file_gives_speed_or_says_nothing():
    """Partial notes are fine; wrong numbers are not."""
    for path in real_files:
        acquisition = read(path)
        if not acquisition.known:
            continue
        if acquisition.scan_speed is not None:
            assert acquisition.scan_speed > 0
        if acquisition.points is not None:
            assert acquisition.points > 0


@needs_real
def test_a_mid_scan_change_is_picked_up():
    """
    The instrument appends "@Line: 229" when a setting changed part-way down.

    It is the only record that something happened mid-scan, and it explains
    images whose character changes half way through.
    """
    changed = [read(p).changed_at_line for p in real_files]
    assert any(line is not None for line in changed)


def test_find_original_matches_on_the_stem(tmp_path):
    (tmp_path / "scan001.ibw").write_bytes(b"")
    assert find_original("scan001", [tmp_path]) is not None
    assert find_original("scan002", [tmp_path]) is None
