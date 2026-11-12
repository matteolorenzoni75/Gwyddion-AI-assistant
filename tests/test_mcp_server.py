"""
Exercise the MCP tools the way Claude will call them.

These are smoke tests with a real dependency: they drive Gwyddion through the
Python 2.7 bridge. If Gwyddion or Python 2.7 is not installed they skip rather
than fail, because a missing toolchain is an environment fact, not a defect in
this code.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from afm_copilot.bridge import BridgeError, GwyBridge
from afm_copilot.mcp_server import server

SAMPLES = Path(r"C:\AFM_Automation\OLD input IMAGES")


def _bridge_available() -> bool:
    try:
        GwyBridge()
    except BridgeError:
        return False
    return True


needs_gwyddion = pytest.mark.skipif(
    not _bridge_available(),
    reason="Gwyddion 32-bit and/or Python 2.7 not available on this machine")

needs_samples = pytest.mark.skipif(
    not SAMPLES.is_dir(), reason="sample scans not present")


def call(_tool: str, /, **kwargs):
    """
    Invoke a tool the way an MCP client does.

    The tool name is positional-only so it cannot collide with a tool argument
    that is itself called `name` -- explain_recipe has one.

    Returns the CallToolResult, whose `.content` is the list of text and image
    blocks the client actually receives.
    """
    return asyncio.run(server.call_tool(_tool, kwargs))


def blocks(result) -> list:
    """The content blocks of a tool result."""
    return list(getattr(result, "content", []) or [])


def as_text(result) -> str:
    """Flatten a tool result to text, ignoring any image blocks."""
    return "\n".join(b.text for b in blocks(result)
                     if getattr(b, "type", None) == "text")


def image_blocks(result) -> list:
    return [b for b in blocks(result) if getattr(b, "type", None) == "image"]


def test_all_tools_are_registered():
    tools = asyncio.run(server.list_tools())
    names = {t.name for t in tools}
    assert {"check_setup", "list_scans", "inspect_scan", "list_recipes",
            "plan_scan", "explain_recipe", "process_scans", "render_batch",
            "measure_thickness", "search_gwyddion",
            "extract_profile"} <= names


def test_every_tool_describes_itself():
    """A tool with no description is invisible to the model in practice."""
    for tool in asyncio.run(server.list_tools()):
        assert tool.description, f"{tool.name} has no description"
        assert len(tool.description) > 40, f"{tool.name} description is too thin"


def test_list_recipes_names_every_recipe():
    from afm_copilot.ops import RECIPES
    text = as_text(call("list_recipes"))
    for key in RECIPES:
        assert key in text


def test_explain_recipe_returns_the_reasoning():
    text = as_text(call("explain_recipe", name="clean-with-features"))
    assert "Flatten base" in text
    # The explanation must carry the caution, not just the steps -- that is the
    # whole point of the built-in explanations.
    assert "Note:" in text


def test_explain_unknown_recipe_lists_the_real_ones():
    text = as_text(call("explain_recipe", name="not-a-recipe"))
    assert "quick-clean" in text


def test_search_gwyddion_finds_a_known_function():
    text = as_text(call("search_gwyddion", query="scars"))
    assert "scars_remove" in text


def test_search_gwyddion_is_honest_about_misses():
    text = as_text(call("search_gwyddion", query="zzzznotafunction"))
    assert "No Gwyddion function matches" in text


@needs_gwyddion
def test_check_setup_reports_a_working_bridge():
    text = as_text(call("check_setup"))
    assert "Gwyddion 2.70" in text
    assert "FAIL" not in text


@needs_samples
def test_list_scans_counts_the_folder():
    text = as_text(call("list_scans", folder=str(SAMPLES)))
    assert "file(s) in" in text


def test_list_scans_handles_a_missing_folder():
    text = as_text(call("list_scans", folder=r"C:\definitely\not\here"))
    assert "No such folder" in text


@needs_gwyddion
@needs_samples
def test_inspect_scan_returns_measurements_and_an_image():
    sample = next(SAMPLES.glob("*.ibw"))
    result = call("inspect_scan", path=str(sample))
    text = as_text(result)

    assert "height channel" in text
    assert "z range" in text
    # The image is the point: Claude has to be able to look at the scan, not
    # just read numbers about it.
    assert image_blocks(result), "inspect_scan returned no image block"


def test_plan_scan_turns_visual_continuity_into_a_conservative_veto(tmp_path):
    import numpy as np

    from afm_copilot.gwy_io import Channel, save_height

    n = 128
    y, x = np.mgrid[0:n, 0:n].astype(float) / n - 0.5
    data = 200e-9 * x + np.random.default_rng(7).normal(0, 1e-9, (n, n))
    data[36:92, 36:92] += 180e-9
    sample = save_height(
        Channel(name="Height", data=data, xreal=5e-6, yreal=5e-6),
        tmp_path / "blind.gwy")

    result = call(
        "plan_scan",
        path=str(sample),
        morphology_family="granular_continuous",
        review_effect="restrict",
        evidence="texture occupies the field; no separate flat background",
    )
    text = as_text(result)

    assert "Recommended: level-only" in text
    assert "restriction used  : yes" in text
    assert "automatic mask    : no" in text
    assert "mcp-vision" in text
    assert image_blocks(result), "the semantic plan must remain visually checkable"


def test_plan_scan_rejects_an_unknown_visual_label(tmp_path):
    import numpy as np

    from afm_copilot.gwy_io import Channel, save_height

    sample = save_height(
        Channel(name="Height", data=np.zeros((32, 32)),
                xreal=1e-6, yreal=1e-6),
        tmp_path / "blind.gwy")
    text = as_text(call(
        "plan_scan", path=str(sample),
        morphology_family="looks-kind-of-grainy"))

    assert "Unknown morphology family" in text
