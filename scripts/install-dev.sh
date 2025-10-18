#!/bin/bash
# Development installation script

set -e

echo "🔧 Setting up coding-agent development environment..."

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python version: $python_version"

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install in editable mode
echo "Installing coding-agent..."
pip install -e ".[dev]"

# Check for ripgrep
if ! command -v rg &> /dev/null; then
    echo "⚠️  Warning: ripgrep not found. Install with: brew install ripgrep"
fi

echo "✅ Installation complete!"
echo ""
echo "Next steps:"
echo "1. Copy .env.example to .env and add your API keys"
echo "2. Run: source venv/bin/activate"
echo "3. Run: coding-agent init"
echo "4. Run: coding-agent chat"
