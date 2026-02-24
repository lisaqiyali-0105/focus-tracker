#!/bin/bash

# Uninstall launchd service

set -e

echo "=================================="
echo "Uninstalling Activity Tracker"
echo "=================================="
echo ""

SERVICE_NAME="com.activitytracker.monitor"
PLIST_PATH="$HOME/Library/LaunchAgents/$SERVICE_NAME.plist"

# Stop and unload service
if [ -f "$PLIST_PATH" ]; then
    echo "Stopping and unloading service..."
    launchctl stop "$SERVICE_NAME" 2>/dev/null || true
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm "$PLIST_PATH"
    echo "✓ Service unloaded and removed"
else
    echo "Service not installed"
fi

echo ""
echo "=================================="
echo "Uninstall Complete!"
echo "=================================="
echo ""
echo "Note: Your data directory has been preserved."
echo "To completely remove all data, run:"
echo "  rm -rf data/"
echo ""
