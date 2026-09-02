"""
MCP server: lets Claude drive Gwyddion by conversation.

This is the "talk to it" half of the interface. Claude Desktop connects over
stdio, so there is no chat UI to build, no API key, and nothing billed beyond
the Claude subscription already in use. Because MCP can carry images back,
Claude actually *sees* the rendered map it is reasoning about rather than
working blind from numbers.

Every tool here is a thin wrapper over afm_copilot, so behaviour is identical
to the command line -- including the refusals. If a step measurement is not
supportable, Claude is told why, in the same words.

Register it with Claude Desktop by adding to claude_desktop_config.json:

    {
      "mcpServers": {
        "afm-copilot": {
          "command": "C:\\\\AFM_Copilot\\\\.venv\\\\Scripts\\\\python.exe",
          "args": ["-m", "afm_copilot.mcp_server"],
          "cwd": "C:\\\\AFM_Copilot"
        }
      }
    }

Run `python -m afm_copilot.mcp_server --print-config` to get that filled in
with the paths on this machine.

Nothing may be printed to stdout: that channel carries the MCP protocol.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from mcp.server.mcpserver import Image, MCPServer

from afm_copilot import __version__
from afm_copilot.analysis import aggregate, measure_film_thickness
from afm_copilot.bridge import BridgeError, GwyBridge
from afm_copilot.gwy_io import Channel, load_channels, load_height
from afm_copilot.ops import RECIPES, get_recipe
from afm_copilot.profile import profile_across
from afm_copilot.render import RenderStyle, render_channel, common_color_scale
from afm_copilot.report import build_thickness_report

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_SUFFIXES = {".ibw", ".tiff", ".tif", ".spm", ".jpk", ".sxm", ".top",
                ".stp", ".nid", ".mi", ".par", ".ezd", ".afm"}
API_JSON = PROJECT_ROOT / "docs" / "pygwy_api" / "pygwy_api.json"

server = MCPServer(
    name="afm-copilot",
    instructions=(
        "Drives Gwyddion to process AFM height maps. Work in this order:\n"
        "1. `list_scans` to see what is in a folder.\n"
        "2. `inspect_scan` to look at one -- it returns the image, so judge it "
        "visually before deciding anything.\n"
        "3. `list_recipes` / `explain_recipe` to choose a processing recipe, "
        "and tell the user WHY that recipe rather than another.\n"
        "4. `process_scans` to apply it. The result reports what each step "
        "changed.\n"
        "5. `measure_thickness` for a film step, `render_batch` for figures.\n\n"
        "Two habits matter. First, a large drop in RMS is not automatically "
        "good -- levelling always removes some real roughness along with the "
        "artifact, so do not present it as an improvement without saying so. "
        "Second, these tools refuse when the data does not support an answer; "
        "relay the refusal and its reason rather than trying another route to "
        "produce a number.\n\n"
        "Never infer what a sample is, or which recipe it needs, from its "
        "filename. The user keeps their test set deliberately blind, and "
        "guessing from names defeats that. Judge from the image and the "
        "measurements."
    ),
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _scratch() -> Path:
    d = Path(tempfile.gettempdir()) / "afm_copilot_mcp"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _split_inputs(path: str | Path) -> tuple[list[Path], list[Path]]:
    """Separate ready .gwy files from raw instrument files."""
    p = Path(path)
    items = sorted(p.iterdir()) if p.is_dir() else [p]
    gwy = [f for f in items if f.is_file() and f.suffix.lower() == ".gwy"]
    raw = [f for f in items if f.is_file() and f.suffix.lower() in RAW_SUFFIXES]
    return gwy, raw


def _to_gwy(path: str | Path, work: Path) -> list[Path]:
    """Everything as .gwy, converting raw files through Gwyddion once."""
    gwy, raw = _split_inputs(path)
    if raw:
        report = GwyBridge().convert_raw(raw, work / "_gwy")
        gwy.extend(Path(r["gwy"]) for r in report["results"] if r["ok"])
    return sorted(set(gwy))


def _describe(ch: Channel) -> dict:
    return {
        "channel": ch.name,
        "pixels": f"{ch.xres} x {ch.yres}",
        "scan_size_um": round(ch.xreal * 1e6, 4),
        "z_range_nm": round(ch.z_range * 1e9, 4),
        "rms_nm": round(ch.rms * 1e9, 4),
        "pixel_size_nm": round(ch.pixel_size * 1e9, 3),
    }


def _preview(ch: Channel, width_in: float = 3.4, dpi: int = 130) -> Image:
    """Render one channel to a PNG so Claude can look at it."""
    out = _scratch() / f"preview_{abs(hash(str(ch.source))) % 10**8}.png"
    scale = common_color_scale([ch])
    render_channel(ch, out, scale, RenderStyle(width_in=width_in, dpi=dpi),
                   title=ch.source.stem if ch.source else ch.name)
    return Image(path=out)


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------

@server.tool(
    description="Check that Gwyddion can be driven. Run this first if anything "
                "seems broken -- it distinguishes a broken toolchain from a "
                "bad file.")
def check_setup() -> str:
    try:
        r = GwyBridge().self_test()
    except BridgeError as exc:
        return f"Gwyddion cannot be reached.\n\n{exc}"
    lines = [f"AFM Copilot {__version__}",
             f"Gwyddion {r.get('gwy_version')} via Python "
             f"{r.get('python_version')}"]
    for name, ok in sorted(r["checks"].items()):
        lines.append(f"  {'ok  ' if ok else 'FAIL'} {name}")
    lines.extend(f"  ! {e}" for e in r.get("errors", []))
    return "\n".join(lines)


@server.tool(
    description="List the AFM scans in a folder with their size, scan range "
                "and roughness. Use this to see what is available before "
                "processing anything.")
def list_scans(folder: str) -> str:
    p = Path(folder)
    if not p.exists():
        return f"No such folder: {folder}"
    gwy, raw = _split_inputs(p)
    if not gwy and not raw:
        return f"{folder} contains no readable AFM files."

    lines = [f"{len(gwy) + len(raw)} file(s) in {folder}",
             f"  {len(gwy)} already converted (.gwy), {len(raw)} raw", ""]
    for f in (gwy + raw)[:60]:
        size = f.stat().st_size / 1e6
        lines.append(f"  {f.name}   ({size:.1f} MB)")
    if len(gwy) + len(raw) > 60:
        lines.append(f"  ... and {len(gwy) + len(raw) - 60} more")
    lines.append("\nUse inspect_scan on one of these to see it.")
    return "\n".join(lines)


@server.tool(
    description="Look at one scan: returns its measurements AND a rendered "
                "image, so you can judge visually what it needs. Do this "
                "before choosing a recipe.")
def inspect_scan(path: str) -> list:
    files = _to_gwy(path, _scratch())
    if not files:
        return [f"Nothing readable at {path}"]
    try:
        ch = load_height(files[0])
    except (ValueError, OSError) as exc:
        return [f"Could not read a height channel: {exc}"]

    info = _describe(ch)
    try:
        all_ch = [c.name for c in load_channels(files[0])]
    except Exception:
        all_ch = [ch.name]

    text = [f"{files[0].name}",
            f"  height channel : {info['channel']}",
            f"  all channels   : {', '.join(all_ch)}",
            f"  size           : {info['pixels']} px over "
            f"{info['scan_size_um']} um",
            f"  pixel          : {info['pixel_size_nm']} nm",
            f"  z range        : {info['z_range_nm']} nm",
            f"  RMS (raw)      : {info['rms_nm']} nm",
            "",
            "The RMS above is the raw value -- it includes any tilt or bow, so "
            "it is not a roughness measurement yet."]
    return ["\n".join(text), _preview(ch)]


@server.tool(
    description="List the one-click recipes. Each bundles the four or five "
                "Gwyddion operations normally run together.")
def list_recipes() -> str:
    lines = []
    for key in sorted(RECIPES):
        r = RECIPES[key]
        lines.append(f"{key}  --  {r.title}")
        lines.append(f"    {r.purpose}")
        lines.append(f"    Use when: {r.when_to_use}")
        lines.append("")
    return "\n".join(lines)


@server.tool(
    description="Explain one recipe in full: every step, what it does, why it "
                "is there, and what it costs. Quote this to the user when you "
                "recommend a recipe.")
def explain_recipe(name: str) -> str:
    try:
        return get_recipe(name).explain()
    except KeyError as exc:
        return str(exc)


@server.tool(
    description="Apply a recipe to a file or folder. Reports what each step "
                "changed to the roughness, so the processing is auditable.")
def process_scans(path: str, recipe: str = "quick-clean",
                  output_folder: str = "") -> str:
    try:
        rec = get_recipe(recipe)
    except KeyError as exc:
        return str(exc)

    work = Path(output_folder) if output_folder else _scratch() / "processed"
    work.mkdir(parents=True, exist_ok=True)
    try:
        files = _to_gwy(path, work)
        if not files:
            return f"Nothing to process at {path}"
        result = GwyBridge().run_recipe(rec, files, work / "processed")
    except BridgeError as exc:
        return f"Processing failed: {exc}"

    lines = [f"Applied '{rec.key}' to {result['n_ok']}/{result['n_total']} "
             f"file(s).", f"Output: {work / 'processed'}", ""]
    for r in result["results"]:
        if not r["ok"]:
            lines.append(f"  {r['stem']}: FAILED -- {r['error']}")
            continue
        lines.append(f"  {r['stem']}: RMS {r['initial']['rms']:.4g} -> "
                     f"{r['final']['rms']:.4g} m")
        for step in r["steps"]:
            if step["applied"] and "rms_change_percent" in step:
                lines.append(f"      {step['title']:<34} "
                             f"{step['rms_change_percent']:+7.2f}% RMS")
            elif step["note"]:
                lines.append(f"      {step['title']:<34} {step['note']}")
    lines.append("\nNote: a large negative RMS change is not automatically an "
                 "improvement -- levelling removes real roughness along with "
                 "the artifact.")
    return "\n".join(lines)


@server.tool(
    description="Render scans as comparable images: one shared colour scale, "
                "a scale bar and a fixed resolution. Returns the first few so "
                "you can see the result.")
def render_batch(path: str, output_folder: str = "", dpi: int = 300,
                 shared_scale: bool = True, show: int = 3) -> list:
    work = Path(output_folder) if output_folder else _scratch() / "figures"
    work.mkdir(parents=True, exist_ok=True)
    files = _to_gwy(path, work)
    if not files:
        return [f"Nothing to render at {path}"]

    channels = []
    for f in files:
        try:
            channels.append(load_height(f))
        except (ValueError, OSError):
            pass
    if not channels:
        return ["No height channels found."]

    from afm_copilot.render import render_batch as _render, scale_spread
    summary = _render(channels, work, RenderStyle(dpi=dpi),
                      shared_scale=shared_scale)

    text = [f"Rendered {summary['n_images']} image(s) to {work}",
            f"  {dpi} dpi, colour map {summary['cmap']}"]
    if shared_scale:
        text.append(f"  shared scale {summary['z_min_display']:.3g} to "
                    f"{summary['z_max_display']:.3g} {summary['z_unit']}")
    spread = scale_spread(channels)
    if shared_scale and spread > 20:
        text.append(f"  WARNING: z ranges differ by a factor of {spread:.0f}. "
                    f"The shallowest scans will look flat on one shared scale.")

    out: list = ["\n".join(text)]
    for rec in summary["images"][:max(0, show)]:
        out.append(Image(path=rec["file"]))
    return out


@server.tool(
    description="Measure a film step across one or more images and write a PDF "
                "report. Levels first by default. Images with no measurable "
                "step are reported as such rather than given a number.")
def measure_thickness(path: str, output_folder: str = "",
                      recipe: str = "clean-with-features",
                      level_first: bool = True) -> list:
    work = Path(output_folder) if output_folder else _scratch() / "thickness"
    work.mkdir(parents=True, exist_ok=True)

    try:
        files = _to_gwy(path, work)
        if not files:
            return [f"Nothing to measure at {path}"]
        if level_first:
            res = GwyBridge().run_recipe(get_recipe(recipe), files,
                                         work / "levelled")
            files = [Path(r["output"]) for r in res["results"] if r["ok"]]
    except (BridgeError, KeyError) as exc:
        return [f"Could not prepare the images: {exc}"]

    channels = []
    for f in files:
        try:
            channels.append(load_height(f))
        except (ValueError, OSError):
            pass
    if not channels:
        return ["No height channels to measure."]

    pdf = work / "thickness_report.pdf"
    summary = build_thickness_report(channels, pdf, png_dir=work / "pages")
    text = [summary["summary"], "",
            f"Measured {summary['n_measured']} of {summary['n_images']} "
            f"image(s).", f"Report: {pdf}"]

    out: list = ["\n".join(text)]
    pages = sorted((work / "pages").glob("*.png"))
    if pages:
        out.append(Image(path=pages[0]))
    return out


@server.tool(
    description="Search Gwyddion's 197 processing functions by name or "
                "description. Use this when the user asks for something the "
                "recipes do not cover -- Gwyddion probably already does it.")
def search_gwyddion(query: str, limit: int = 20) -> str:
    if not API_JSON.is_file():
        return ("The function inventory has not been generated. Run "
                "tools/introspect_pygwy.py through tools/run_py27.ps1.")
    data = json.loads(API_JSON.read_text(encoding="utf-8"))
    q = query.lower().strip()
    hits = [f for f in data["process_functions"]
            if q in f["name"].lower()
            or q in (f.get("tooltip") or "").lower()
            or q in (f.get("menu_path") or "").lower()]
    if not hits:
        return (f"No Gwyddion function matches '{query}'. "
                f"There are {len(data['process_functions'])} in total.")

    lines = [f"{len(hits)} of {len(data['process_functions'])} functions match "
             f"'{query}':", ""]
    for f in sorted(hits, key=lambda x: x["name"])[:limit]:
        lines.append(f"  {f['name']}")
        lines.append(f"      {f.get('tooltip', '')}")
        lines.append(f"      menu: {f.get('menu_path', '')}")
    if len(hits) > limit:
        lines.append(f"  ... and {len(hits) - limit} more")
    lines.append("\nNot all of these are wrapped as recipes yet. Tell the user "
                 "what exists rather than implying it is already available "
                 "here.")
    return "\n".join(lines)


@server.tool(
    description="Extract a height profile across a scan and export it as the "
                "two-column text Gwyddion produces.")
def extract_profile(path: str, axis: str = "horizontal",
                    position: float = 0.5, band_pixels: int = 16,
                    output_folder: str = "") -> str:
    work = Path(output_folder) if output_folder else _scratch() / "profiles"
    work.mkdir(parents=True, exist_ok=True)
    files = _to_gwy(path, work)
    if not files:
        return f"Nothing readable at {path}"

    try:
        ch = load_height(files[0])
    except (ValueError, OSError) as exc:
        return f"Could not read a height channel: {exc}"

    prof = profile_across(ch, axis, position=position, band_px=band_pixels)
    txt = work / f"{files[0].stem}_profile.txt"
    prof.to_text(txt)

    step = measure_film_thickness(ch)
    return "\n".join([
        f"Profile across {files[0].name} ({axis}, at {position:.0%} of the "
        f"frame, averaged over {band_pixels} rows)",
        f"  {prof.n_points} points over {prof.length * 1e6:.3f} um",
        f"  exported to {txt}",
        "",
        step.explain(),
    ])


def _print_config() -> None:
    """Print the Claude Desktop entry with this machine's paths filled in."""
    python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    config = {"mcpServers": {"afm-copilot": {
        "command": str(python),
        "args": ["-m", "afm_copilot.mcp_server"],
        "cwd": str(PROJECT_ROOT),
    }}}
    # stderr, because stdout belongs to the MCP protocol.
    print(json.dumps(config, indent=2), file=sys.stderr)


def main() -> None:
    if "--print-config" in sys.argv:
        _print_config()
        return
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
