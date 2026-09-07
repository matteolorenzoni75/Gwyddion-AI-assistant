# -*- coding: utf-8 -*-
"""
Gwyddion's own automatic colour range, for every file given.

Python 2.7, run through the bridge. `gwy_data_field_get_autorange` is what
Gwyddion uses to choose a false-colour range on its own: the bulk of the height
distribution with the tails cut off. Its exact method is documented as
unspecified, which is precisely why it is asked for rather than imitated -- an
approximation would look almost right and be quietly different from what the
user sees when they open the same file.

One subprocess for the whole batch: the range is a couple of numbers per file,
and a round trip per scan would cost more than the ranges are worth.

    run_py27.ps1 pygwy\autorange.py <file.gwy> [<file.gwy> ...]
"""

import json
import os
import sys

import gwy


def main():
    out = {"ok": True, "ranges": {}, "failed": {}}

    for path in sys.argv[1:]:
        stem = os.path.splitext(os.path.basename(path))[0]
        try:
            container = gwy.gwy_file_load(path, gwy.RUN_NONINTERACTIVE)
            gwy.gwy_app_data_browser_add(container)
            ids = gwy.gwy_app_data_browser_get_data_ids(container)
            if not ids:
                out["failed"][stem] = "no channels"
                continue
            field = container.get_object_by_name("/%d/data" % ids[0])
            low, high = field.get_autorange()
            out["ranges"][stem] = [float(low), float(high)]
        except Exception, exc:                                 # noqa: E722
            out["failed"][stem] = "%s: %s" % (type(exc).__name__, exc)

    sys.stdout.write(json.dumps(out))


main()
