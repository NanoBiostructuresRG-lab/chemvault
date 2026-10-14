# SPDX-License-Identifier: LGPL-3.0-or-later
"""Command-line launcher for the installed Streamlit application."""

from __future__ import annotations

import argparse
import importlib.metadata
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="chemvault",
        description="Launch the installed CHEMVAULT Streamlit application.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"ChemVault {importlib.metadata.version('ChemVault')}",
    )
    return parser


def _resolve_app_path() -> Path:
    return Path(__file__).resolve().parent.parent / "app.py"


def _streamlit_command(app_path: Path) -> list[str]:
    return [sys.executable, "-m", "streamlit", "run", str(app_path)]


def main(argv: Sequence[str] | None = None) -> int:
    """Parse CLI arguments and launch the installed Streamlit application."""

    parser = _build_parser()
    parser.parse_args(argv)

    app_path = _resolve_app_path()
    if not app_path.is_file():
        print(f"chemvault: application file not found: {app_path}", file=sys.stderr)
        return 1

    try:
        completed = subprocess.run(_streamlit_command(app_path), check=False)
    except KeyboardInterrupt:
        return 130
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["main"]
