# -*- coding: utf-8 -*-
"""
query_api.py  --  read the generated PyGwy inventory and print a menu section.

Runs under either Python 2.7 or Python 3, since it only reads the JSON that
tools/introspect_pygwy.py produced. Handy for answering "what can Gwyddion
actually do in category X" without opening the 1 MB JSON by hand.

Usage:
    python tools/query_api.py                 # list all sections with counts
    python tools/query_api.py "_Level"        # list one section's functions
    python tools/query_api.py --search flat   # search names + tooltips
"""

from __future__ import print_function

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(os.path.dirname(HERE), "docs", "pygwy_api", "pygwy_api.json")


def load():
    fh = open(JSON_PATH, "r")
    try:
        return json.load(fh)
    finally:
        fh.close()


def group_by_section(funcs):
    groups = {}
    for f in funcs:
        mp = f.get("menu_path") or "/(no menu)"
        top = mp.lstrip("/").split("/")[0]
        groups.setdefault(top, []).append(f)
    return groups


def main():
    data = load()
    funcs = data["process_functions"]
    groups = group_by_section(funcs)

    args = sys.argv[1:]

    if args and args[0] == "--search":
        term = args[1].lower() if len(args) > 1 else ""
        hits = [f for f in funcs
                if term in f["name"].lower() or term in (f["tooltip"] or "").lower()]
        print("%d match(es) for %r\n" % (len(hits), term))
        for f in sorted(hits, key=lambda x: x["name"]):
            print("  %-22s %-38s %s" % (f["name"], f["menu_path"], f["tooltip"]))
        return

    if args:
        section = args[0]
        if section not in groups:
            print("No such section. Available:")
            for s in sorted(groups):
                print("   %s" % s)
            return
        print("=== %s (%d) ===\n" % (section, len(groups[section])))
        for f in sorted(groups[section], key=lambda x: x["name"]):
            print("  %-22s %s" % (f["name"], f["tooltip"]))
            print("  %-22s %s" % ("", f["menu_path"]))
        return

    print("PyGwy inventory: %d process functions, %d file functions, %d classes\n"
          % (len(funcs), len(data["file_functions"]), len(data["classes"])))
    for s in sorted(groups):
        print("  %-24s %d" % (s, len(groups[s])))


if __name__ == "__main__":
    main()
