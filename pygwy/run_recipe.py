# -*- coding: utf-8 -*-
"""
run_recipe.py  --  PYTHON 2.7 ONLY (PyGwy)

Executes a recipe -- an ordered list of Gwyddion operations -- on one or more
files. The recipe itself is decided on the Python 3 side and arrives as JSON,
so all the reasoning about *which* operations to run and *why* stays in
readable, testable Python 3. This script only carries them out.

    run_py27.ps1 pygwy\run_recipe.py --job job.json

The job file looks like:

    {
      "out_dir": "...",
      "steps": [ {"key": ..., "gwy_func": ..., "settings": {...}}, ... ],
      "files": ["...", ...]
    }

Prints one JSON document to stdout recording, per file and per step, the RMS
and z range before and after -- so the caller can report what each operation
actually changed rather than merely that it ran.

Python 2.7 constraints apply: no f-strings, no pathlib, no type hints.
"""

from __future__ import print_function

import json
import os
import sys

import gwy


def ensure_dir(path):
    if not os.path.isdir(path):
        os.makedirs(path)


def field_stats(field):
    return {
        "rms": field.get_rms(),
        "z_min": field.get_min(),
        "z_max": field.get_max(),
        "z_range": field.get_max() - field.get_min(),
    }


def apply_settings(settings):
    """
    Push a step's parameters into Gwyddion's global settings container.

    Gwyddion modules read their parameters from there rather than taking
    arguments, which is why every parameterised operation has to do this dance.
    """
    if not settings:
        return
    container = gwy.gwy_app_settings_get()
    for key, value in settings.items():
        if isinstance(value, bool):
            container.set_boolean_by_name(str(key), value)
        elif isinstance(value, int):
            container.set_int32_by_name(str(key), int(value))
        elif isinstance(value, float):
            container.set_double_by_name(str(key), float(value))
        else:
            container.set_string_by_name(str(key), str(value))


def has_mask(container, cid):
    try:
        return container.get_object_by_name("/%d/mask" % cid) is not None
    except Exception:
        return False


def run_steps(container, cid, steps):
    """Run every step in order, recording what each one changed."""
    field = container.get_object_by_name("/%d/data" % cid)
    log = []

    for step in steps:
        func = step["gwy_func"]
        record = {"key": step.get("key", func), "gwy_func": func,
                  "title": step.get("title", func), "applied": False,
                  "note": ""}

        if not gwy.gwy_process_func_exists(func):
            record["note"] = "not available in this Gwyddion build"
            log.append(record)
            continue

        # A repair step with nothing marked would either fail or silently do
        # nothing; saying so is more useful than either.
        if step.get("needs_mask") and not has_mask(container, cid):
            record["note"] = "skipped: no mask present for this step to act on"
            log.append(record)
            continue

        before = field_stats(field)
        try:
            apply_settings(step.get("settings"))
            gwy.gwy_app_data_browser_select_data_field(container, cid)
            gwy.gwy_process_func_run(func, container, gwy.RUN_IMMEDIATE)
            record["applied"] = True
        except Exception, e:
            record["note"] = "failed: %s" % e
            log.append(record)
            continue

        # The module may have replaced the field object rather than editing it.
        field = container.get_object_by_name("/%d/data" % cid)
        after = field_stats(field)
        record["before"] = before
        record["after"] = after
        record["rms_change"] = after["rms"] - before["rms"]
        if before["rms"] > 0:
            record["rms_change_percent"] = \
                100.0 * (after["rms"] - before["rms"]) / before["rms"]
        if step.get("creates_mask"):
            record["mask_created"] = has_mask(container, cid)
        log.append(record)

    return log, field


def process_file(path, steps, out_dir):
    stem = os.path.splitext(os.path.basename(path))[0]
    rec = {"source": path, "stem": stem, "ok": False, "error": "", "steps": []}

    try:
        container = gwy.gwy_file_load(path, gwy.RUN_NONINTERACTIVE)
    except Exception, e:
        rec["error"] = "load failed: %s" % e
        return rec
    if container is None:
        rec["error"] = "load returned nothing"
        return rec

    gwy.gwy_app_data_browser_add(container)
    try:
        ids = gwy.gwy_app_data_browser_get_data_ids(container)
    except Exception, e:
        rec["error"] = "cannot list channels: %s" % e
        return rec
    if not ids:
        rec["error"] = "no channels"
        return rec

    # Operate on the first channel; the Python 3 side has already decided
    # which file to send and expects its primary channel to be the topography.
    cid = ids[0]
    try:
        rec["channel"] = container.get_string_by_name("/%d/data/title" % cid)
    except Exception:
        rec["channel"] = ""

    field = container.get_object_by_name("/%d/data" % cid)
    rec["initial"] = field_stats(field)

    rec["steps"], field = run_steps(container, cid, steps)
    rec["final"] = field_stats(field)

    out_path = os.path.join(out_dir, stem + ".gwy")
    try:
        gwy.gwy_file_save(container, out_path, gwy.RUN_NONINTERACTIVE)
        rec["output"] = out_path
        rec["ok"] = True
    except Exception, e:
        rec["error"] = "save failed: %s" % e

    try:
        gwy.gwy_app_data_browser_remove(container)
    except Exception:
        pass
    return rec


def main():
    argv = sys.argv[1:]
    job_path = None
    i = 0
    while i < len(argv):
        if argv[i] == "--job":
            i += 1
            job_path = argv[i]
        i += 1

    if not job_path or not os.path.isfile(job_path):
        sys.stderr.write("Usage: run_recipe.py --job <job.json>\n")
        return 2

    fh = open(job_path, "r")
    try:
        job = json.load(fh)
    finally:
        fh.close()

    out_dir = job["out_dir"]
    ensure_dir(out_dir)
    steps = job["steps"]

    results = [process_file(p, steps, out_dir) for p in job["files"]]

    json.dump({"results": results,
               "n_ok": sum(1 for r in results if r["ok"]),
               "n_total": len(results)},
              sys.stdout, indent=2, sort_keys=True, default=repr)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
