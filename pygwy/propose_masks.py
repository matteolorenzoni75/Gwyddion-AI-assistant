# -*- coding: utf-8 -*-
"""Run independent Gwyddion grain-marking proposals (Python 2.7/PyGwy)."""

from __future__ import print_function

import json
import os
import sys

import gwy


def apply_settings(settings):
    container = gwy.gwy_app_settings_get()
    for key, value in settings.items():
        if isinstance(value, bool):
            container.set_boolean_by_name(str(key), value)
        elif isinstance(value, int):
            container.set_int32_by_name(str(key), value)
        elif isinstance(value, float):
            container.set_double_by_name(str(key), value)
        else:
            container.set_string_by_name(str(key), str(value))


def has_mask(container, cid):
    try:
        return container.get_object_by_name("/%d/mask" % cid) is not None
    except Exception:
        return False


def process(job):
    record = {"source": job["source"], "method": job["method"]["key"],
              "output": job["output"], "ok": False, "error": ""}
    try:
        container = gwy.gwy_file_load(job["source"], gwy.RUN_NONINTERACTIVE)
        if container is None:
            record["error"] = "load returned nothing"
            return record
        gwy.gwy_app_data_browser_add(container)
        ids = gwy.gwy_app_data_browser_get_data_ids(container)
        if not ids:
            record["error"] = "no channels"
            return record
        cid = ids[0]
        func = job["method"]["gwy_func"]
        if not gwy.gwy_process_func_exists(func):
            record["error"] = "process function not available: " + func
            return record
        # Each candidate starts with no previous proposal or manual mask.  The
        # manual mask is input evidence elsewhere; it must not bias a trial.
        try:
            container.remove_by_name("/%d/mask" % cid)
        except Exception:
            pass
        apply_settings(job["method"].get("settings", {}))
        gwy.gwy_app_data_browser_select_data_field(container, cid)
        gwy.gwy_process_func_run(func, container, gwy.RUN_IMMEDIATE)
        if not has_mask(container, cid):
            record["error"] = "method marked no pixels"
            return record
        parent = os.path.dirname(job["output"])
        if not os.path.isdir(parent):
            os.makedirs(parent)
        gwy.gwy_file_save(container, job["output"], gwy.RUN_NONINTERACTIVE)
        record["ok"] = True
        return record
    except Exception, exc:
        record["error"] = str(exc)
        return record
    finally:
        try:
            gwy.gwy_app_data_browser_remove(container)
        except Exception:
            pass


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--job":
        sys.stderr.write("Usage: propose_masks.py --job JOB.json\n")
        return 2
    fh = open(sys.argv[2], "r")
    try:
        job = json.load(fh)
    finally:
        fh.close()
    results = [process(item) for item in job.get("jobs", [])]
    json.dump({"results": results,
               "n_ok": sum(1 for result in results if result["ok"]),
               "n_total": len(results)}, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
