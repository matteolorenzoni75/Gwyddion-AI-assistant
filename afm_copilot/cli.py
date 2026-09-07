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
from afm_copilot.compare import build_comparison_report
from afm_copilot.gwy_io import Channel, load_channels, load_height
from afm_copilot.ops import (RECIPES, compare_logs, describe_source,
                             get_recipe, read_log, recipe_from_log)
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


def cmd_copy_processing(args: argparse.Namespace) -> int:
    """Repeat one scan's processing on others."""
    reference = Path(args.reference)
    if not reference.is_file():
        print(f"No such file: {reference}", file=sys.stderr)
        return 1

    entries = read_log(reference, channel=args.channel)
    if not entries:
        print(f"{reference.name} carries no processing history.\n"
              f"Open it in Gwyddion, do the processing there, save it, and try "
              f"again — Gwyddion records what you did inside the file.",
              file=sys.stderr)
        return 1

    try:
        recipe = recipe_from_log(entries, key="recorded",
                                 title=f"Processing copied from {reference.stem}",
                                 source_name=reference.name)
    except ValueError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1

    importer = describe_source(entries)
    print(f"Read {len(recipe.steps)} processing step(s) from {reference.name}"
          + (f" (originally read by Gwyddion's '{importer}' importer)"
             if importer else "") + ":\n")
    print(recipe.explain())
    print()

    if args.show_only:
        print("Nothing processed — this was a preview. Drop --show-only to "
              "apply it.")
        return 0

    if not args.inputs:
        print("Give one or more files or folders to apply this to, or use "
              "--show-only.", file=sys.stderr)
        return 1

    gwy_files, raw_files = _collect_inputs(args.inputs)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        bridge = GwyBridge()
        if raw_files:
            print(f"Converting {len(raw_files)} raw file(s)...")
            report = bridge.convert_raw(raw_files, out_dir / "_gwy")
            gwy_files.extend(Path(r["gwy"]) for r in report["results"] if r["ok"])
        targets = [p for p in sorted(set(gwy_files)) if p != reference]
        if not targets:
            print("No scans to apply it to.", file=sys.stderr)
            return 1
        print(f"Applying to {len(targets)} scan(s)...\n")
        result = bridge.run_recipe(recipe, targets, out_dir / "processed")
    except BridgeError as exc:
        print(f"Failed: {exc}", file=sys.stderr)
        return 1

    print(f"Done: {result['n_ok']}/{result['n_total']} scan(s).\n")
    mismatches = 0
    for rec in result["results"]:
        if not rec["ok"]:
            print(f"  {rec['stem']}: FAILED — {rec['error']}")
            continue
        print(f"  {rec['stem']}: RMS {rec['initial']['rms']:.4g} -> "
              f"{rec['final']['rms']:.4g} m")
        for step in rec["steps"]:
            if step["note"]:
                print(f"      {step['title']:<34} {step['note']}")

        # Read back what Gwyddion recorded on the result and check it matches.
        # A setting written to the wrong place fails silently, so comparing the
        # two logs is the only way to know the copy was faithful.
        problems = compare_logs(entries, read_log(rec["output"]))
        for problem in problems:
            print(f"      ! {problem}")
        mismatches += len(problems)

    if mismatches:
        print(f"\n{mismatches} setting(s) did not carry over. Those steps ran "
              f"with Gwyddion's own defaults\ninstead of the reference's "
              f"values — check the result before relying on it.")
    elif result["n_ok"]:
        print("\nEvery recorded setting was reproduced exactly.")

    json_path = out_dir / "copy_processing_summary.json"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"\nProcessed files: {out_dir / 'processed'}")
    print(f"Full record:     {json_path}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    """Two columns: every scan as it arrived and as it came out."""
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    pdf = out_dir / args.name

    try:
        summary = build_comparison_report(
            args.raw, args.processed, pdf, title=args.title,
            png_dir=out_dir / "pages")
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1

    print(f"{summary['n_scans']} scan(s), {summary['n_processed']} processed.\n")
    print(f"  {'scan':<32} {'RMS raw':>10} {'RMS after':>10} "
          f"{'tilt raw':>9} {'tilt after':>10}")
    for s in summary["scans"]:
        raw, out = s["raw"], s["processed"]
        print(f"  {s['name'][:32]:<32} {raw['rms'] * 1e9:>9.2f}n "
              f"{(out['rms'] * 1e9 if out else float('nan')):>9.2f}n "
              f"{raw['tilt'] * 100:>8.0f}% "
              f"{(out['tilt'] * 100 if out else float('nan')):>9.0f}%")

    print(f"\nReport: {pdf}")
    json_path = out_dir / "comparison.json"
    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"Numbers: {json_path}")
    print("\nA fall in RMS is not by itself an improvement — read the table "
          "beside the\nimages, not instead of them.")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    """Say what each scan needs, and why, without touching anything."""
    from afm_copilot.decide import plan_for

    gwy_files, raw_files = _collect_inputs(args.inputs)
    if raw_files:
        work = Path(args.out) if args.out else Path(".afm_plan")
        try:
            report = GwyBridge().convert_raw(raw_files, work / "_gwy")
        except BridgeError as exc:
            print(f"Could not read the raw files: {exc}", file=sys.stderr)
            return 1
        gwy_files.extend(Path(r["gwy"]) for r in report["results"] if r["ok"])

    if not gwy_files:
        print("Nothing to look at.", file=sys.stderr)
        return 1

    plans = []
    for path in sorted(set(gwy_files)):
        try:
            channel = load_height(path)
        except (ValueError, OSError) as exc:
            print(f"  ! {path.name}: {exc}", file=sys.stderr)
            continue
        plans.append((path, plan_for(channel)))

    if args.detail:
        for path, plan in plans:
            print(f"\n=== {path.name} ===")
            print(plan.explain())
        print()
    else:
        print(f"{'scan':<34} {'tilt':>5} {'objects':>8} {'order':>6}   recipe")
        print("-" * 78)
        for path, plan in plans:
            print(f"{path.stem[:34]:<34} {plan.tilt * 100:>4.0f}% "
                  f"{plan.object_fraction * 100:>7.0f}% "
                  f"{plan.background_degree:>6}   {plan.recipe_key}")
        print("\nRun again with --detail to see the reasoning for each.")

    print("\nNothing was processed. These are recommendations, measured from "
          "each scan.")
    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        payload = [{
            "scan": p.name,
            "tilt": plan.tilt,
            "object_fraction": plan.object_fraction,
            "background_degree": plan.background_degree,
            "already_levelled": plan.already_levelled,
            "recipe": plan.recipe_key,
            "explained_by_degree": plan.explained_by_degree,
            "notes": plan.notes,
        } for p, plan in plans]
        path = out_dir / "plan.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"Details: {path}")
    return 0


def cmd_batch(args: argparse.Namespace) -> int:
    """Everything, on a folder: the normal level of operation."""
    from afm_copilot import batch

    out = Path(args.out)
    summary = batch.run([Path(p) for p in args.inputs], out,
                        deduplicate=not args.keep_duplicates,
                        do_clean=not args.no_clean)

    if not summary["scans_read"]:
        print("Nothing to read.", file=sys.stderr)
        return 1

    print(f"Read {summary['scans_read']} scan(s).\n")
    print(f"  kept          {summary['kept']:>4}"
          f"   ({summary['good']} as they were, "
          f"{summary['needed_work']} needing correction)")
    print(f"  cropped       {summary['cropped']:>4}   stopped early, trimmed "
          "to the part that has data")
    print(f"  repeats       {summary['duplicates']:>4}   the same area scanned "
          "again")
    print(f"  set aside     {summary['discarded']:>4}   not worth using")
    if summary.get("not_topography"):
        print(f"  not height    {summary['not_topography']:>4}   other "
              "channels, kept for when we read them")
    if summary["unreadable"]:
        print(f"  could not read{summary['unreadable']:>4}   listed below, "
              "not skipped")

    if summary.get("cleaned"):
        print(f"\nCleaned {summary['cleaned']}, by what each one needed:\n")
        for key, count in summary.get("recipes_used", {}).items():
            print(f"  {key:<22} {count:>4}")
    sized = [r for r in summary["results"] if r.get("object_true_radius_nm")]
    if sized:
        from_image = summary.get("tip_from_image", 0)
        print(f"\nObject sizes are corrected for the probe. {from_image} scan(s)"
              " could bound the tip\nfrom their own features; the rest assume "
              "the nominal 10 nm of an AC160.")

    lost = [r for r in summary["results"] if r.get("over_flattened")]
    if lost:
        print(f"\nLook at these {len(lost)}: the cleaning took more roughness "
              "than the background\ncan account for, so some of what it removed "
              "was surface, not artifact.\n")
        for r in lost:
            kept_pct = 100.0 * r["rms_after_nm"] / r["rms_before_nm"]
            print(f"  {r['name'][:38]:<38} {kept_pct:5.1f}% of the roughness "
                  f"left   ({r['recipe']})")
        print("\n  Nothing was chosen differently on their account -- which "
              "recipe is right\n  depends on what the sample is, and that is "
              "your call, not a rule of thumb.")

    unread = [r for r in summary["results"] if r["verdict"] == "unreadable"]
    if unread:
        print(f"\nCould not be read at all ({len(unread)}):\n")
        for r in unread[:12]:
            print(f"  {r['name'][:40]:<40} {r['why'][0][:60]}")
        if len(unread) > 12:
            print(f"  ... and {len(unread) - 12} more, all in batch.json")

    aside = [r for r in summary["results"] if r["verdict"] == "discard"]
    if aside:
        print("\nSet aside, and why:\n")
        for r in aside:
            print(f"  {r['name']}")
            for why in r["why"]:
                print(f"     {why}")

    print(f"\nEverything, scan by scan: {out / 'batch.json'}")
    print("Nothing was deleted. A scan set aside is recorded with its reason, "
          "so\nyou can look at it and disagree.")
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

    p_copy = sub.add_parser(
        "copy-processing",
        help="repeat one scan's processing on others",
        description=(
            "Gwyddion records what it did inside every file it saves. Process "
            "one scan the way you want — here or by hand in Gwyddion itself — "
            "then use it as the reference and the same steps, with the same "
            "settings, are applied to every scan you name."))
    p_copy.add_argument("--from", dest="reference", required=True,
                        metavar="SCAN.gwy",
                        help="the scan whose processing should be copied")
    p_copy.add_argument("inputs", nargs="*",
                        help="files or folders to apply it to")
    p_copy.add_argument("--out", default="copied",
                        help="output directory (default: copied)")
    p_copy.add_argument("--channel", type=int, default=0,
                        help="which channel's history to read (default: 0)")
    p_copy.add_argument("--show-only", action="store_true",
                        help="print what was recorded without processing "
                             "anything")
    p_copy.set_defaults(func=cmd_copy_processing)

    p_cmp = sub.add_parser(
        "compare",
        help="side-by-side report of every scan, raw and processed",
        description=(
            "One row per scan, two columns: as it arrived and as it came out, "
            "with the numbers under each. Makes over-processing visible — a "
            "correction that halved the roughness while flattening a real "
            "feature looks obviously wrong side by side, and looks like "
            "success in a table."))
    p_cmp.add_argument("--raw", required=True,
                       help="folder of the original .gwy scans")
    p_cmp.add_argument("--processed", required=True,
                       help="folder of the processed .gwy scans")
    p_cmp.add_argument("--out", default="comparison", help="output directory")
    p_cmp.add_argument("--name", default="raw_vs_processed.pdf",
                       help="report filename")
    p_cmp.add_argument("--title", default="Raw and processed",
                       help="title shown on the report")
    p_cmp.set_defaults(func=cmd_compare)

    p_plan = sub.add_parser(
        "plan",
        help="say what each scan needs, and why, without processing anything",
        description=(
            "Measures each scan and recommends how to treat it — how much tilt "
            "it has, whether anything stands above the surface, and what order "
            "of background is genuinely there. Nothing is changed; this is the "
            "reasoning, shown before any decision is acted on."))
    p_plan.add_argument("inputs", nargs="+", help="files or folders")
    p_plan.add_argument("--detail", action="store_true",
                        help="show the full reasoning for each scan")
    p_plan.add_argument("--out", default=None,
                        help="also write the measurements to this directory")
    p_plan.set_defaults(func=cmd_plan)

    p_batch = sub.add_parser(
        "batch",
        help="the whole path on a folder: check, crop, measure, report",
        description=(
            "The normal way to use this. Point it at a day's or a month's "
            "measurements and it reads them, judges whether each is worth "
            "using, crops the ones that stopped early, sets aside the "
            "duplicates, and measures the rest — with a reason recorded "
            "against every scan it leaves out. Nothing is deleted."))
    p_batch.add_argument("inputs", nargs="+", help="files or folders")
    p_batch.add_argument("--out", required=True, help="where to write results")
    p_batch.add_argument("--keep-duplicates", action="store_true",
                         help="measure repeated scans of the same area too")
    p_batch.add_argument("--no-clean", action="store_true",
                         help="judge and measure only, leave the scans alone")
    p_batch.set_defaults(func=cmd_batch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

