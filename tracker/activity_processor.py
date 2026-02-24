"""
Activity processor - aggregates raw activities into sessions.
Runs every 5 minutes to create session records.
"""
import sys
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timedelta
from typing import List
from sqlalchemy import and_

from database.models import Activity, Session, AppSwitch, get_session
from config.logging import setup_logging
from config.settings import (
    SESSION_TIMEOUT_SECONDS,
    RAPID_SWITCH_THRESHOLD_SECONDS,
    DEEP_WORK_THRESHOLD_SECONDS
)

logger = setup_logging('activity_processor')


class ActivityProcessor:
    """Processes raw activities into aggregated sessions."""

    def __init__(self):
        self.db_session = get_session()

    def _get_unprocessed_activities(self) -> List[Activity]:
        """Get activities that haven't been processed into sessions yet."""
        # Find the timestamp of the last processed session
        last_session = self.db_session.query(Session).order_by(
            Session.end_time.desc()
        ).first()

        if last_session:
            start_time = last_session.end_time
        else:
            # No sessions yet, start from beginning
            start_time = datetime.min

        activities = self.db_session.query(Activity).filter(
            Activity.timestamp > start_time
        ).order_by(Activity.timestamp).all()

        return activities

    def _get_app_family(self, bundle_id: str, app_name: str = '') -> str:
        """Detect app family for smarter grouping."""
        bundle_lower = bundle_id.lower()
        app_lower = app_name.lower()

        # Browsers
        if any(x in bundle_lower or x in app_lower for x in ['chrome', 'safari', 'firefox', 'brave', 'edge', 'arc', 'opera']):
            return 'browser'

        # Communication
        if any(x in bundle_lower or x in app_lower for x in ['slack', 'zoom', 'teams', 'discord', 'skype', 'telegram', 'signal']):
            return 'communication'

        # Development
        if any(x in bundle_lower or x in app_lower for x in ['vscode', 'terminal', 'iterm', 'pycharm', 'intellij', 'xcode', 'cursor', 'claude']):
            return 'development'

        # Productivity
        if any(x in bundle_lower or x in app_lower for x in ['notion', 'evernote', 'onenote', 'obsidian', 'roam']):
            return 'productivity'

        # Design
        if any(x in bundle_lower or x in app_lower for x in ['figma', 'sketch', 'photoshop', 'illustrator', 'canva']):
            return 'design'

        # Email
        if any(x in bundle_lower or x in app_lower for x in ['mail', 'gmail', 'outlook', 'spark', 'superhuman', 'comet']):
            return 'email'

        return bundle_id  # Use full bundle ID if not in a family

    def _is_same_app_family(self, bundle_id1: str, bundle_id2: str, app_name1: str = '', app_name2: str = '') -> bool:
        """Check if two apps are in the same family."""
        return self._get_app_family(bundle_id1, app_name1) == self._get_app_family(bundle_id2, app_name2)

    def _are_related_apps(self, bundle_id1: str, bundle_id2: str, app_name1: str = '', app_name2: str = '') -> bool:
        """Check if apps are commonly used together (task-related)."""
        # Get families
        family1 = self._get_app_family(bundle_id1, app_name1)
        family2 = self._get_app_family(bundle_id2, app_name2)

        # Common work pairs
        related_pairs = [
            {'development', 'browser'},      # Coding + docs
            {'development', 'communication'}, # Coding + asking for help
            {'productivity', 'communication'}, # Note-taking + messaging
            {'productivity', 'browser'},     # Research + note-taking
            {'email', 'browser'},            # Email + web
            {'email', 'productivity'},       # Email + notes
        ]

        pair = {family1, family2}
        return pair in related_pairs or family1 == family2

    def _group_into_sessions(self, activities: List[Activity]) -> List[dict]:
        """Group activities into sessions with smart intent detection."""
        if not activities:
            return []

        sessions = []
        current_session = {
            'app_bundle_id': activities[0].app_bundle_id,
            'app_name': activities[0].app_name,
            'window_title': activities[0].window_title,
            'window_title_hash': activities[0].window_title_hash,
            'is_sensitive': activities[0].is_sensitive,
            'start_time': activities[0].timestamp,
            'end_time': activities[0].timestamp,
            'activities': [activities[0]],
            'app_switches': 0,
            'apps_in_session': {activities[0].app_bundle_id},  # Track unique apps
            'app_families': {self._get_app_family(activities[0].app_bundle_id, activities[0].app_name)}
        }

        for i, activity in enumerate(activities[1:], 1):
            time_gap = (activity.timestamp - current_session['end_time']).total_seconds()
            same_app = activity.app_bundle_id == current_session['app_bundle_id']
            same_family = self._is_same_app_family(
                activity.app_bundle_id, current_session['app_bundle_id'],
                activity.app_name, current_session['app_name']
            )
            related_apps = self._are_related_apps(
                activity.app_bundle_id, current_session['app_bundle_id'],
                activity.app_name, current_session['app_name']
            )

            # Look ahead for context: is this a quick detour?
            is_quick_detour = False
            if i < len(activities) - 1:
                next_activity = activities[i + 1]
                # If we return to current session's app soon, this is a quick check
                if next_activity.app_bundle_id == current_session['app_bundle_id']:
                    detour_duration = (next_activity.timestamp - activity.timestamp).total_seconds()
                    if detour_duration < 60:  # Quick check < 1 minute
                        is_quick_detour = True

            # Smart grouping logic
            should_extend = False
            grouping_reason = None

            # Case 1: Same app, within timeout
            if same_app and time_gap <= SESSION_TIMEOUT_SECONDS:
                should_extend = True
                grouping_reason = 'same_app'

            # Case 2: Same family organization (tab cleanup, channel switching)
            elif same_family and time_gap <= 120:
                should_extend = True
                grouping_reason = 'same_family'
                current_session['app_switches'] += 1

            # Case 3: Related apps (common work pairs) within 90 seconds
            elif related_apps and time_gap <= 90:
                should_extend = True
                grouping_reason = 'related_apps'
                current_session['app_switches'] += 1

            # Case 4: Quick detour/check - returning to main task
            elif is_quick_detour and time_gap <= 60:
                should_extend = True
                grouping_reason = 'quick_check'
                current_session['app_switches'] += 1

            # Case 5: Micro-break within same work context (< 3 min gap, same family)
            elif same_family and time_gap <= 180:
                should_extend = True
                grouping_reason = 'micro_break'
                current_session['app_switches'] += 1

            if should_extend:
                current_session['end_time'] = activity.timestamp
                current_session['activities'].append(activity)
                current_session['apps_in_session'].add(activity.app_bundle_id)
                current_session['app_families'].add(
                    self._get_app_family(activity.app_bundle_id, activity.app_name)
                )

                # Update window title
                if not activity.is_sensitive and activity.window_title:
                    current_session['window_title'] = activity.window_title
                elif activity.is_sensitive and activity.window_title_hash:
                    current_session['window_title_hash'] = activity.window_title_hash

                # Track grouping metadata
                if not same_app:
                    current_session['is_mixed'] = True
                    if 'grouping_reasons' not in current_session:
                        current_session['grouping_reasons'] = []
                    if grouping_reason:
                        current_session['grouping_reasons'].append(grouping_reason)
            else:
                # Save current session and start new one
                sessions.append(current_session)

                current_session = {
                    'app_bundle_id': activity.app_bundle_id,
                    'app_name': activity.app_name,
                    'window_title': activity.window_title,
                    'window_title_hash': activity.window_title_hash,
                    'is_sensitive': activity.is_sensitive,
                    'start_time': activity.timestamp,
                    'end_time': activity.timestamp,
                    'activities': [activity],
                    'app_switches': 0,
                    'apps_in_session': {activity.app_bundle_id},
                    'app_families': {self._get_app_family(activity.app_bundle_id, activity.app_name)}
                }

        # Add last session
        sessions.append(current_session)

        return sessions

    def _create_session_record(self, session_data: dict) -> Session:
        """Create a Session database record with smart intent classification."""
        import json
        from collections import Counter

        duration = (session_data['end_time'] - session_data['start_time']).total_seconds()

        # Get metadata
        app_switches = session_data.get('app_switches', 0)
        is_mixed = session_data.get('is_mixed', False)
        grouping_reasons = session_data.get('grouping_reasons', [])
        num_apps = len(session_data.get('apps_in_session', {1}))
        num_families = len(session_data.get('app_families', {1}))

        # Detect split screen session
        is_split_screen = False
        visible_apps_json = None
        activities = session_data.get('activities', [])

        if activities:
            # Count how many activities had multiple visible apps
            multi_app_count = 0
            all_visible_apps = []

            for activity in activities:
                if activity.visible_apps:
                    try:
                        visible = json.loads(activity.visible_apps)
                        if len(visible) > 1:  # More than just the active app
                            multi_app_count += 1
                            all_visible_apps.extend(visible)
                    except:
                        pass

            # If > 50% of activities had multiple apps visible, check if it's real split screen
            if len(activities) > 2 and multi_app_count / len(activities) >= 0.5:
                # Get unique visible apps
                app_counts = Counter(all_visible_apps)
                unique_apps = len(app_counts)

                # Only mark as split screen if 2-4 apps (real split screen scenario)
                # If 5+ apps, it's likely many apps across desktops, not actual split screen
                if 2 <= unique_apps <= 4:
                    is_split_screen = True
                    common_apps = [app for app, count in app_counts.most_common(3)]
                    visible_apps_json = json.dumps(common_apps)
                    logger.debug(f"Split screen detected: {unique_apps} apps ({common_apps})")
                else:
                    logger.debug(f"Not split screen: {unique_apps} visible apps (too many for split screen)")

        # Smart classification
        is_deep_work = duration >= DEEP_WORK_THRESHOLD_SECONDS

        # Organizational: cleanup, tidying, organizing
        is_organizational = (
            is_mixed and
            30 < duration < 240 and  # 30 seconds to 4 minutes
            app_switches >= 2 and
            num_families == 1  # All within same family
        )

        # Task-based: switching between related apps for a task
        is_task_based = (
            'related_apps' in grouping_reasons or
            ('quick_check' in grouping_reasons and duration > 120)
        )

        # Rapid switch: only if NOT organizational, task-based, or split screen
        is_rapid_switch = (
            duration < RAPID_SWITCH_THRESHOLD_SECONDS and
            not is_organizational and
            not is_task_based and
            not is_split_screen and  # Split screen is NOT rapid switching!
            num_families > 1  # Switching between different types of apps
        )

        session = Session(
            start_time=session_data['start_time'],
            end_time=session_data['end_time'],
            duration_seconds=duration,
            app_bundle_id=session_data['app_bundle_id'],
            app_name=session_data['app_name'],
            window_title=session_data['window_title'],
            window_title_hash=session_data['window_title_hash'],
            is_sensitive=session_data['is_sensitive'],
            is_rapid_switch=is_rapid_switch,
            is_deep_work=is_deep_work,
            is_split_screen=is_split_screen,
            visible_apps=visible_apps_json
        )

        return session

    def _record_app_switch(self, from_session: dict, to_session: dict):
        """Record an app switch for ADHD tracking."""
        from_duration = (from_session['end_time'] - from_session['start_time']).total_seconds()
        is_rapid = from_duration < RAPID_SWITCH_THRESHOLD_SECONDS

        # Count switches in the last minute
        one_minute_ago = to_session['start_time'] - timedelta(minutes=1)
        recent_switches = self.db_session.query(AppSwitch).filter(
            AppSwitch.timestamp >= one_minute_ago
        ).count()

        switch = AppSwitch(
            timestamp=to_session['start_time'],
            from_app_bundle_id=from_session['app_bundle_id'],
            from_app_name=from_session['app_name'],
            from_duration_seconds=from_duration,
            to_app_bundle_id=to_session['app_bundle_id'],
            to_app_name=to_session['app_name'],
            is_rapid=is_rapid,
            switch_count_in_minute=recent_switches + 1
        )

        self.db_session.add(switch)

    def process(self) -> int:
        """Process unprocessed activities into sessions."""
        logger.info("Processing activities into sessions...")

        activities = self._get_unprocessed_activities()
        if not activities:
            logger.info("No new activities to process")
            return 0

        logger.info(f"Processing {len(activities)} activities")

        # Group into sessions
        session_groups = self._group_into_sessions(activities)
        logger.info(f"Created {len(session_groups)} sessions")

        # Create session records and track switches
        previous_session = None
        for session_data in session_groups:
            session = self._create_session_record(session_data)
            self.db_session.add(session)

            # Track app switches
            if previous_session and previous_session['app_bundle_id'] != session_data['app_bundle_id']:
                self._record_app_switch(previous_session, session_data)

            previous_session = session_data

        self.db_session.commit()
        logger.info(f"Successfully processed {len(session_groups)} sessions")

        return len(session_groups)

    def close(self):
        """Close database session."""
        self.db_session.close()


def main():
    """Entry point for activity processor."""
    processor = ActivityProcessor()
    try:
        processor.process()
    finally:
        processor.close()


if __name__ == '__main__':
    main()
