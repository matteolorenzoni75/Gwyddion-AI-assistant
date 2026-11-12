# -*- coding: utf-8 -*-
"""Python 2.7 read-only Gwyddion channel/calibration probe.

Accepts a PRIVATE JSON job file with IDs and paths. Returns anonymous JSON
records with numeric dimensions and units only; never prints source names or
metadata contents. Never converts, saves, or changes any scan.
"""
from __future__ import print_function
import json
import math
import sys
import gwy


def kind_of(title, zunit):
    t = (title or "").lower()
    blocked = ("phase", "amplitude", "deflection", "current", "potential",
               "friction", "lateral", "frequency", "adhesion", "stiffness")
    if any(word in t for word in blocked):
        return "non-height"
    if "height" in t or "topograph" in t or "zsensor" in t or "z sensor" in t:
        return "height"
    return "height" if zunit == "m" else "other"


def direction_of(title):
    t = (title or "").lower()
    if "retrace" in t or "backward" in t:
        return "retrace"
    if "trace" in t or "forward" in t:
        return "trace"
    return "unspecified"


def finite_number(value):
    try:
        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except (TypeError, ValueError, OverflowError):
        return None


def probe(entry):
    record = {"id": entry["id"], "status": "read_failed", "n_height": 0,
              "trace_retrace_height": False, "channels": []}
    container = None
    try:
        container = gwy.gwy_file_load(entry["path"], gwy.RUN_NONINTERACTIVE)
        if container is None:
            return record
        gwy.gwy_app_data_browser_add(container)
        ids = gwy.gwy_app_data_browser_get_data_ids(container)
        directions = set()
        for cid in ids:
            field = container.get_object_by_name("/%d/data" % cid)
            if field is None:
                continue
            try:
                title = container.get_string_by_name("/%d/data/title" % cid) or ""
            except Exception:
                title = ""
            try:
                xy_unit = field.get_si_unit_xy().get_string(gwy.SI_UNIT_FORMAT_PLAIN)
                z_unit = field.get_si_unit_z().get_string(gwy.SI_UNIT_FORMAT_PLAIN)
            except Exception:
                xy_unit = "?"
                z_unit = "?"
            xreal, yreal = field.get_xreal(), field.get_yreal()
            label = kind_of(title, z_unit)
            direction = direction_of(title)
            if label == "height":
                directions.add(direction)
            calibrated = (xy_unit == "m" and z_unit == "m" and
                          xreal > 0 and yreal > 0 and
                          not math.isnan(xreal) and not math.isnan(yreal) and
                          not math.isinf(xreal) and not math.isinf(yreal))
            record["channels"].append({
                "kind": label, "direction": direction,
                "xres": field.get_xres(), "yres": field.get_yres(),
                "xreal_m": finite_number(xreal), "yreal_m": finite_number(yreal),
                "xy_unit": xy_unit, "z_unit": z_unit,
                "z_range_si": finite_number(field.get_max() - field.get_min()),
                "calibration_ok": bool(calibrated) if label == "height" else None,
            })
        record["n_height"] = len([c for c in record["channels"] if c["kind"] == "height"])
        record["trace_retrace_height"] = "trace" in directions and "retrace" in directions
        record["status"] = "ok"
    except Exception:
        record["status"] = "read_failed"
    finally:
        if container is not None:
            try:
                gwy.gwy_app_data_browser_remove(container)
            except Exception:
                pass
    return record


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "--job":
        print('{"results": []}')
        return 2
    with open(sys.argv[2], "rb") as fh:
        job = json.load(fh)
    results = [probe(item) for item in job.get("files", [])]
    json.dump({"results": results}, sys.stdout, sort_keys=True)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
