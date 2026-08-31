# -*- coding: utf-8 -*-
"""
selftest.py  --  PYTHON 2.7 ONLY (PyGwy)

Confirms the Python 2.7 side is healthy: gwy imports, its processing modules
registered themselves, and a real operation actually changes data. Prints one
JSON document to stdout.

Run it whenever the toolchain moves -- a new Gwyddion version, a different
machine, a reinstalled Python 2.7. It is the fastest way to tell "the bridge is
broken" from "my script is broken".
"""

from __future__ import print_function

import json
import sys

result = {"ok": False, "checks": {}, "errors": []}

try:
    import gwy
    result["checks"]["import_gwy"] = True
    result["gwy_version"] = gwy.gwy_version_string()
except Exception, e:
    result["checks"]["import_gwy"] = False
    result["errors"].append("import gwy failed: %s" % e)
    json.dump(result, sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    sys.exit(1)

result["python_version"] = sys.version.split()[0]

# Modules register themselves on import; if they had not, every process
# function would be missing and nothing else here would work.
probes = ["level", "align_rows", "scars_remove", "flatten_base", "polylevel",
          "fft_filter_1d", "outliers", "laplace"]
missing = [p for p in probes if not gwy.gwy_process_func_exists(p)]
result["checks"]["modules_registered"] = not missing
if missing:
    result["errors"].append("process functions missing: %s" % ", ".join(missing))

# End-to-end: build a tilted field, subtract a plane, confirm it flattened.
try:
    n = 64
    d = gwy.DataField(n, n, 1e-6, 1e-6, True)
    for row in range(n):
        for col in range(n):
            d.set_val(col, row, 1e-9 * (col + row))
    before = d.get_max() - d.get_min()

    c = gwy.Container()
    c.set_object_by_name("/0/data", d)
    gwy.gwy_app_data_browser_add(c)
    gwy.gwy_app_data_browser_select_data_field(c, 0)
    gwy.gwy_process_func_run("level", c, gwy.RUN_IMMEDIATE)

    after = d.get_max() - d.get_min()
    gwy.gwy_app_data_browser_remove(c)

    flattened = after < before * 1e-6
    result["checks"]["can_process"] = bool(flattened)
    result["plane_level_range_before"] = before
    result["plane_level_range_after"] = after
    if not flattened:
        result["errors"].append(
            "plane levelling did not flatten a synthetic tilt "
            "(%.3g -> %.3g)" % (before, after))
except Exception, e:
    result["checks"]["can_process"] = False
    result["errors"].append("processing test failed: %s" % e)

result["ok"] = all(result["checks"].values())

json.dump(result, sys.stdout, indent=2, sort_keys=True)
sys.stdout.write("\n")
sys.exit(0 if result["ok"] else 1)
