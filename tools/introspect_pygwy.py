# -*- coding: utf-8 -*-
"""
introspect_pygwy.py  --  PYTHON 2.7 ONLY (runs against Gwyddion's PyGwy binding)

Builds a complete, VERIFIED inventory of the PyGwy API available on this machine:

  1. Every registered *process* function (Data Process menu), with its menu path,
     tooltip and supported run types.
  2. Every registered *file* function (import/export formats).
  3. Every class exposed by the `gwy` module, with its methods and doc strings.
  4. Every module-level function and constant.

Why the DLL string-scan: PyGwy exposes gwy_process_func_exists()/get_menu_path()
but no "list all functions" call. Gwyddion bundles its process modules into
lib/gwyddion/modules/process/process.dll, and every registered function name
appears there as a literal. So we harvest candidate identifiers from the binary
and then CONFIRM each one through the real API. Nothing is guessed: a name only
reaches the output if gwy_process_func_exists() returned True for it.

Run it via tools/run_py27.ps1, or directly with the Gwyddion bin directory on
PATH and PYTHONPATH. Outputs land in docs/pygwy_api/.

Python 2.7 constraints apply: no f-strings, no pathlib, no type hints.
"""

from __future__ import print_function

import json
import os
import re
import sys

import gwy


# --------------------------------------------------------------------------
# Paths
# --------------------------------------------------------------------------

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(HERE)
OUT_DIR = os.path.join(PROJECT_ROOT, "docs", "pygwy_api")

GWY_ROOT = os.environ.get("GWYDDION_ROOT", r"C:\Program Files (x86)\Gwyddion")
MODULE_DIR = os.path.join(GWY_ROOT, "lib", "gwyddion", "modules")

# Identifiers Gwyddion uses for registered functions: lowercase, digits, underscore.
IDENT_RE = re.compile(r"[a-z][a-z0-9_]{2,63}")

# Run-type flag names, resolved from the gwy module rather than hardcoded.
# Hardcoding these was wrong: the real values are NONINTERACTIVE=1,
# INTERACTIVE=2, IMMEDIATE=4, so an assumed 1/2 mislabelled every function
# and reported the genuinely immediate ones as "UNKNOWN(4)".
RUN_TYPE_NAMES = [
    "RUN_NONINTERACTIVE",
    "RUN_INTERACTIVE",
    "RUN_IMMEDIATE",
]

# File-operation flag names, resolved from the gwy module so we never hardcode
# values that could drift between Gwyddion versions.
FILE_OP_NAMES = [
    "FILE_OPERATION_DETECT",
    "FILE_OPERATION_LOAD",
    "FILE_OPERATION_SAVE",
    "FILE_OPERATION_EXPORT",
]


def ensure_dir(path):
    """os.makedirs with exist_ok, Python 2.7 style."""
    if not os.path.isdir(path):
        os.makedirs(path)


# --------------------------------------------------------------------------
# Candidate harvesting
# --------------------------------------------------------------------------

def harvest_strings(dll_path):
    """Return the set of identifier-like ASCII strings inside a binary file."""
    found = set()
    if not os.path.isfile(dll_path):
        return found
    fh = open(dll_path, "rb")
    try:
        blob = fh.read()
    finally:
        fh.close()
    for match in IDENT_RE.findall(blob):
        found.add(match)
    return found


def harvest_all_candidates():
    """Collect candidate names from every module DLL plus the core binaries."""
    candidates = set()
    scanned = []
    for sub in ("process", "file", "graph", "volume", "xyz", "cmap", "tool", "layer"):
        d = os.path.join(MODULE_DIR, sub)
        if not os.path.isdir(d):
            continue
        for fn in os.listdir(d):
            if fn.lower().endswith(".dll"):
                full = os.path.join(d, fn)
                candidates |= harvest_strings(full)
                scanned.append(full)
    return candidates, scanned


# --------------------------------------------------------------------------
# Verification through the real API
# --------------------------------------------------------------------------

def decode_run_types(value):
    """Turn the run-type bitmask into a readable list."""
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return ["RUN_NONE"]
    if not raw:
        return ["RUN_NONE"]
    out = []
    for const in RUN_TYPE_NAMES:
        bit = getattr(gwy, const, None)
        if bit is None:
            continue
        try:
            bit = int(bit)
        except (TypeError, ValueError):
            continue
        if bit and (raw & bit):
            out.append(const)
    if not out:
        out.append("UNKNOWN(%d)" % raw)
    return out


