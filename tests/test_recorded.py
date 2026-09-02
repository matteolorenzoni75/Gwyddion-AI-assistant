"""
Tests for copying a scan's recorded processing onto other scans.

The failure this guards against is silent: a parameter written under the wrong
name is simply ignored by Gwyddion, which then uses whatever value happened to
be left there. The result looks processed and is wrong.
"""

from __future__ import annotations

import pytest

from afm_copilot.ops import OPERATIONS
from afm_copilot.ops.recorded import (compare_logs, describe_source, parse_log,
                                      recipe_from_log)

# A real log, copied from a file this project processed.
REAL_LOG = [
    'file::psia(filename="C:\\\\scans\\\\example.tiff")@2026-08-31 13:24:30Z',
    "proc::level(mode=0)@2026-08-31 13:35:01.902635Z",
    "proc::flatten_base()@2026-08-31 13:35:02.005669Z",
    "proc::align_rows(direction=0, do_extract=False, do_plot=False, "
    "masking=0, max_degree=5, method=4, trim_fraction=0.0985)"
    "@2026-08-31 13:35:02.013414Z",
    "proc::scars_remove(combine=False, combine_type=0, max_width=1, "
    "min_len=17, threshold_high=0.007, threshold_low=0.007, type=5, "
    "update=True)@2026-08-31 13:35:02.024125Z",
    "proc::fix_zero(mode=0)@2026-08-31 13:35:02.024125Z",
]


def test_reads_only_the_processing_steps():
    steps = parse_log(REAL_LOG)
    # The file:: entry records how the scan was read, not something to repeat.
    assert [s["gwy_func"] for s in steps] == [
        "level", "flatten_base", "align_rows", "scars_remove", "fix_zero"]


def test_values_keep_their_types():
    steps = {s["gwy_func"]: s["settings"] for s in parse_log(REAL_LOG)}
    align = steps["align_rows"]
    assert align["method"] == 4                  # int, not "4"
    assert align["trim_fraction"] == 0.0985      # float
    assert align["do_plot"] is False             # bool
    assert steps["flatten_base"] == {}           # no parameters logged


def test_reports_which_importer_read_the_scan():
    assert describe_source(REAL_LOG) == "psia"
    assert describe_source(["proc::level(mode=0)@now"]) == ""


def test_align_rows_settings_go_where_gwyddion_keeps_them():
    """
    The bug this exists for.

    Gwyddion logs the operation as `align_rows` but stores its parameters under
    `linematch`. Writing to `/module/align_rows/` is accepted and ignored, so a
    recorded method=4 silently came back as whatever was there before.
    """
    recipe = recipe_from_log(REAL_LOG)
    align = next(op for op in recipe.operations if op.gwy_func == "align_rows")

    assert "/module/linematch/method" in align.settings
    assert align.settings["/module/linematch/method"] == 4
    assert not any(k.startswith("/module/align_rows/") for k in align.settings)


def test_recorded_steps_reuse_the_written_explanations():
    """A copied recipe should read like any other, not like raw log text."""
    recipe = recipe_from_log(REAL_LOG)
    titles = [op.title for op in recipe.operations]

    assert "Subtract mean plane" in titles
    assert "Align rows (median of differences)" in titles
    # And the cautions come along, because they still apply.
    align = next(op for op in recipe.operations if op.gwy_func == "align_rows")
    assert align.caution and "roughness" in align.caution


def test_recipe_says_when_not_to_use_it():
    recipe = recipe_from_log(REAL_LOG, source_name="reference.gwy")
    assert "reference.gwy" in recipe.purpose
    # Copying settings chosen for one scan onto a different one is the risk.
    assert "differ" in recipe.when_not_to_use


def test_refuses_a_scan_that_was_never_processed():
    only_opened = ['file::psia(filename="x.tiff")@2026-08-31 13:24:30Z']
    with pytest.raises(ValueError, match="no processing history"):
        recipe_from_log(only_opened)


def test_unknown_operation_is_described_but_flagged():
    """
    An operation outside the catalogue still runs, but says so.

    Better to carry it with an honest caveat than to drop it silently and
    produce a copy that is missing a step.
    """
    log = ["proc::some_unlisted_function(alpha=3)@2026-08-31 13:00:00Z"]
    recipe = recipe_from_log(log)
    op = recipe.operations[0]

    assert op.gwy_func == "some_unlisted_function"
    assert op.settings == {"/module/some_unlisted_function/alpha": 3}
    assert "not been checked" in (op.caution or "")


def test_comparison_is_silent_on_a_faithful_copy():
    assert compare_logs(REAL_LOG, REAL_LOG) == []


def test_comparison_catches_a_setting_that_did_not_carry_over():
    produced = [e.replace("method=4", "method=2") for e in REAL_LOG]
    problems = compare_logs(REAL_LOG, produced)

    assert len(problems) == 1
    assert "method" in problems[0]
    assert "4" in problems[0] and "2" in problems[0]


def test_comparison_catches_a_missing_step():
    produced = REAL_LOG[:-1]
    problems = compare_logs(REAL_LOG, produced)
    assert any("steps were recorded" in p for p in problems)


def test_registering_a_recorded_recipe_does_not_break_the_catalogue():
    """The built-in recipes must still work after a copy has been read."""
    before = set(OPERATIONS)
    recipe_from_log(REAL_LOG)

    from afm_copilot.ops import get_recipe
    quick = get_recipe("quick-clean")
    assert [op.title for op in quick.operations][0] == "Subtract mean plane"
    # Recorded steps are added under their own keys; nothing is replaced.
    assert before <= set(OPERATIONS)
