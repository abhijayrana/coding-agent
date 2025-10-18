#!/usr/bin/env python3
"""Entry point for coding-agent CLI."""

import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from agent.ui.cli import app

if __name__ == "__main__":
    app()
