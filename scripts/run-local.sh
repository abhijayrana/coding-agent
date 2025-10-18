#!/bin/bash
# Quick run script

set -e

# Activate virtual environment
if [ -d "venv" ]; then
    source venv/bin/activate
else
    echo "❌ Virtual environment not found. Run scripts/install-dev.sh first"
    exit 1
fi

# Check for .env
if [ ! -f ".env" ]; then
    echo "⚠️  .env not found. Copying from .env.example..."
    cp .env.example .env
    echo "Please edit .env and add your API keys"
    exit 1
fi

# Run the agent
coding-agent "$@"