def safe_call(fn, name, default=None):
    """Call a PyGwy accessor, swallowing failures for functions that lack the attr."""
    try:
        return fn(name)
    except Exception:
        return default


def collect_process_funcs(candidates):
    """Verify each candidate against gwy_process_func_exists and gather metadata."""
    funcs = []
    for name in sorted(candidates):
        try:
            if not gwy.gwy_process_func_exists(name):
                continue
        except Exception:
            continue
        entry = {
            "name": name,
            "menu_path": safe_call(gwy.gwy_process_func_get_menu_path, name, ""),
            "tooltip": safe_call(gwy.gwy_process_func_get_tooltip, name, ""),
            "stock_id": safe_call(gwy.gwy_process_func_get_stock_id, name, ""),
            "run_types": decode_run_types(
                safe_call(gwy.gwy_process_func_get_run_types, name, 0)
            ),
        }
        funcs.append(entry)
    return funcs


def decode_file_operations(value):
    """
    Turn the file-operation bitmask into (int, [names]).

    gwy_file_func_get_operations() returns a GObject *flags* object. Those
    subclass int, so json.dump() will happily serialise one -- but it emits the
    object's repr (`<flags GWY_FILE_OPERATION_LOAD of type ...>`) unquoted,
    which silently produces an invalid JSON file. Coercing to a plain int here
    is what keeps the output parseable.
    """
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return 0, []
    names = []
    for const in FILE_OP_NAMES:
        bit = getattr(gwy, const, None)
        if bit is None:
            continue
        try:
            bit = int(bit)
        except (TypeError, ValueError):
            continue
        if bit and (raw & bit):
            names.append(const)
    return raw, names


def collect_file_funcs(candidates):
    """Same treatment for file import/export functions."""
    funcs = []
    for name in sorted(candidates):
        try:
            if not gwy.gwy_file_func_exists(name):
                continue
        except Exception:
            continue
        ops_raw, ops_names = decode_file_operations(
            safe_call(gwy.gwy_file_func_get_operations, name, 0)
        )
        entry = {
            "name": name,
            "description": safe_call(gwy.gwy_file_func_get_description, name, ""),
            "operations": ops_raw,
            "operation_names": ops_names,
        }
        funcs.append(entry)
    return funcs


# --------------------------------------------------------------------------
# Module surface: classes, functions, constants
# --------------------------------------------------------------------------

def describe_module():
    """Split the gwy module namespace into classes, callables and constants."""
    classes = {}
    functions = []
    constants = []

    for name in sorted(dir(gwy)):
        if name.startswith("_"):
            continue
        try:
            obj = getattr(gwy, name)
        except Exception:
            continue

        if isinstance(obj, type):
            methods = []
            for meth in sorted(dir(obj)):
                if meth.startswith("_"):
                    continue
                try:
                    mobj = getattr(obj, meth)
                except Exception:
                    continue
                if not callable(mobj):
                    continue
                methods.append({
                    "name": meth,
                    "doc": (getattr(mobj, "__doc__", "") or "").strip()[:400],
                })
            classes[name] = {
                "doc": (getattr(obj, "__doc__", "") or "").strip()[:400],
                "n_methods": len(methods),
                "methods": methods,
            }
        elif callable(obj):
            functions.append({
                "name": name,
                "doc": (getattr(obj, "__doc__", "") or "").strip()[:400],
            })
        else:
            constants.append({"name": name, "value": repr(obj)[:120]})

    return classes, functions, constants


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------

