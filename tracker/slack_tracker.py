"""
Track Slack conversation views and reading patterns.
"""
from datetime import datetime, timedelta
from typing import List, Dict
from sqlalchemy import text

from database.models import Activity, get_session
from tracker.slack_parser import SlackParser
from config.logging import setup_logging

logger = setup_logging('slack_tracker')


class SlackTracker:
    """Tracks Slack conversation views from activity data."""

    def __init__(self):
        self.db = get_session()
        self.parser = SlackParser()

    def process_slack_activities(self, since: datetime = None) -> int:
        """
        Process Slack activities and update tracking.

        Args:
            since: Only process activities after this time (default: last 24 hours)

        Returns:
            Number of Slack views processed
        """
        if since is None:
            since = datetime.now() - timedelta(hours=24)

        # Get Slack activities
        activities = self.db.query(Activity).filter(
            Activity.app_name == 'Slack',
            Activity.timestamp >= since,
            Activity.window_title.isnot(None)
        ).order_by(Activity.timestamp).all()

        if not activities:
            logger.info("No Slack activities to process")
            return 0

        logger.info(f"Processing {len(activities)} Slack activities")

        # Group consecutive activities into views
        views = self._group_into_views(activities)

        # Save views to database
        for view in views:
            self._save_view(view)

        self.db.commit()
        logger.info(f"Processed {len(views)} Slack views")
        return len(views)

    def _group_into_views(self, activities: List[Activity]) -> List[Dict]:
        """
        Group consecutive Slack activities into conversation views.

        A "view" is continuous time spent in a specific conversation.
        """
        views = []
        current_view = None

        for activity in activities:
            parsed = self.parser.parse_window_title(activity.window_title)
            if not parsed:
                continue

            # Start new view if conversation changed or gap > 30 seconds
            if current_view is None:
                current_view = {
                    'conversation_name': parsed['conversation_name'],
                    'conversation_type': parsed['conversation_type'],
                    'workspace': parsed['workspace'],
                    'start_time': activity.timestamp,
                    'end_time': activity.timestamp,
                    'had_new_messages': parsed['has_new_messages'],
                    'new_message_count': parsed['new_message_count']
                }
            elif (parsed['conversation_name'] != current_view['conversation_name'] or
                  (activity.timestamp - current_view['end_time']).total_seconds() > 30):
                # Save current view and start new one
                views.append(current_view)
                current_view = {
                    'conversation_name': parsed['conversation_name'],
                    'conversation_type': parsed['conversation_type'],
                    'workspace': parsed['workspace'],
                    'start_time': activity.timestamp,
                    'end_time': activity.timestamp,
                    'had_new_messages': parsed['has_new_messages'],
                    'new_message_count': parsed['new_message_count']
                }
            else:
                # Extend current view
                current_view['end_time'] = activity.timestamp
                current_view['had_new_messages'] = current_view['had_new_messages'] or parsed['has_new_messages']
                current_view['new_message_count'] = max(current_view['new_message_count'], parsed['new_message_count'])

        # Don't forget the last view
        if current_view:
            views.append(current_view)

        return views

    def _save_view(self, view: Dict):
        """Save a Slack view to the database."""
        # Get or create conversation
        result = self.db.execute(text("""
            INSERT INTO slack_conversations (conversation_name, conversation_type, workspace, last_viewed, view_count, total_time_seconds)
            VALUES (:name, :type, :workspace, :last_viewed, 1, :duration)
            ON CONFLICT(conversation_name, workspace) DO UPDATE SET
                last_viewed = :last_viewed,
                view_count = view_count + 1,
                total_time_seconds = total_time_seconds + :duration
            RETURNING id
        """), {
            'name': view['conversation_name'],
            'type': view['conversation_type'],
            'workspace': view['workspace'],
            'last_viewed': view['end_time'],
            'duration': (view['end_time'] - view['start_time']).total_seconds()
        })

        conversation_id = result.fetchone()[0]

        # Insert view record
        self.db.execute(text("""
            INSERT INTO slack_views (conversation_id, viewed_at, duration_seconds, had_new_messages, new_message_count)
            VALUES (:conversation_id, :viewed_at, :duration, :had_new_messages, :new_message_count)
        """), {
            'conversation_id': conversation_id,
            'viewed_at': view['start_time'],
            'duration': (view['end_time'] - view['start_time']).total_seconds(),
            'had_new_messages': view['had_new_messages'],
            'new_message_count': view['new_message_count']
        })

    def close(self):
        """Close database session."""
        self.db.close()


def main():
    """Process recent Slack activities."""
    tracker = SlackTracker()
    try:
        count = tracker.process_slack_activities()
        print(f"Processed {count} Slack views")
    finally:
        tracker.close()


if __name__ == '__main__':
    main()
