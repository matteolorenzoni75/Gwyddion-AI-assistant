# -*- coding: utf-8 -*-
"""
survey_channels.py  --  PYTHON 2.7 ONLY (PyGwy)

Answers three questions about a folder of raw AFM files, before any processing
architecture is committed to:

  1. Which channels does each file actually contain? Specifically, are there
     BOTH trace and retrace height channels? That pair is the highest-value
     signal available -- it detects tracking failure, hysteresis and
     time-locked noise at once, and gives a reference image for scoring
     without needing ground truth.
  2. What acquisition metadata is stored? Scan rate and line rate let us
     PREDICT where mains hum should land in the 2D FFT, which is the strongest
     discriminator between periodic noise and genuine periodic sample
     structure.
  3. Do the .tiff files carry calibrated height data, or are they rendered
     pictures? (Asylum documents TIFF export as an image convenience.)

Usage, via tools/run_py27.ps1:
    run_py27.ps1 tools\survey_channels.py <folder> [<folder> ...]

Writes docs/data_survey/channel_survey.{json,md}.

Python 2.7 constraints apply: no f-strings, no pathlib, no type hints.
"""

from __future__ import print_function

import json
import os
import re
import sys

import gwy


HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(PROJECT_ROOT, "docs", "data_survey")

DATA_EXT = (".ibw", ".tiff", ".tif", ".gwy", ".spm", ".jpk")

# Channel titles that indicate a forward/backward pair. Asylum uses
# "HeightTrace"/"HeightRetrace"; other vendors use Fwd/Bwd or Up/Down.
TRACE_PAT = re.compile(r"(?<!re)trace|forward|\bfwd\b|\bup\b", re.I)
RETRACE_PAT = re.compile(r"retrace|backward|\bbwd\b|\bdown\b", re.I)

# Metadata keys worth pulling out for hum prediction and general provenance.
META_OF_INTEREST = re.compile(
    r"scan.*rate|line.*rate|scan.*speed|scan.*size|scan.*angle|rate|"
    r"setpoint|gain|amplitude|drive|date|time|point|line",
    re.I)


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def is_height_channel(title):
    """Height-like channels, excluding amplitude/phase/deflection/current."""
    t = (title or "").lower()
    if "height" in t or "topograph" in t or t.startswith("z"):
        return True
    return False


def channel_kind(title):
    """Classify a channel title as trace / retrace / unknown."""
    t = title or ""
    if RETRACE_PAT.search(t):
        return "retrace"
    if TRACE_PAT.search(t):
        return "trace"
    return "unpaired"


def describe_field(field):
    """Pull the physical dimensions out of a DataField."""
    try:
        zunit = field.get_si_unit_z().get_string(gwy.SI_UNIT_FORMAT_PLAIN)
    except Exception:
        zunit = "?"
    try:
        xyunit = field.get_si_unit_xy().get_string(gwy.SI_UNIT_FORMAT_PLAIN)
    except Exception:
        xyunit = "?"
    return {
        "xres": field.get_xres(),
        "yres": field.get_yres(),
        "xreal": field.get_xreal(),
        "yreal": field.get_yreal(),
        "xy_unit": xyunit,
        "z_unit": zunit,
        "z_min": field.get_min(),
        "z_max": field.get_max(),
        "rms": field.get_rms(),
    }


def read_metadata(container, cid):
    """Return acquisition metadata for one channel, filtered to useful keys."""
    meta = {}
    try:
        mc = container.get_object_by_name("/%d/meta" % cid)
    except Exception:
        return meta
    if mc is None:
        return meta
    try:
        keys = mc.keys_by_name()
    except Exception:
        return meta
    for k in keys:
        try:
            v = mc.get_string_by_name(k)
        except Exception:
            continue
        name = k.lstrip("/")
        if META_OF_INTEREST.search(name):
            meta[name] = v
    return meta


def survey_file(path):
    """Load one file through Gwyddion and describe every channel in it."""
    entry = {
        "file": os.path.basename(path),
        "path": path,
        "ok": False,
        "error": "",
        "channels": [],
    }
    try:
        container = gwy.gwy_file_load(path, gwy.RUN_NONINTERACTIVE)
    except Exception, e:
        entry["error"] = "load failed: %s" % e
        return entry
    if container is None:
        entry["error"] = "load returned nothing"
        return entry

    try:
        gwy.gwy_app_data_browser_add(container)
    except Exception:
        pass

    try:
        ids = gwy.gwy_app_data_browser_get_data_ids(container)
    except Exception, e:
        entry["error"] = "cannot list channels: %s" % e
        return entry

    for cid in ids:
        title = ""
        try:
            title = container.get_string_by_name("/%d/data/title" % cid) or ""
        except Exception:
            pass
        ch = {"id": cid, "title": title, "kind": channel_kind(title),
              "is_height": is_height_channel(title)}
        try:
            field = container.get_object_by_name("/%d/data" % cid)
            ch.update(describe_field(field))
        except Exception, e:
            ch["error"] = str(e)
        ch["meta"] = read_metadata(container, cid)
        entry["channels"].append(ch)

    entry["ok"] = True

    # The headline question: are there paired height trace + retrace channels?
    heights = [c for c in entry["channels"] if c["is_height"]]
    kinds = set(c["kind"] for c in heights)
    entry["n_channels"] = len(entry["channels"])
    entry["n_height_channels"] = len(heights)
    entry["has_trace_retrace_pair"] = ("trace" in kinds and "retrace" in kinds)

    try:
        gwy.gwy_app_data_browser_remove(container)
    except Exception:
        pass
    return entry


