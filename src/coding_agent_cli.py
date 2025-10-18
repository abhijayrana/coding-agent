#!/usr/bin/env python3
"""Entry point for coding-agent CLI."""

import sys
from pathlib import Path

# Ensure src is in path
src_path = Path(__file__).parent
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from ui.cli import app as typer_app

def app():
    """Entry point wrapper."""
    typer_app()

if __name__ == "__main__":
    app()
