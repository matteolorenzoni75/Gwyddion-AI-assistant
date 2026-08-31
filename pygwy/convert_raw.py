# -*- coding: utf-8 -*-
"""
convert_raw.py  --  PYTHON 2.7 ONLY (PyGwy)

The one job the Python 3 side cannot do for itself: read any of the 176 file
formats Gwyddion understands, and hand them over as .gwy plus a metadata
sidecar. Everything downstream (rendering, profiles, reports) then works in
Python 3, where gwyfile reads .gwy natively and fast.

Called by afm_copilot.bridge, not usually by hand.

    run_py27.ps1 pygwy\convert_raw.py --out <dir> <file> [<file> ...]

For each input it writes:
    <out>/<stem>.gwy        every channel Gwyddion found
    <out>/<stem>.meta.json  channel list + acquisition metadata

and prints one JSON document to stdout summarising the batch, so the caller
never has to parse human-readable output.

Python 2.7 constraints apply: no f-strings, no pathlib, no type hints.
"""

from __future__ import print_function

import json
import os
import sys

import gwy


# Acquisition metadata worth carrying forward. Scan rate and pixel counts let
# us predict where mains hum must land in the FFT; the gains and the
# setpoint/free-amplitude ratio predict feedback artifacts. See
# docs/data_survey/FINDINGS.md.
META_KEYS_WANTED = (
    "scanrate", "scan rate", "scanpoints", "scanlines", "scansize",
    "fastscansize", "slowscansize", "scanangle", "scanspeed", "sample rate",
    "scan time", "integralgain", "proportionalgain", "setpoint",
    "freeairamplitude", "drivefrequency", "date", "time",
    "line direction", "set point", "z servo gain",
)


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def wanted(key):
    k = key.lower()
    for w in META_KEYS_WANTED:
        if w in k:
            return True
    return False


def read_meta(container, cid):
    """Acquisition metadata for one channel, filtered to the useful keys."""
    out = {}
    try:
        mc = container.get_object_by_name("/%d/meta" % cid)
    except Exception:
        return out
    if mc is None:
        return out
    try:
        keys = mc.keys_by_name()
    except Exception:
        return out
    for k in keys:
        name = k.lstrip("/")
        if not wanted(name):
            continue
        try:
            out[name] = mc.get_string_by_name(k)
        except Exception:
            pass
    return out


def describe(container, cid):
    """Physical description of one channel."""
    info = {"id": cid, "title": ""}
    try:
        info["title"] = container.get_string_by_name("/%d/data/title" % cid) or ""
    except Exception:
        pass
    try:
        f = container.get_object_by_name("/%d/data" % cid)
    except Exception, e:
        info["error"] = str(e)
        return info
    info["xres"] = f.get_xres()
    info["yres"] = f.get_yres()
    info["xreal"] = f.get_xreal()
    info["yreal"] = f.get_yreal()
    info["z_min"] = f.get_min()
    info["z_max"] = f.get_max()
    info["rms"] = f.get_rms()
    try:
        info["z_unit"] = f.get_si_unit_z().get_string(gwy.SI_UNIT_FORMAT_PLAIN)
        info["xy_unit"] = f.get_si_unit_xy().get_string(gwy.SI_UNIT_FORMAT_PLAIN)
    except Exception:
        info["z_unit"] = info["xy_unit"] = "?"
    info["meta"] = read_meta(container, cid)
    return info


def convert(path, out_dir):
    stem = os.path.splitext(os.path.basename(path))[0]
    rec = {"source": path, "stem": stem, "ok": False, "error": "", "channels": []}

    try:
        container = gwy.gwy_file_load(path, gwy.RUN_NONINTERACTIVE)
    except Exception, e:
        rec["error"] = "load failed: %s" % e
        return rec
    if container is None:
        rec["error"] = "load returned nothing"
        return rec

    try:
        gwy.gwy_app_data_browser_add(container)
    except Exception:
        pass

    try:
        ids = gwy.gwy_app_data_browser_get_data_ids(container)
    except Exception, e:
        rec["error"] = "cannot list channels: %s" % e
        return rec

    for cid in ids:
        rec["channels"].append(describe(container, cid))

    gwy_path = os.path.join(out_dir, stem + ".gwy")
    try:
        gwy.gwy_file_save(container, gwy_path, gwy.RUN_NONINTERACTIVE)
        rec["gwy"] = gwy_path
    except Exception, e:
        rec["error"] = "save failed: %s" % e
        return rec

    meta_path = os.path.join(out_dir, stem + ".meta.json")
    fh = open(meta_path, "w")
    try:
        json.dump(rec, fh, indent=2, sort_keys=True, default=repr)
    finally:
        fh.close()
    rec["meta_json"] = meta_path
    rec["ok"] = True

    try:
        gwy.gwy_app_data_browser_remove(container)
    except Exception:
        pass
    return rec


def main():
    argv = sys.argv[1:]
    out_dir = None
    inputs = []
    i = 0
    while i < len(argv):
        if argv[i] == "--out":
            i += 1
            out_dir = argv[i]
        else:
            inputs.append(argv[i])
        i += 1

    if out_dir is None or not inputs:
        sys.stderr.write("Usage: convert_raw.py --out <dir> <file> [<file> ...]\n")
        return 2

    ensure_dir(out_dir)
    results = [convert(p, out_dir) for p in inputs]

    # stdout is the machine-readable channel; anything chatty goes to stderr.
    json.dump({"results": results,
               "n_ok": sum(1 for r in results if r["ok"]),
               "n_total": len(results)},
              sys.stdout, indent=2, sort_keys=True, default=repr)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
