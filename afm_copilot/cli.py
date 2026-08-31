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
from afm_copilot.render import (RenderStyle, group_by_scale, group_label,
                                render_batch)

RAW_SUFFIXES = {".ibw", ".tiff", ".tif", ".spm", ".jpk", ".sxm", ".top",
                ".stp", ".nid", ".mi", ".par", ".ezd", ".afm"}


def _parse_length(text: str) -> float:
    """Accept '5um', '500nm', '1.2e-5' and return metres."""
    t = text.strip().lower().replace("µ", "u")
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

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
