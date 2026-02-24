"""
Configuration management for activity tracker.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Project root
PROJECT_ROOT = Path(__file__).parent.parent

# Database
DATABASE_PATH = os.getenv('DATABASE_PATH', str(PROJECT_ROOT / 'data' / 'activities.db'))

# Tracking
POLLING_INTERVAL_SECONDS = int(os.getenv('POLLING_INTERVAL_SECONDS', '5'))  # Reduced from 3s to avoid macOS throttling
SESSION_TIMEOUT_SECONDS = int(os.getenv('SESSION_TIMEOUT_SECONDS', '30'))
RAPID_SWITCH_THRESHOLD_SECONDS = int(os.getenv('RAPID_SWITCH_THRESHOLD_SECONDS', '30'))
DEEP_WORK_THRESHOLD_SECONDS = 25 * 60  # 25 minutes

# AI Configuration
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY', '')
AI_BATCH_SIZE = int(os.getenv('AI_BATCH_SIZE', '50'))
AI_CATEGORIZATION_INTERVAL_MINUTES = int(os.getenv('AI_CATEGORIZATION_INTERVAL_MINUTES', '15'))

# Dashboard
FLASK_HOST = os.getenv('FLASK_HOST', '127.0.0.1')
FLASK_PORT = int(os.getenv('FLASK_PORT', '5000'))
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'

# Logging
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
LOG_FILE = os.getenv('LOG_FILE', str(PROJECT_ROOT / 'data' / 'logs' / 'tracker.log'))

# Ensure directories exist
Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
