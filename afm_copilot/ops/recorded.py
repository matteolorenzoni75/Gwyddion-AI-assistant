"""
Turn a scan's own processing history into a recipe you can re-run.

Gwyddion writes a log into every file it touches, recording each operation and
every parameter it used:

    proc::level(mode=0)@2026-08-31 13:35:01Z
    proc::align_rows(method=4, trim_fraction=0.0985, ...)@...

That log is written whether the work was done here or by hand in Gwyddion's own
window. So a user can process one scan interactively until it looks right, and
this module reads back exactly what they did and applies it to a hundred more.

The result is an ordinary Recipe. That is deliberate: everything downstream --
the explanations, the runner, the panel, the Claude tools -- already knows how
to handle a Recipe, so recorded processing needs no new machinery anywhere
else.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from afm_copilot.ops.catalog import OPERATIONS, Operation
from afm_copilot.ops.recipes import Recipe

# proc::name(k=v, k=v)@timestamp   -- the parameter list may be empty.
_ENTRY = re.compile(r"^(?P<kind>\w+)::(?P<name>[\w-]+)\((?P<args>.*)\)@(?P<when>.*)$")

# Splits "a=1, b=\"x, y\", c=True" without breaking on commas inside quotes.
_ARG = re.compile(r'(\w+)=("(?:[^"\\]|\\.)*"|[^,]*)')

# Where the Gwyddion function inventory lives, used to describe operations the
# hand-written catalogue does not cover.
_API_JSON = Path(__file__).resolve().parents[2] / "docs" / "pygwy_api" / "pygwy_api.json"
_INVENTORY: dict[str, dict] | None = None


def _inventory() -> dict[str, dict]:
    """Gwyddion's own description of each function, loaded once."""
    global _INVENTORY
    if _INVENTORY is None:
        try:
            data = json.loads(_API_JSON.read_text(encoding="utf-8"))
            _INVENTORY = {f["name"]: f for f in data["process_functions"]}
        except (OSError, ValueError, KeyError):
            _INVENTORY = {}
    return _INVENTORY


def _coerce(text: str):
    """Turn a logged value back into the type Gwyddion will want."""
    text = text.strip()
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    if text in ("True", "False"):
        return text == "True"
    for cast in (int, float):
        try:
            return cast(text)
        except ValueError:
            pass
    return text


def parse_log(entries: list[str]) -> list[dict]:
    """
    Read a Gwyddion log into a list of operations.

    Only `proc::` entries are kept. A `file::` entry records which importer
    read the scan, which is worth knowing but is not something to replay.
    """
    steps: list[dict] = []
    for raw in entries:
        match = _ENTRY.match(raw.strip())
        if not match or match.group("kind") != "proc":
            continue
        args = {k: _coerce(v) for k, v in _ARG.findall(match.group("args"))}
        steps.append({"gwy_func": match.group("name"),
                      "settings": args,
                      "when": match.group("when")})
    return steps


def describe_source(entries: list[str]) -> str:
    """The `file::` entry, in words -- which importer read this scan."""
    for raw in entries:
        match = _ENTRY.match(raw.strip())
        if match and match.group("kind") == "file":
            return match.group("name")
    return ""


def _settings_prefix(op: Operation | None, func: str) -> str:
    """
    Where Gwyddion keeps this function's parameters.

    Not always under the function's own name: the log records `align_rows` but
    the module stores its settings under `/module/linematch/`. Writing to the
    wrong prefix fails silently -- Gwyddion simply uses whatever was left there
    from a previous run, which is how a recorded `method=4` came back as
    `method=2`.

    The catalogue already holds the true prefix for every operation it covers,
    so take it from there and fall back to the function name otherwise.
    """
    if op is not None and op.settings:
        first = next(iter(op.settings))
        return first.rsplit("/", 1)[0]
    return f"/module/{func}"


