"""
Window monitor using macOS Accessibility API.
Polls active window every 3 seconds and stores in database.
"""
import time
import hashlib
from datetime import datetime
from typing import Optional, Dict, Any, List
import re

try:
    import atomacos
    ATOMACOS_AVAILABLE = True
except ImportError:
    ATOMACOS_AVAILABLE = False
    print("Warning: atomacos not available. Install with: pip install atomacos")

from database.models import Activity, SensitiveApp, get_session
from config.logging import setup_logging
from config.settings import POLLING_INTERVAL_SECONDS

logger = setup_logging('window_monitor')


class WindowMonitor:
    """Monitors active window and records activities."""

    def __init__(self):
        self.session = get_session()
        self.last_activity = None
        self.sensitive_patterns = self._load_sensitive_patterns()
        self.consecutive_failures = 0
        self.max_failures_before_restart = 10

    def _load_sensitive_patterns(self) -> Dict[str, str]:
        """Load sensitive app configurations from database."""
        patterns = {}
        sensitive_apps = self.session.query(SensitiveApp).all()
        for app in sensitive_apps:
            patterns[app.bundle_id] = app.sensitivity_level
        return patterns

    def _is_sensitive_bundle(self, bundle_id: str) -> Optional[str]:
        """Check if bundle ID matches sensitive pattern."""
        # Check exact match first
        if bundle_id in self.sensitive_patterns:
            return self.sensitive_patterns[bundle_id]

        # Check common patterns
        sensitive_patterns = [
            r'com\.(1password|lastpass|dashlane|bitwarden)',
            r'com\.(chase|bankofamerica|wellsfargo|usbank|citi)',
            r'com\.apple\.KeychainAccess',
        ]

        for pattern in sensitive_patterns:
            if re.search(pattern, bundle_id, re.IGNORECASE):
                return 'anonymize'

        return None

    def _is_sensitive_title(self, title: str) -> bool:
        """Check if window title contains sensitive keywords."""
        if not title:
            return False

        sensitive_keywords = [
            'password', 'login', 'sign in', 'authentication',
            'bank', 'credit card', 'social security',
            'private', 'confidential', 'incognito',
            'private browsing'
        ]

        title_lower = title.lower()
        return any(keyword in title_lower for keyword in sensitive_keywords)

    def _hash_title(self, title: str) -> str:
        """Create SHA256 hash of window title."""
        return hashlib.sha256(title.encode('utf-8')).hexdigest()

    def _run_osascript_with_retry(self, max_attempts=3) -> Optional[str]:
        """Run osascript with retry logic to handle transient failures."""
        import subprocess

        for attempt in range(max_attempts):
            try:
                result = subprocess.run(
                    ['osascript', '-e', 'tell application "System Events" to get name of first application process whose frontmost is true'],
                    capture_output=True,
                    text=True,
                    timeout=5  # Increased from 2s to 5s
                )

                if result.returncode == 0:
                    self.consecutive_failures = 0  # Reset on success
                    return result.stdout.strip()

            except subprocess.TimeoutExpired:
                if attempt < max_attempts - 1:
                    time.sleep(1)  # Wait 1 second before retry
                    continue

            except Exception as e:
                if attempt < max_attempts - 1:
                    time.sleep(1)
                    continue

        # All attempts failed
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.max_failures_before_restart:
            logger.warning(f"osascript failed {self.consecutive_failures} times consecutively. Consider restarting monitor.")

        return None

    def _get_visible_apps(self) -> List[str]:
        """Get apps with visible, non-minimized windows (actual split screen candidates)."""
        import subprocess
        try:
            # Check for non-minimized windows only - these are the ones actually visible on screen
            script = '''
            tell application "System Events"
                set visibleApps to {}
                set currentSpace to {}

                repeat with proc in (every process whose visible is true and background only is false)
                    try
                        -- Check if process has any non-minimized windows
                        set hasVisibleWindow to false
                        repeat with win in (windows of proc)
                            try
                                -- Window is visible if it exists and isn't minimized
                                if (value of attribute "AXMinimized" of win) is false then
                                    set hasVisibleWindow to true
                                    exit repeat
                                end if
                            end try
                        end repeat

                        if hasVisibleWindow then
                            set end of visibleApps to name of proc
                        end if
                    end try
                end repeat
                return visibleApps
            end tell
            '''
            result = subprocess.run(
                ['osascript', '-e', script],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                # Returns comma-separated list: "Finder, Safari, Terminal"
                apps = [app.strip() for app in result.stdout.strip().split(',')]
                # Filter out system processes and menu bar apps
                system_apps = {
                    'Finder', 'Dock', 'Window Server', 'SystemUIServer',
                    'ControlCenter', 'Notification Center', 'Spotlight'
                }
                filtered = [app for app in apps if app and app not in system_apps]
                logger.debug(f"Visible apps with non-minimized windows: {filtered}")
                return filtered
            return []
        except Exception as e:
            logger.debug(f"Failed to get visible apps: {e}")
            return []

    def _get_active_window_info(self) -> Optional[Dict[str, Any]]:
        """Get information about currently active window."""
        if not ATOMACOS_AVAILABLE:
            # Fallback for testing without atomacos
            return None

        try:
            # Get frontmost app name using AppleScript with retry logic
            app_name = self._run_osascript_with_retry()

            if not app_name:
                return None

            # Get all visible apps for split screen detection
            visible_apps = self._get_visible_apps()

            # Get the app reference
            try:
                app = atomacos.getAppRefByLocalizedName(app_name)
            except:
                # Try alternative method
                return {
                    'bundle_id': f'unknown.{app_name.lower().replace(" ", "")}',
                    'app_name': app_name,
                    'window_title': None,
                    'visible_apps': visible_apps
                }

            # Get bundle ID
            try:
                bundle_id = app.bundleId
            except:
                bundle_id = f'unknown.{app_name.lower().replace(" ", "")}'

            # Get focused window
            window_title = None
            try:
                windows = app.windows()
                if windows and len(windows) > 0:
                    window_title = windows[0].AXTitle
            except:
                pass

            return {
                'bundle_id': bundle_id,
                'app_name': app_name,
                'window_title': window_title,
                'visible_apps': visible_apps
            }

        except Exception as e:
            logger.error(f"Error getting active window: {e}")
            return None

    def _should_skip_activity(self, info: Dict[str, Any]) -> bool:
        """Check if activity should be skipped entirely."""
        sensitivity = self._is_sensitive_bundle(info['bundle_id'])
        return sensitivity == 'exclude'

    def record_activity(self) -> bool:
        """Record current active window as activity."""
        import json

        info = self._get_active_window_info()

        if not info:
            return False

        # Check if should exclude
        if self._should_skip_activity(info):
            logger.debug(f"Excluding sensitive app: {info['app_name']}")
            return False

        # Check sensitivity
        sensitivity = self._is_sensitive_bundle(info['bundle_id'])
        is_sensitive = sensitivity is not None or self._is_sensitive_title(info.get('window_title', ''))

        # Prepare activity data
        window_title = info.get('window_title')
        window_title_hash = None

        if is_sensitive and window_title:
            window_title_hash = self._hash_title(window_title)
            window_title = None  # Don't store plaintext

        # Serialize visible apps to JSON
        visible_apps = info.get('visible_apps', [])
        visible_apps_json = json.dumps(visible_apps) if visible_apps else None

        # Create activity record
        activity = Activity(
            timestamp=datetime.now(),  # Use local time instead of UTC
            app_bundle_id=info['bundle_id'],
            app_name=info['app_name'],
            window_title=window_title,
            window_title_hash=window_title_hash,
            is_sensitive=is_sensitive,
            visible_apps=visible_apps_json
        )

        self.session.add(activity)
        self.session.commit()

        # Log split screen detection
        if visible_apps and len(visible_apps) > 1:
            logger.debug(f"Recorded activity: {info['app_name']} - {window_title or '[sensitive]'} (Split screen: {', '.join(visible_apps)})")
        else:
            logger.debug(f"Recorded activity: {info['app_name']} - {window_title or '[sensitive]'}")

        self.last_activity = activity
        return True

    def run(self):
        """Main monitoring loop."""
        logger.info(f"Starting window monitor (polling every {POLLING_INTERVAL_SECONDS}s)")

        # Check accessibility permissions
        if ATOMACOS_AVAILABLE:
            try:
                import subprocess
                result = subprocess.run(
                    ['osascript', '-e', 'tell application "System Events" to get name of first application process whose frontmost is true'],
                    capture_output=True,
                    text=True,
                    timeout=2
                )
                if result.returncode == 0:
                    logger.info("Accessibility permissions OK")
                else:
                    logger.error("Accessibility permissions not granted!")
                    logger.error("Enable in: System Settings > Privacy & Security > Accessibility")
                    return
            except Exception as e:
                logger.error(f"Accessibility check failed: {e}")
                logger.error("Enable in: System Settings > Privacy & Security > Accessibility")
                return

        while True:
            try:
                self.record_activity()
                time.sleep(POLLING_INTERVAL_SECONDS)
            except KeyboardInterrupt:
                logger.info("Monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}")
                time.sleep(POLLING_INTERVAL_SECONDS)

        self.session.close()


def main():
    """Entry point for window monitor."""
    monitor = WindowMonitor()
    monitor.run()


if __name__ == '__main__':
    main()
