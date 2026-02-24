"""
Advanced Slack analytics for ADHD-focused insights.
"""
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from sqlalchemy import text
from collections import defaultdict

from database.models import get_session
from config.logging import setup_logging

logger = setup_logging('slack_analytics')


class SlackAnalytics:
    """Advanced analytics for Slack usage patterns."""

    def __init__(self):
        self.db = get_session()

    def get_piecemeal_message_patterns(
        self,
        date: datetime.date,
        important_people: List[str] = None,
        grouping_window_minutes: int = 5
    ) -> List[Dict]:
        """
        Detect piecemeal messaging patterns (multiple views of same conversation in short time).

        Args:
            date: Date to analyze
            important_people: List of person names/patterns to track (e.g., manager)
            grouping_window_minutes: Group views within this window

        Returns:
            List of piecemeal patterns with conversation name, view count, total time
        """
        start_time = datetime.combine(date, datetime.min.time())
        end_time = datetime.combine(date, datetime.max.time())

        # Get all views for the day, ordered by time
        result = self.db.execute(text("""
            SELECT
                sc.conversation_name,
                sc.conversation_type,
                sv.viewed_at,
                sv.duration_seconds,
                sv.had_new_messages,
                sv.new_message_count
            FROM slack_conversations sc
            JOIN slack_views sv ON sc.id = sv.conversation_id
            WHERE sv.viewed_at BETWEEN :start_time AND :end_time
            ORDER BY sc.conversation_name, sv.viewed_at
        """), {'start_time': start_time, 'end_time': end_time})

        # Group views into piecemeal windows
        conversation_windows = defaultdict(list)
        current_window = {}

        for row in result:
            conv_name = row[0]
            conv_type = row[1]
            viewed_at = row[2]
            duration = row[3]
            had_new_msgs = row[4]
            new_msg_count = row[5]

            # Check if this should filter by important people
            if important_people:
                if not any(person.lower() in conv_name.lower() for person in important_people):
                    continue

            # Convert string timestamp if needed
            if isinstance(viewed_at, str):
                viewed_at = datetime.fromisoformat(viewed_at)

            # Start new window or extend existing
            if conv_name not in current_window:
                current_window[conv_name] = {
                    'conversation_name': conv_name,
                    'conversation_type': conv_type,
                    'start_time': viewed_at,
                    'end_time': viewed_at,
                    'view_count': 1,
                    'total_duration': duration,
                    'had_new_messages': had_new_msgs,
                    'total_new_messages': new_msg_count or 0
                }
            else:
                window = current_window[conv_name]
                time_gap = (viewed_at - window['end_time']).total_seconds() / 60

                if time_gap <= grouping_window_minutes:
                    # Extend window
                    window['end_time'] = viewed_at
                    window['view_count'] += 1
                    window['total_duration'] += duration
                    window['had_new_messages'] = window['had_new_messages'] or had_new_msgs
                    window['total_new_messages'] += (new_msg_count or 0)
                else:
                    # Save current window and start new one
                    if window['view_count'] > 1:  # Only save piecemeal patterns
                        conversation_windows[conv_name].append(window.copy())

                    current_window[conv_name] = {
                        'conversation_name': conv_name,
                        'conversation_type': conv_type,
                        'start_time': viewed_at,
                        'end_time': viewed_at,
                        'view_count': 1,
                        'total_duration': duration,
                        'had_new_messages': had_new_msgs,
                        'total_new_messages': new_msg_count or 0
                    }

        # Save remaining windows
        for conv_name, window in current_window.items():
            if window['view_count'] > 1:
                conversation_windows[conv_name].append(window)

        # Flatten and sort by view count
        piecemeal_patterns = []
        for conv_name, windows in conversation_windows.items():
            for window in windows:
                piecemeal_patterns.append({
                    'conversation_name': window['conversation_name'],
                    'conversation_type': window['conversation_type'],
                    'start_time': window['start_time'].isoformat(),
                    'end_time': window['end_time'].isoformat(),
                    'view_count': window['view_count'],
                    'total_duration_minutes': round(window['total_duration'] / 60, 1),
                    'had_new_messages': window['had_new_messages'],
                    'total_new_messages': window['total_new_messages'],
                    'is_important': important_people and any(
                        person.lower() in window['conversation_name'].lower()
                        for person in important_people
                    )
                })

        piecemeal_patterns.sort(key=lambda x: x['view_count'], reverse=True)
        return piecemeal_patterns

    def get_context_switching_cost(self, date: datetime.date) -> Dict:
        """
        Calculate cost of context switching between Slack conversations.

        Args:
            date: Date to analyze

        Returns:
            Dict with switching metrics
        """
        start_time = datetime.combine(date, datetime.min.time())
        end_time = datetime.combine(date, datetime.max.time())

        # Get all views ordered by time
        result = self.db.execute(text("""
            SELECT
                sc.conversation_name,
                sv.viewed_at,
                sv.duration_seconds
            FROM slack_conversations sc
            JOIN slack_views sv ON sc.id = sv.conversation_id
            WHERE sv.viewed_at BETWEEN :start_time AND :end_time
            ORDER BY sv.viewed_at
        """), {'start_time': start_time, 'end_time': end_time})

        views = list(result)
        if len(views) < 2:
            return {
                'total_switches': 0,
                'rapid_switches': 0,
                'average_time_before_switch_seconds': 0
            }

        total_switches = 0
        rapid_switches = 0  # Switches < 60 seconds
        durations_before_switch = []

        for i in range(len(views) - 1):
            current_conv = views[i][0]
            next_conv = views[i + 1][0]
            duration = views[i][2]

            if current_conv != next_conv:
                total_switches += 1
                durations_before_switch.append(duration)

                if duration < 60:
                    rapid_switches += 1

        avg_duration = sum(durations_before_switch) / len(durations_before_switch) if durations_before_switch else 0

        return {
            'total_switches': total_switches,
            'rapid_switches': rapid_switches,
            'rapid_switch_percentage': round(rapid_switches / total_switches * 100, 1) if total_switches > 0 else 0,
            'average_time_before_switch_seconds': round(avg_duration, 1),
            'average_time_before_switch_minutes': round(avg_duration / 60, 1)
        }

    def get_response_time_patterns(
        self,
        date: datetime.date,
        important_people: List[str] = None
    ) -> List[Dict]:
        """
        Calculate response times to new messages in conversations.

        Args:
            date: Date to analyze
            important_people: List of person names/patterns to prioritize

        Returns:
            List of conversations with response time metrics
        """
        start_time = datetime.combine(date, datetime.min.time())
        end_time = datetime.combine(date, datetime.max.time())

        # Get views with new messages
        result = self.db.execute(text("""
            SELECT
                sc.conversation_name,
                sc.conversation_type,
                sv.viewed_at,
                sv.new_message_count,
                LAG(sv.viewed_at) OVER (PARTITION BY sc.id ORDER BY sv.viewed_at) as previous_view
            FROM slack_conversations sc
            JOIN slack_views sv ON sc.id = sv.conversation_id
            WHERE sv.viewed_at BETWEEN :start_time AND :end_time
                AND sv.had_new_messages = TRUE
            ORDER BY sv.viewed_at
        """), {'start_time': start_time, 'end_time': end_time})

        response_times = defaultdict(list)

        for row in result:
            conv_name = row[0]
            conv_type = row[1]
            viewed_at = row[2]
            new_msg_count = row[3]
            previous_view = row[4]

            # If there was a previous view, calculate time since
            if previous_view:
                if isinstance(viewed_at, str):
                    viewed_at = datetime.fromisoformat(viewed_at)
                if isinstance(previous_view, str):
                    previous_view = datetime.fromisoformat(previous_view)

                response_time_seconds = (viewed_at - previous_view).total_seconds()

                response_times[conv_name].append({
                    'response_time_seconds': response_time_seconds,
                    'new_message_count': new_msg_count
                })

        # Calculate average response times
        response_patterns = []
        for conv_name, times in response_times.items():
            avg_response = sum(t['response_time_seconds'] for t in times) / len(times)
            total_messages = sum(t['new_message_count'] for t in times)

            is_important = important_people and any(
                person.lower() in conv_name.lower()
                for person in important_people
            )

            response_patterns.append({
                'conversation_name': conv_name,
                'average_response_time_seconds': round(avg_response, 1),
                'average_response_time_minutes': round(avg_response / 60, 1),
                'total_responses': len(times),
                'total_new_messages': total_messages,
                'is_important': is_important
            })

        # Sort important people first, then by response time
        response_patterns.sort(key=lambda x: (not x['is_important'], x['average_response_time_seconds']))
        return response_patterns

    def get_unread_important_conversations(self, important_people: List[str]) -> List[Dict]:
        """
        Find important conversations that haven't been checked recently.

        Args:
            important_people: List of person names/patterns to track

        Returns:
            List of important conversations not checked in a while
        """
        if not important_people:
            return []

        # Get conversations matching important people
        patterns = [f"%{person}%" for person in important_people]
        placeholders = ', '.join([f':pattern_{i}' for i in range(len(patterns))])

        result = self.db.execute(text(f"""
            SELECT
                conversation_name,
                conversation_type,
                last_viewed,
                view_count,
                total_time_seconds
            FROM slack_conversations
            WHERE ({' OR '.join([f'conversation_name LIKE :pattern_{i}' for i in range(len(patterns))])})
            ORDER BY last_viewed DESC
        """), {f'pattern_{i}': patterns[i] for i in range(len(patterns))})

        conversations = []
        now = datetime.now()

        for row in result:
            conv_name = row[0]
            conv_type = row[1]
            last_viewed = row[2]
            view_count = row[3]
            total_time = row[4]

            if isinstance(last_viewed, str):
                last_viewed = datetime.fromisoformat(last_viewed)

            time_since_check = (now - last_viewed).total_seconds() / 60  # minutes

            conversations.append({
                'conversation_name': conv_name,
                'conversation_type': conv_type,
                'last_viewed': last_viewed.isoformat(),
                'minutes_since_check': round(time_since_check, 1),
                'view_count': view_count,
                'total_time_minutes': round(total_time / 60, 1)
            })

        return conversations

    def close(self):
        """Close database session."""
        self.db.close()
