"""
Register (or refresh) the AFM Copilot MCP server in Claude Desktop.

Merges into claude_desktop_config.json rather than replacing it -- that file
holds every other Claude Desktop preference, and overwriting it would silently
reset them. The previous version is copied to a timestamped backup first.

    .venv\\Scripts\\python.exe tools\\register_mcp.py            # show the plan
    .venv\\Scripts\\python.exe tools\\register_mcp.py --apply    # write it

Restart Claude Desktop afterwards; MCP servers are read at launch.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SERVER_KEY = "afm-copilot"


def config_path() -> Path:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("APPDATA is not set -- is this Windows?")
    return Path(appdata) / "Claude" / "claude_desktop_config.json"


def entry() -> dict:
    python = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
    if not python.is_file():
        raise SystemExit(
            f"No virtualenv at {python}.\n"
            f"Create it first:  python -m venv .venv  &&  "
            f".venv\\Scripts\\python.exe -m pip install -e .")
    return {
        "command": str(python),
        "args": ["-m", "afm_copilot.mcp_server"],
        "cwd": str(PROJECT_ROOT),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the change (default: show it only)")
    args = parser.parse_args()

    path = config_path()
    new_entry = entry()

    if path.is_file():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(
                f"{path} is not valid JSON ({exc}). Fix or remove it before "
                f"running this, so nothing already there is lost.")
    else:
        config = {}
        print(f"No config yet; one will be created at {path}")

    servers = config.setdefault("mcpServers", {})
    existing = servers.get(SERVER_KEY)

    if existing == new_entry:
        print(f"Already registered and up to date in {path}")
        return 0

    print(f"Config file : {path}")
    print(f"Other keys kept: {', '.join(k for k in config if k != 'mcpServers') or '(none)'}")
    print(f"Other MCP servers kept: "
          f"{', '.join(k for k in servers if k != SERVER_KEY) or '(none)'}")
    print(f"\n{'Updating' if existing else 'Adding'} '{SERVER_KEY}':")
    print(json.dumps(new_entry, indent=2))

    if not args.apply:
        print("\nNothing written. Re-run with --apply to make the change.")
        return 0

    if path.is_file():
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.stem}.{stamp}.bak{path.suffix}")
        shutil.copy2(path, backup)
        print(f"\nBacked up to {backup}")

    servers[SERVER_KEY] = new_entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2), encoding="utf-8")

    # Read it back: a config that does not parse leaves Claude Desktop with no
    # MCP servers at all, and the failure is silent at launch.
    json.loads(path.read_text(encoding="utf-8"))
    print("Written and verified.")
    print("\nRestart Claude Desktop -- MCP servers are only read at launch.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
