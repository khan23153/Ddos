#!/usr/bin/env python3
"""Compatibility entry point for the authorized staging-only QA harness.

The historical filename is retained for convenience. The implementation does
not hide automation, bypass verification, defeat anti-bot controls, or target
third-party production stores.
"""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.exists():
    sys.path.insert(0, str(SRC))

from flash_sale_qa.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
