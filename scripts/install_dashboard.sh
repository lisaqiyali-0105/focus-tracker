#!/bin/bash

# Install launchd service for the dashboard web server
# This lets the dashboard start automatically at login

set -e

echo "=================================="
echo "Installing Dashboard LaunchAgent"
echo "=================================="
echo ""

# Get project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# LaunchAgent directory
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"

# Service name
SERVICE_NAME="com.adhd-dashboard"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$SERVICE_NAME.plist"

# Python executable in venv
PYTHON_PATH="$PROJECT_DIR/venv/bin/python3"
SCRIPT_PATH="$PROJECT_DIR/dashboard/app.py"

# Check if venv exists
if [ ! -f "$PYTHON_PATH" ]; then
    echo "Error: Virtual environment not found"
    echo "Run ./scripts/setup.sh first"
    exit 1
fi

# Create data/logs directory if needed
mkdir -p "$PROJECT_DIR/data/logs"

# Create plist file dynamically (no hardcoded username)
echo "Creating LaunchAgent plist..."
cat > "$PLIST_PATH" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$SERVICE_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_PATH</string>
        <string>$SCRIPT_PATH</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
        <key>Crashed</key>
        <true/>
    </dict>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/data/logs/dashboard.log</string>

    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/data/logs/dashboard-error.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
        <key>DATABASE_PATH</key>
        <string>data/activities.db</string>
        <key>FLASK_HOST</key>
        <string>127.0.0.1</string>
        <key>FLASK_PORT</key>
        <string>5000</string>
        <key>FLASK_DEBUG</key>
        <string>False</string>
        <key>LOG_LEVEL</key>
        <string>INFO</string>
    </dict>

    <key>ProcessType</key>
    <string>Interactive</string>
</dict>
</plist>
EOF

echo "✓ LaunchAgent plist created at: $PLIST_PATH"

# Note: ANTHROPIC_API_KEY should be in your .env file, not the plist
if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo ""
    echo "⚠️  No .env file found. Copy .env.example and add your API key:"
    echo "   cp .env.example .env"
fi

# Load the service
echo "Loading LaunchAgent..."
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✓ Dashboard service loaded"

echo ""
echo "=================================="
echo "Dashboard Service Installed!"
echo "=================================="
echo ""
echo "The dashboard will start automatically at login."
echo "Open: http://127.0.0.1:5000"
echo ""
echo "Management commands:"
echo "  Start:   launchctl start $SERVICE_NAME"
echo "  Stop:    launchctl stop $SERVICE_NAME"
echo "  Unload:  launchctl unload $PLIST_PATH"
echo ""
echo "Logs: $PROJECT_DIR/data/logs/dashboard.log"
echo ""