def _operation_for(step: dict, index: int) -> Operation:
    """
    Describe one logged step.

    Where the hand-written catalogue already covers the function, its
    explanation is reused verbatim -- the same words the user reads everywhere
    else. Otherwise the description comes from Gwyddion's own tooltip, which is
    thinner but honest about where it came from.
    """
    func = step["gwy_func"]
    known = next((op for op in OPERATIONS.values() if op.gwy_func == func), None)
    prefix = _settings_prefix(known, func)
    settings = {f"{prefix}/{k}": v for k, v in step["settings"].items()}

    if known is not None:
        # Same operation, but carrying the parameters that were actually
        # recorded rather than the catalogue's defaults.
        return Operation(
            key=f"{known.key}@{index}",
            gwy_func=func,
            title=known.title,
            what=known.what,
            why=known.why,
            caution=known.caution,
            menu=known.menu,
            settings=settings,
            needs_mask=known.needs_mask,
            creates_mask=known.creates_mask,
        )

    info = _inventory().get(func, {})
    tooltip = info.get("tooltip") or "No description available."
    return Operation(
        key=f"{func}@{index}",
        gwy_func=func,
        title=info.get("menu_path", func).split("/")[-1].replace("_", "") or func,
        what=tooltip,
        why="Recorded from the reference scan's own processing history.",
        caution="Not one of the described operations -- it was taken from the "
                "reference scan, so its effect on your other scans has not "
                "been checked here.",
        menu=info.get("menu_path", ""),
        settings=settings,
    )


def recipe_from_log(
    entries: list[str],
    key: str = "recorded",
    title: str = "Recorded processing",
    source_name: str = "",
) -> Recipe:
    """
    Build a runnable recipe from a scan's processing history.

    Raises ValueError when the log holds no processing steps -- a scan that was
    only opened and saved has nothing to copy, and saying so is better than
    handing back an empty recipe that appears to work.
    """
    steps = parse_log(entries)
    if not steps:
        raise ValueError(
            "this scan has no processing history to copy: its log records only "
            "how the file was read, not any operation applied to it")

    operations = [_operation_for(step, i) for i, step in enumerate(steps)]
    # Registering them makes the recipe's `operations` lookup work like any
    # other, so nothing downstream needs to special-case a recorded recipe.
    for op in operations:
        OPERATIONS[op.key] = op

    where = f" from {source_name}" if source_name else ""
    return Recipe(
        key=key,
        title=title,
        purpose=f"Repeat exactly the processing recorded{where}: "
                + " then ".join(op.title.lower() for op in operations) + ".",
        when_to_use="Scans of the same kind, taken under the same conditions, "
                    "that should be treated identically to the reference.",
        when_not_to_use="Scans that differ from the reference -- a different "
                        "sample, scan size or tip. The recorded parameters were "
                        "chosen for one scan and are applied here unchanged, "
                        "with no check that they still suit.",
        steps=tuple(op.key for op in operations),
    )


def compare_logs(reference: list[str], produced: list[str]) -> list[str]:
    """
    Check a copy actually took, by reading back what Gwyddion recorded.

    Gwyddion writes its own log again when the copied steps run, so the two
    can be compared parameter by parameter. This is the safety net for
    operations the catalogue does not cover: if a parameter went to the wrong
    place it fails silently, and the only way to notice is that the value that
    came back is not the one that went in.

    Returns a list of human-readable differences; empty means a faithful copy.
    """
    want = parse_log(reference)
    got = parse_log(produced)
    problems: list[str] = []

    if len(got) < len(want):
        problems.append(
            f"only {len(got)} of {len(want)} steps were recorded on the result")

    for i, expected in enumerate(want):
        if i >= len(got):
            break
        actual = got[i]
        if actual["gwy_func"] != expected["gwy_func"]:
            problems.append(
                f"step {i + 1}: expected {expected['gwy_func']}, "
                f"got {actual['gwy_func']}")
            continue
        for key, value in expected["settings"].items():
            if key not in actual["settings"]:
                continue
            if actual["settings"][key] != value:
                problems.append(
                    f"{expected['gwy_func']}: '{key}' was {value!r} on the "
                    f"reference but {actual['settings'][key]!r} on the copy")
    return problems


def read_log(path: str | Path, channel: int = 0) -> list[str]:
    """
    Read a scan's processing log, in Python 3, without going through Gwyddion.

    Returns an empty list when the file has no log -- most raw files do not.
    """
    import gwyfile

    obj = gwyfile.load(str(path))
    try:
        log = obj[f"/{channel}/data/log"]
    except (KeyError, TypeError):
        return []
    try:
        return [str(s) for s in log["strings"]]
    except (KeyError, TypeError):
        return []