def write_markdown(path, process_funcs, file_funcs, classes, functions, constants):
    fh = open(path, "w")
    try:
        fh.write("# PyGwy API inventory\n\n")
        fh.write("Generated by `tools/introspect_pygwy.py` against the Gwyddion install at\n")
        fh.write("`%s`.\n\n" % GWY_ROOT)
        fh.write("Every process/file function below was confirmed through the live API ")
        fh.write("(`gwy_process_func_exists` / `gwy_file_func_exists`); none are guessed.\n\n")

        fh.write("| Category | Count |\n|---|---|\n")
        fh.write("| Process functions | %d |\n" % len(process_funcs))
        fh.write("| File functions | %d |\n" % len(file_funcs))
        fh.write("| Classes | %d |\n" % len(classes))
        fh.write("| Module functions | %d |\n" % len(functions))
        fh.write("| Constants | %d |\n\n" % len(constants))

        # Process functions grouped by their top-level menu section.
        fh.write("## Process functions by menu section\n\n")
        groups = {}
        for f in process_funcs:
            mp = f["menu_path"] or "/(no menu)"
            top = mp.lstrip("/").split("/")[0] if mp else "(no menu)"
            groups.setdefault(top, []).append(f)

        for top in sorted(groups):
            fh.write("### %s  (%d)\n\n" % (top, len(groups[top])))
            fh.write("| name | menu path | run types | tooltip |\n")
            fh.write("|---|---|---|---|\n")
            for f in sorted(groups[top], key=lambda x: x["name"]):
                tip = (f["tooltip"] or "").replace("|", "\\|").replace("\n", " ")
                mp = (f["menu_path"] or "").replace("|", "\\|")
                fh.write("| `%s` | %s | %s | %s |\n" % (
                    f["name"], mp, ", ".join(f["run_types"]), tip))
            fh.write("\n")

        fh.write("## File functions\n\n")
        fh.write("| name | operations | description |\n|---|---|---|\n")
        for f in file_funcs:
            desc = (f["description"] or "").replace("|", "\\|").replace("\n", " ")
            ops = ", ".join(
                n.replace("FILE_OPERATION_", "")
                for n in f.get("operation_names", [])
            )
            fh.write("| `%s` | %s | %s |\n" % (f["name"], ops, desc))
        fh.write("\n")

        fh.write("## Classes\n\n")
        fh.write("| class | methods |\n|---|---|\n")
        for cname in sorted(classes, key=lambda c: -classes[c]["n_methods"]):
            fh.write("| `%s` | %d |\n" % (cname, classes[cname]["n_methods"]))
        fh.write("\n")
        fh.write("Full method lists are in `pygwy_api.json`.\n")
    finally:
        fh.close()


def main():
    ensure_dir(OUT_DIR)

    print("Gwyddion root : %s" % GWY_ROOT)
    print("Python        : %s" % sys.version.split()[0])
    print("Harvesting candidate names from module DLLs...")
    candidates, scanned = harvest_all_candidates()
    for s in scanned:
        print("   scanned %s" % s)
    print("   %d candidate identifiers" % len(candidates))

    print("Verifying process functions against the live API...")
    process_funcs = collect_process_funcs(candidates)
    print("   %d confirmed process functions" % len(process_funcs))

    print("Verifying file functions...")
    file_funcs = collect_file_funcs(candidates)
    print("   %d confirmed file functions" % len(file_funcs))

    print("Describing module namespace...")
    classes, functions, constants = describe_module()
    print("   %d classes, %d functions, %d constants"
          % (len(classes), len(functions), len(constants)))

    payload = {
        "gwyddion_root": GWY_ROOT,
        "python_version": sys.version,
        "process_functions": process_funcs,
        "file_functions": file_funcs,
        "classes": classes,
        "module_functions": functions,
        "constants": constants,
    }

    json_path = os.path.join(OUT_DIR, "pygwy_api.json")
    fh = open(json_path, "w")
    try:
        # default=repr catches any stray GObject value we did not explicitly
        # coerce; without it such a value serialises as a bare, unquoted repr
        # and quietly corrupts the file.
        json.dump(payload, fh, indent=2, sort_keys=True, default=repr)
    finally:
        fh.close()

    # Read the file back before claiming success -- a corrupt inventory that
    # nobody notices until much later is worse than a loud failure here.
    fh = open(json_path, "r")
    try:
        json.load(fh)
    except ValueError:
        print("ERROR: %s was written but is not valid JSON." % json_path)
        raise
    finally:
        fh.close()
    print("Wrote %s (validated)" % json_path)

    md_path = os.path.join(OUT_DIR, "PYGWY_API.md")
    write_markdown(md_path, process_funcs, file_funcs, classes, functions, constants)
    print("Wrote %s" % md_path)


if __name__ == "__main__":
    main()
