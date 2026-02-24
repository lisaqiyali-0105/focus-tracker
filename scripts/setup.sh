#!/bin/bash

# macOS Activity Tracker Setup Script

set -e

echo "=================================="
echo "macOS Activity Tracker Setup"
echo "=================================="
echo ""

# Get script directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Check Python version
echo "Checking Python version..."
python3 --version || {
    echo "Error: Python 3 is required but not found"
    echo "Install Python 3 from https://www.python.org/downloads/"
    exit 1
}

# Create virtual environment
echo "Creating virtual environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✓ Virtual environment created"
else
    echo "✓ Virtual environment already exists"
fi

# Activate virtual environment
echo "Activating virtual environment..."
source venv/bin/activate

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip

# Install dependencies
echo "Installing dependencies..."
pip install -r requirements.txt
echo "✓ Dependencies installed"

# Create .env file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file..."
    cp .env.example .env
    echo "✓ .env file created"
    echo ""
    echo "⚠️  IMPORTANT: Edit .env and add your ANTHROPIC_API_KEY"
    echo "   Get your API key from: https://console.anthropic.com/"
else
    echo "✓ .env file already exists"
fi

# Create data directories
echo "Creating data directories..."
mkdir -p data/logs
echo "✓ Data directories created"

# Initialize database
echo "Initializing database..."
python3 << EOF
from database.models import init_db
init_db()
print("✓ Database initialized with default categories")
EOF

echo ""
echo "=================================="
echo "Setup Complete!"
echo "=================================="
echo ""
echo "Next steps:"
echo "1. Edit .env and add your ANTHROPIC_API_KEY"
echo "2. Grant Accessibility permissions:"
echo "   System Settings > Privacy & Security > Accessibility"
echo "   Add: Terminal or Python"
echo ""
echo "To start tracking:"
echo "  source venv/bin/activate"
echo "  python3 services/background_runner.py"
echo ""
echo "To start dashboard (in another terminal):"
echo "  source venv/bin/activate"
echo "  python3 dashboard/app.py"
echo "  Then open: http://127.0.0.1:5000"
echo ""
