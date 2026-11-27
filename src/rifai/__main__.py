"""Allow executing the Rifa'i CLI via `python -m rifai`."""

from __future__ import annotations

from rifai.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
