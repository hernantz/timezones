"""Installed entry point (bin/timezones imports main from here).

Everything lives in src.app — this module used to carry a second copy of the
App class, which is how the keyboard accelerators ended up bound in one copy
and not in the one that actually ships.
"""

from __future__ import annotations

from src.app import main  # noqa: F401

if __name__ == "__main__":
    raise SystemExit(main())
