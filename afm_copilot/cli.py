"""
Command line entry point.

    python -m afm_copilot selftest
    python -m afm_copilot batch-images <input> --out <dir>

Every command prints what it did and why, not just that it finished -- the
explanation is part of the output, not an optional verbose mode.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from afm_copilot import __version__
from afm_copilot.bridge import BridgeError, GwyBridge
from afm_copilot.gwy_io import Channel, load_channels, load_height
from afm_copilot.ops import RECIPES, get_recipe
from afm_copilot.report import build_thickness_report
from afm_copilot.render import (RenderStyle, group_by_scale, group_label,
                                render_batch)

RAW_SUFFIXES = {".ibw", ".tiff", ".tif", ".spm", ".jpk", ".sxm", ".top",
                ".stp", ".nid", ".mi", ".par", ".ezd", ".afm"}


def _parse_length(text: str) -> float:
    """Accept '5um', '500nm', '1.2e-5' and return metres."""
    t = text.strip().lower().replace("µ", "u").replace("μ", "u")
    for suffix, factor in (("nm", 1e-9), ("um", 1e-6), ("mm", 1e-3), ("m", 1.0)):
        if t.endswith(suffix):
            return float(t[: -len(suffix)]) * factor
    return float(t)


def _collect_inputs(paths: list[str]) -> tuple[list[Path], list[Path]]:
    """Split the given files or folders into ready .gwy and raw files."""
    gwy_files: list[Path] = []
    raw_files: list[Path] = []
    for item in paths:
        p = Path(item)
        candidates = sorted(p.iterdir()) if p.is_dir() else [p]
        for c in candidates:
            if not c.is_file():
                continue
            if c.suffix.lower() == ".gwy":
                gwy_files.append(c)
            elif c.suffix.lower() in RAW_SUFFIXES:
                raw_files.append(c)
    return gwy_files, raw_files


def cmd_selftest(args: argparse.Namespace) -> int:
    print("Checking the Python 2.7 / Gwyddion side...\n")
    try:
        bridge = GwyBridge()
        result = bridge.self_test()
    except BridgeError as exc:
        print(f"FAILED: {exc}")
        return 1

    for name, ok in sorted(result["checks"].items()):
        print(f"  {'OK  ' if ok else 'FAIL'}  {name}")
    print(f"\nGwyddion {result.get('gwy_version')} via Python "
          f"{result.get('python_version')}")
    if result.get("errors"):
        for e in result["errors"]:
            print(f"  ! {e}")
    print("\nWhat this proves: Gwyddion's processing modules load and run "
          "headlessly,\nso no Gwyddion window is ever needed.")
    return 0 if result["ok"] else 1


def cmd_batch_images(args: argparse.Namespace) -> int:
    gwy_files, raw_files = _collect_inputs(args.inputs)
    if not gwy_files and not raw_files:
        print("No readable files found.", file=sys.stderr)
        return 1

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    # Raw instrument files have to pass through Gwyddion once, because only it
    # can read all 176 formats. After that everything is native Python 3.
    if raw_files:
        print(f"Converting {len(raw_files)} raw file(s) through Gwyddion...")
        converted_dir = out_dir / "_gwy"
        try:
            report = GwyBridge().convert_raw(raw_files, converted_dir)
        except BridgeError as exc:
            print(f"Conversion failed: {exc}", file=sys.stderr)
            return 1
        for rec in report["results"]:
            if rec["ok"]:
                gwy_files.append(Path(rec["gwy"]))
            else:
                print(f"  ! {Path(rec['source']).name}: {rec['error']}",
                      file=sys.stderr)
        print(f"  {report['n_ok']}/{report['n_total']} converted\n")

    channels: list[Channel] = []
    for path in sorted(set(gwy_files)):
        try:
            channels.append(load_height(path) if not args.all_channels
                            else load_channels(path)[0])
        except (ValueError, OSError) as exc:
            print(f"  ! {path.name}: {exc}", file=sys.stderr)

    if not channels:
        print("No height channels to render.", file=sys.stderr)
        return 1

    style = RenderStyle(
        cmap=args.cmap,
        dpi=args.dpi,
        width_in=args.width,
        show_colorbar=not args.no_colorbar,
        show_scalebar=not args.no_scalebar,
    )
    fov_m = _parse_length(args.fov) if args.fov else None

    if args.auto_group and not args.individual_scale:
        groups = group_by_scale(channels, max_ratio=args.group_ratio)
        print(f"Grouping {len(channels)} scan(s) into {len(groups)} scale "
              f"group(s), so each group stays internally comparable.\n")
        summaries = []
        for group in groups:
            label = group_label(group)
            sub = render_batch(group, out_dir / label, style=style,
                               shared_scale=True, fov_m=fov_m, fmt=args.format)
            print(f"  {label:<22} {sub['n_images']:>3} image(s), scale "
                  f"{sub['z_min_display']:.3g}-{sub['z_max_display']:.3g} "
                  f"{sub['z_unit']}")
            sub["group"] = label
            summaries.append(sub)
        combined = {"grouped": True, "n_groups": len(summaries),
                    "n_images": sum(s["n_images"] for s in summaries),
                    "output_dir": str(out_dir), "groups": summaries}
        json_path = out_dir / "render_summary.json"
        json_path.write_text(json.dumps(combined, indent=2), encoding="utf-8")
        print(f"\nImages are comparable WITHIN each group, not across groups.")
        print(f"Caption-ready details: {json_path}")
        return 0

    summary = render_batch(
        channels,
        out_dir,
        style=style,
        shared_scale=not args.individual_scale,
        fov_m=fov_m,
        fmt=args.format,
    )

    print(f"Rendered {summary['n_images']} image(s) to {summary['output_dir']}")
    print(f"  resolution     {summary['dpi']} dpi, "
          f"{args.width:g} in wide -> {int(args.width * summary['dpi'])} px")
    print(f"  colour map     {summary['cmap']}")
    if summary["shared_scale"]:
        print(f"  colour scale   SHARED: {summary['z_min_display']:.3g} to "
              f"{summary['z_max_display']:.3g} {summary['z_unit']}")
        print("                 -- equal colours mean equal heights in every "
              "image,\n                    so the set can be compared directly.")
    else:
        print("  colour scale   per image (NOT comparable between images)")
    if fov_m:
        print(f"  field of view  cropped to {args.fov} in every image, so "
              "features\n                 are shown at the same physical scale")

    if summary.get("scale_warning"):
        print(f"\n  WARNING: {summary['scale_warning']}")

    json_path = out_dir / "render_summary.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\nCaption-ready details: {json_path}")
    return 0


def cmd_recipes(args: argparse.Namespace) -> int:
    """List the recipes, or explain one in full."""
    if args.name:
        try:
            recipe = get_recipe(args.name)
        except KeyError as exc:
            print(exc, file=sys.stderr)
            return 1
        print(recipe.explain())
        return 0

    print("Available recipes -- each bundles the operations that are normally "
          "run together:\n")
    for key in sorted(RECIPES):
        r = RECIPES[key]
        print(f"  {key:<22} {r.title}")
        print(f"  {'':<22} {r.purpose}")
        print(f"  {'':<22} {len(r.steps)} steps: "
              f"{' -> '.join(o.title for o in r.operations)}")
        print()
    print("Run `afm-copilot recipes <name>` for the full explanation of any "
          "one of them.")
    return 0


def cmd_process(args: argparse.Namespace) -> int:
    try:
        recipe = get_recipe(args.recipe)
    except KeyError as exc:
        print(exc, file=sys.stderr)
        return 1

    gwy_files, raw_files = _collect_inputs(args.inputs)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        bridge = GwyBridge()
    except BridgeError as exc:
        print(f"Cannot reach Gwyddion: {exc}", file=sys.stderr)
        return 1

    if raw_files:
        print(f"Converting {len(raw_files)} raw file(s) through Gwyddion...")
        try:
            report = bridge.convert_raw(raw_files, out_dir / "_gwy")
        except BridgeError as exc:
            print(f"Conversion failed: {exc}", file=sys.stderr)
            return 1
        gwy_files.extend(Path(r["gwy"]) for r in report["results"] if r["ok"])
        print(f"  {report['n_ok']}/{report['n_total']} converted\n")

    if not gwy_files:
        print("Nothing to process.", file=sys.stderr)
        return 1

    print(f"Applying recipe '{recipe.key}' to {len(gwy_files)} file(s).\n")
    print(recipe.explain())
    print()

    try:
        result = bridge.run_recipe(recipe, sorted(set(gwy_files)),
                                   out_dir / "processed")
    except BridgeError as exc:
        print(f"Processing failed: {exc}", file=sys.stderr)
        return 1

    print(f"Processed {result['n_ok']}/{result['n_total']} file(s).\n")
    print("What changed, per file (RMS is the roughness measure):\n")
    for rec in result["results"]:
        if not rec["ok"]:
            print(f"  {rec['stem']}: FAILED -- {rec['error']}")
            continue
        initial = rec["initial"]["rms"]
        final = rec["final"]["rms"]
        print(f"  {rec['stem']}")
        print(f"     RMS {initial:.4g} -> {final:.4g} m")
        for step in rec["steps"]:
            if step["applied"] and "rms_change_percent" in step:
                print(f"       {step['title']:<34} "
                      f"{step['rms_change_percent']:+7.2f}% RMS")
            elif step["note"]:
                print(f"       {step['title']:<34} {step['note']}")

    json_path = out_dir / "process_summary.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nProcessed files: {out_dir / 'processed'}")
    print(f"Full record:     {json_path}")
    print("\nA large negative RMS change is not automatically good -- levelling "
          "always\nremoves some real roughness along with the artifact. See "
          "docs/research/QUALITY_METRICS.md.")
    return 0


def cmd_thickness(args: argparse.Namespace) -> int:
    """Measure a film step across several images and report the pooled value."""
    gwy_files, raw_files = _collect_inputs(args.inputs)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    if raw_files:
        print(f"Converting {len(raw_files)} raw file(s) through Gwyddion...")
        try:
            report = GwyBridge().convert_raw(raw_files, out_dir / "_gwy")
        except BridgeError as exc:
            print(f"Conversion failed: {exc}", file=sys.stderr)
            return 1
        gwy_files.extend(Path(r["gwy"]) for r in report["results"] if r["ok"])
        print(f"  {report['n_ok']}/{report['n_total']} converted\n")

    # A step measurement on an unlevelled image is rejected by design, so level
    # first unless the caller has already done it. The default recipe is the
    # feature-aware one: an image with a step by definition contains a raised
    # region, and levelling that fits *through* it leaves enough residual
    # curvature to merge the two height populations.
    if not args.no_level:
        recipe = get_recipe(args.recipe)
        print(f"Levelling first with '{recipe.key}' -- an unlevelled image has "
              f"no measurable\nstep, because tilt and bow spread the two height "
              f"populations until they merge.\n")
        try:
            result = GwyBridge().run_recipe(recipe,
                                            sorted(set(gwy_files)),
                                            out_dir / "levelled")
        except BridgeError as exc:
            print(f"Levelling failed: {exc}", file=sys.stderr)
            return 1
        gwy_files = [Path(r["output"]) for r in result["results"] if r["ok"]]

    channels = []
    for path in sorted(set(gwy_files)):
        try:
            channels.append(load_height(path))
        except (ValueError, OSError) as exc:
            print(f"  ! {path.name}: {exc}", file=sys.stderr)

    if not channels:
        print("No height channels to measure.", file=sys.stderr)
        return 1

    out_pdf = out_dir / args.name
    summary = build_thickness_report(channels, out_pdf, title=args.title,
                                     band_px=args.band,
                                     profile_axis=args.axis,
                                     png_dir=out_dir / "pages")

    print(summary["summary"])
    print(f"\nMeasured {summary['n_measured']} of {summary['n_images']} image(s).")
    print(f"Report: {out_pdf}")

    json_path = out_dir / "thickness_summary.json"
    json_path.write_text(json.dumps(summary, indent=2, default=str),
                         encoding="utf-8")
    print(f"Numbers: {json_path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="afm-copilot",
        description="Make Gwyddion's capability reachable without knowing it.")
    parser.add_argument("--version", action="version",
                        version=f"afm-copilot {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_self = sub.add_parser(
        "selftest", help="check that Gwyddion can be driven headlessly")
    p_self.set_defaults(func=cmd_selftest)

    p_img = sub.add_parser(
        "batch-images",
        help="render a folder of scans as comparable images",
        description=(
            "Renders every scan with ONE shared colour scale, a scale bar and "
            "a fixed resolution, so the images can be compared by eye and "
            "dropped straight into a report."))
    p_img.add_argument("inputs", nargs="+",
                       help="files or folders (.gwy or raw instrument formats)")
    p_img.add_argument("--out", required=True, help="output directory")
    p_img.add_argument("--dpi", type=int, default=300,
                       help="output resolution (default: 300)")
    p_img.add_argument("--width", type=float, default=4.0,
                       help="image width in inches (default: 4.0)")
    p_img.add_argument("--cmap", default="afmhot",
                       help="matplotlib colour map (default: afmhot)")
    p_img.add_argument("--fov", default=None,
                       help="crop all images to this field of view, "
                            "e.g. 5um or 500nm")
    p_img.add_argument("--format", default="jpg",
                       choices=["jpg", "png", "tif", "pdf"],
                       help="output format (default: jpg)")
    p_img.add_argument("--individual-scale", action="store_true",
                       help="scale each image to its own range "
                            "(breaks comparability)")
    p_img.add_argument("--auto-group", action="store_true",
                       help="split into scale groups so shallow scans are not "
                            "flattened by deep ones; each group gets its own "
                            "folder and shared scale")
    p_img.add_argument("--group-ratio", type=float, default=8.0,
                       help="largest z-range ratio allowed inside one group "
                            "(default: 8)")
    p_img.add_argument("--all-channels", action="store_true",
                       help="render the first channel of each file rather than "
                            "picking the height channel")
    p_img.add_argument("--no-colorbar", action="store_true")
    p_img.add_argument("--no-scalebar", action="store_true")
    p_img.set_defaults(func=cmd_batch_images)

    p_rec = sub.add_parser(
        "recipes",
        help="list the one-click processing recipes, or explain one",
        description=(
            "Recipes bundle the four or five Gwyddion operations that are "
            "normally run together. Each one explains what it does, why, and "
            "when it is the wrong choice."))
    p_rec.add_argument("name", nargs="?", help="recipe to explain in full")
    p_rec.set_defaults(func=cmd_recipes)

    p_proc = sub.add_parser(
        "process",
        help="apply a recipe to files",
        description=(
            "Runs a named recipe through Gwyddion and reports what each step "
            "changed, so the processing is auditable rather than a black box."))
    p_proc.add_argument("inputs", nargs="+",
                        help="files or folders (.gwy or raw formats)")
    p_proc.add_argument("--recipe", default="quick-clean",
                        help="recipe name (default: quick-clean). "
                             "See `afm-copilot recipes`.")
    p_proc.add_argument("--out", required=True, help="output directory")
    p_proc.set_defaults(func=cmd_process)

    p_thick = sub.add_parser(
        "thickness",
        help="measure a film step across images and write a PDF report",
        description=(
            "For a scratch experiment: the scratch exposes the substrate and "
            "the rest of the frame is intact film, so the height histogram has "
            "two levels and the thickness is the distance between them. Images "
            "with no measurable step are reported as such rather than given a "
            "plausible-looking number."))
    p_thick.add_argument("inputs", nargs="+",
                         help="files or folders (.gwy or raw formats)")
    p_thick.add_argument("--out", required=True, help="output directory")
    p_thick.add_argument("--name", default="thickness_report.pdf",
                         help="report filename (default: thickness_report.pdf)")
    p_thick.add_argument("--title", default="Film thickness",
                         help="title shown on the report")
    p_thick.add_argument("--band", type=int, default=16,
                         help="rows to average for the profile (default: 16)")
    p_thick.add_argument("--axis", default="horizontal",
                         choices=["horizontal", "vertical"],
                         help="profile direction (default: horizontal)")
    p_thick.add_argument("--recipe", default="clean-with-features",
                         help="recipe used to level before measuring "
                              "(default: clean-with-features, which masks the "
                              "raised region so it does not bias the fit)")
    p_thick.add_argument("--no-level", action="store_true",
                         help="skip levelling; use if the files are already "
                              "processed")
    p_thick.set_defaults(func=cmd_thickness)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

