"""
Background service orchestrator.
Runs window monitor, activity processor, and AI categorizer.
"""
import signal
import sys
import os
import time
import multiprocessing
from datetime import datetime
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from tracker.window_monitor import WindowMonitor
from tracker.activity_processor import ActivityProcessor
from tracker.slack_tracker import SlackTracker
from ai.categorizer import SessionCategorizer
from config.logging import setup_logging
from config.settings import AI_CATEGORIZATION_INTERVAL_MINUTES

logger = setup_logging('background_runner')


# Standalone functions for multiprocessing (avoids pickling issues)
def run_window_monitor():
    """Run window monitor in subprocess."""
    setup_logging('window_monitor')  # Re-setup logging in subprocess
    logger = setup_logging('background_runner')
    logger.info("Starting window monitor subprocess")
    monitor = WindowMonitor()
    monitor.run()


def run_activity_processor(stop_event):
    """Run activity processor periodically."""
    setup_logging('activity_processor')  # Re-setup logging in subprocess
    logger = setup_logging('background_runner')
    logger.info("Starting activity processor subprocess")

    while not stop_event.is_set():
        try:
            processor = ActivityProcessor()
            result = processor.process()
            processor.close()
            logger.info(f"Activity processor completed: {result} sessions")
        except Exception as e:
            logger.error(f"Activity processor error: {e}")

        # Run every 5 minutes
        for _ in range(300):  # Sleep in 1-second increments to check stop_event
            if stop_event.is_set():
                break
            time.sleep(1)


def run_slack_tracker(stop_event):
    """Run Slack tracker periodically."""
    setup_logging('slack_tracker')  # Re-setup logging in subprocess
    logger = setup_logging('background_runner')
    logger.info("Starting Slack tracker subprocess")

    while not stop_event.is_set():
        try:
            tracker = SlackTracker()
            count = tracker.process_slack_activities()
            tracker.close()
            logger.info(f"Slack tracker completed: {count} views processed")
        except Exception as e:
            logger.error(f"Slack tracker error: {e}")

        # Run every 5 minutes (same as activity processor)
        for _ in range(300):  # Sleep in 1-second increments to check stop_event
            if stop_event.is_set():
                break
            time.sleep(1)


def run_ai_categorizer(stop_event):
    """Run AI categorizer periodically."""
    setup_logging('ai_categorizer')  # Re-setup logging in subprocess
    logger = setup_logging('background_runner')
    logger.info("Starting AI categorizer subprocess")

    # Wait 1 minute before first run (let some data accumulate)
    for _ in range(60):
        if stop_event.is_set():
            return
        time.sleep(1)

    while not stop_event.is_set():
        try:
            categorizer = SessionCategorizer()
            categorizer.categorize_batch()
            categorizer.close()
        except Exception as e:
            logger.error(f"AI categorizer error: {e}")

        # Run every 15 minutes (configurable)
        for _ in range(AI_CATEGORIZATION_INTERVAL_MINUTES * 60):
            if stop_event.is_set():
                break
            time.sleep(1)


class BackgroundRunner:
    """Orchestrates all background services."""

    def __init__(self):
        self.processes = []
        self.stop_event = multiprocessing.Event()

    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info(f"Received signal {signum}, shutting down...")
        self.stop_event.set()
        self._stop_all_processes()
        sys.exit(0)

    def _stop_all_processes(self):
        """Stop all running processes."""
        self.stop_event.set()
        for process in self.processes:
            if process.is_alive():
                logger.info(f"Stopping process: {process.name}")
                process.join(timeout=5)
                if process.is_alive():
                    logger.warning(f"Force killing process: {process.name}")
                    process.kill()

    def _check_accessibility_permissions(self) -> bool:
        """Check if accessibility permissions are granted."""
        try:
            import subprocess
            result = subprocess.run(
                ['osascript', '-e', 'tell application "System Events" to get name of first application process whose frontmost is true'],
                capture_output=True,
                text=True,
                timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                logger.info(f"Accessibility check passed - detected app: {result.stdout.strip()}")
                return True
            else:
                logger.warning("Accessibility check inconclusive - will try anyway")
                return True  # Try anyway
        except Exception as e:
            logger.warning(f"Accessibility check failed: {e} - will try anyway")
            return True  # Try anyway - let the monitor itself fail if needed

    def start(self):
        """Start all background services."""
        # Setup signal handlers after initialization
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)

        logger.info("="*50)
        logger.info("Starting macOS Activity Tracker")
        logger.info("="*50)

        # Check permissions
        if not self._check_accessibility_permissions():
            logger.error("Cannot start without accessibility permissions")
            return

        # Start window monitor
        monitor_process = multiprocessing.Process(
            target=run_window_monitor,
            name="WindowMonitor"
        )
        monitor_process.start()
        self.processes.append(monitor_process)
        logger.info("Window monitor started")

        # Start activity processor
        processor_process = multiprocessing.Process(
            target=run_activity_processor,
            args=(self.stop_event,),
            name="ActivityProcessor"
        )
        processor_process.start()
        self.processes.append(processor_process)
        logger.info("Activity processor started")

        # Start Slack tracker
        slack_tracker_process = multiprocessing.Process(
            target=run_slack_tracker,
            args=(self.stop_event,),
            name="SlackTracker"
        )
        slack_tracker_process.start()
        self.processes.append(slack_tracker_process)
        logger.info("Slack tracker started")

        # Start AI categorizer
        categorizer_process = multiprocessing.Process(
            target=run_ai_categorizer,
            args=(self.stop_event,),
            name="AICategorizer"
        )
        categorizer_process.start()
        self.processes.append(categorizer_process)
        logger.info("AI categorizer started")

        logger.info("="*50)
        logger.info("All services running. Press Ctrl+C to stop.")
        logger.info("="*50)

        # Keep main process alive
        try:
            while not self.stop_event.is_set():
                # Check if any process died and restart it
                for i, process in enumerate(self.processes):
                    if not process.is_alive():
                        logger.error(f"Process {process.name} died unexpectedly! Restarting...")

                        # Restart the process
                        if process.name == "WindowMonitor":
                            new_process = multiprocessing.Process(
                                target=run_window_monitor,
                                name="WindowMonitor"
                            )
                        elif process.name == "ActivityProcessor":
                            new_process = multiprocessing.Process(
                                target=run_activity_processor,
                                args=(self.stop_event,),
                                name="ActivityProcessor"
                            )
                        elif process.name == "SlackTracker":
                            new_process = multiprocessing.Process(
                                target=run_slack_tracker,
                                args=(self.stop_event,),
                                name="SlackTracker"
                            )
                        elif process.name == "AICategorizer":
                            new_process = multiprocessing.Process(
                                target=run_ai_categorizer,
                                args=(self.stop_event,),
                                name="AICategorizer"
                            )

                        new_process.start()
                        self.processes[i] = new_process
                        logger.info(f"Process {process.name} restarted")

                time.sleep(10)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
            self._stop_all_processes()


def main():
    """Entry point for background runner."""
    runner = BackgroundRunner()
    runner.start()


if __name__ == '__main__':
    main()