def collect_files(folders):
    found = []
    for folder in folders:
        if not os.path.isdir(folder):
            print("  (skipping, not a folder: %s)" % folder)
            continue
        for fn in sorted(os.listdir(folder)):
            if fn.lower().endswith(DATA_EXT):
                found.append(os.path.join(folder, fn))
    return found


def write_markdown(path, results):
    fh = open(path, "w")
    try:
        fh.write("# Raw data survey\n\n")
        fh.write("Generated by `tools/survey_channels.py` through Gwyddion's own\n")
        fh.write("file importers, so this reflects exactly what Gwyddion sees.\n\n")

        ok = [r for r in results if r["ok"]]
        paired = [r for r in ok if r.get("has_trace_retrace_pair")]
        fh.write("| | |\n|---|---|\n")
        fh.write("| Files read | %d of %d |\n" % (len(ok), len(results)))
        fh.write("| With a height trace+retrace pair | **%d** |\n\n" % len(paired))

        fh.write("## Per file\n\n")
        fh.write("| file | channels | height ch. | trace+retrace | size (px) |\n")
        fh.write("|---|---|---|---|---|\n")
        for r in results:
            if not r["ok"]:
                fh.write("| `%s` | - | - | load failed | %s |\n"
                         % (r["file"], r["error"].replace("|", "/")))
                continue
            first = r["channels"][0] if r["channels"] else {}
            size = "%sx%s" % (first.get("xres", "?"), first.get("yres", "?"))
            fh.write("| `%s` | %d | %d | %s | %s |\n" % (
                r["file"], r["n_channels"], r["n_height_channels"],
                "**yes**" if r["has_trace_retrace_pair"] else "no", size))
        fh.write("\n")

        fh.write("## Channels in detail\n\n")
        for r in results:
            if not r["ok"]:
                continue
            fh.write("### %s\n\n" % r["file"])
            fh.write("| id | title | kind | height? | px | real size | z unit | z range |\n")
            fh.write("|---|---|---|---|---|---|---|---|\n")
            for c in r["channels"]:
                zr = ""
                if "z_min" in c and "z_max" in c:
                    zr = "%.4g" % (c["z_max"] - c["z_min"])
                real = ""
                if "xreal" in c:
                    real = "%.4g x %.4g %s" % (c["xreal"], c["yreal"],
                                               c.get("xy_unit", ""))
                fh.write("| %s | %s | %s | %s | %sx%s | %s | %s | %s |\n" % (
                    c["id"], c["title"], c["kind"],
                    "yes" if c["is_height"] else "no",
                    c.get("xres", "?"), c.get("yres", "?"),
                    real, c.get("z_unit", "?"), zr))
            fh.write("\n")
            meta = {}
            for c in r["channels"]:
                meta.update(c.get("meta", {}))
            if meta:
                fh.write("Acquisition metadata found:\n\n")
                for k in sorted(meta):
                    fh.write("- `%s` = %s\n" % (k, meta[k]))
                fh.write("\n")
    finally:
        fh.close()


def main():
    folders = sys.argv[1:]
    if not folders:
        print("Usage: survey_channels.py <folder> [<folder> ...]")
        return 1

    ensure_dir(OUT_DIR)
    files = collect_files(folders)
    print("Found %d data file(s).\n" % len(files))

    results = []
    for path in files:
        print("Reading %s" % os.path.basename(path))
        r = survey_file(path)
        if r["ok"]:
            print("   %d channel(s), %d height, trace+retrace: %s"
                  % (r["n_channels"], r["n_height_channels"],
                     "YES" if r["has_trace_retrace_pair"] else "no"))
            for c in r["channels"]:
                print("      [%d] %-28s %s" % (c["id"], c["title"], c["kind"]))
        else:
            print("   FAILED: %s" % r["error"])
        results.append(r)

    json_path = os.path.join(OUT_DIR, "channel_survey.json")
    fh = open(json_path, "w")
    try:
        json.dump(results, fh, indent=2, sort_keys=True, default=repr)
    finally:
        fh.close()
    fh = open(json_path, "r")
    try:
        json.load(fh)
    except ValueError:
        print("ERROR: %s is not valid JSON." % json_path)
        raise
    finally:
        fh.close()

    md_path = os.path.join(OUT_DIR, "CHANNEL_SURVEY.md")
    write_markdown(md_path, results)

    ok = [r for r in results if r["ok"]]
    paired = [r for r in ok if r.get("has_trace_retrace_pair")]
    print("")
    print("=" * 60)
    print("Read %d of %d files." % (len(ok), len(results)))
    print("Files with a height trace+retrace pair: %d" % len(paired))
    print("Wrote %s" % json_path)
    print("Wrote %s" % md_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
