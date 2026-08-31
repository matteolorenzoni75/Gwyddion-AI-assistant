"""Allow `python -m afm_copilot`."""

import sys

from afm_copilot.cli import main

if __name__ == "__main__":
    sys.exit(main())
