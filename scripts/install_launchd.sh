#!/bin/bash

# Install launchd service for automatic startup

set -e

echo "=================================="
echo "Installing LaunchAgent Service"
echo "=================================="
echo ""

# Get project directory
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# LaunchAgent directory
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_AGENTS_DIR"

# Service name
SERVICE_NAME="com.activitytracker.monitor"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$SERVICE_NAME.plist"

# Python executable in venv
PYTHON_PATH="$PROJECT_DIR/venv/bin/python3"
SCRIPT_PATH="$PROJECT_DIR/services/background_runner.py"

# Check if venv exists
if [ ! -f "$PYTHON_PATH" ]; then
    echo "Error: Virtual environment not found"
    echo "Run scripts/setup.sh first"
    exit 1
fi

# Create plist file
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
    <true/>

    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.out.log</string>

    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/data/logs/launchd.err.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
EOF

echo "✓ LaunchAgent plist created at: $PLIST_PATH"

# Load the service
echo "Loading LaunchAgent..."
launchctl unload "$PLIST_PATH" 2>/dev/null || true
launchctl load "$PLIST_PATH"

echo "✓ LaunchAgent loaded"

echo ""
echo "=================================="
echo "Installation Complete!"
echo "=================================="
echo ""
echo "The activity tracker will now start automatically at login."
echo ""
echo "Management commands:"
echo "  Start:   launchctl start $SERVICE_NAME"
echo "  Stop:    launchctl stop $SERVICE_NAME"
echo "  Restart: launchctl stop $SERVICE_NAME && launchctl start $SERVICE_NAME"
echo "  Unload:  launchctl unload $PLIST_PATH"
echo ""
echo "Logs are at: $PROJECT_DIR/data/logs/"
echo ""
