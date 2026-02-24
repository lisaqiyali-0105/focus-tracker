"""
Task Cluster Analyzer - Detects task-focused multi-app patterns.

Identifies "anchor apps" and groups related sessions into task clusters
to capture ADHD-friendly work patterns where you flip between apps
while staying focused on a single task.
"""
import sys
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import Counter, defaultdict
from dataclasses import dataclass

from database.models import Session, get_session
from config.logging import setup_logging
from config.settings import DEEP_WORK_THRESHOLD_SECONDS

logger = setup_logging('task_cluster_analyzer')


@dataclass
class TaskCluster:
    """Represents a detected task cluster."""
    sessions: List[Session]
    anchor_app: str
    anchor_app_name: str
    start_time: datetime
    end_time: datetime
    total_duration: float
    anchor_duration: float
    support_apps: List[Tuple[str, float]]  # [(app_name, duration), ...]
    is_deep_work: bool
    cluster_type: str  # 'anchor_focused', 'multi_app_task', 'flow_state'


class TaskClusterAnalyzer:
    """Analyzes sessions to detect task-focused multi-app patterns."""

    # Time window for detecting task clusters (30 minutes)
    CLUSTER_WINDOW_MINUTES = 30

    # Minimum anchor app percentage to qualify as task cluster (50%)
    MIN_ANCHOR_PERCENTAGE = 0.50

    # Minimum total duration for deep work task cluster (25 minutes)
    MIN_TASK_DEEP_WORK_MINUTES = 25

    # Maximum detour duration (5 minutes)
    MAX_DETOUR_MINUTES = 5

    # Apps commonly used for support tasks (not anchor apps)
    SUPPORT_APP_PATTERNS = [
        'slack', 'zoom', 'teams', 'discord',  # Communication
        'chrome', 'safari', 'firefox', 'arc',  # Quick lookups
        'mail', 'gmail', 'outlook', 'comet',   # Email checks
        'finder', 'terminal'                    # File/system tasks
    ]

    def __init__(self, db_session=None):
        self.db_session = db_session or get_session()

    def _is_support_app(self, app_name: str) -> bool:
        """Check if an app is typically used for support tasks."""
        app_lower = app_name.lower()
        return any(pattern in app_lower for pattern in self.SUPPORT_APP_PATTERNS)

    def _find_anchor_app(self, sessions: List[Session]) -> Optional[Tuple[str, str, float]]:
        """
        Find the anchor app in a group of sessions.

        Returns (bundle_id, app_name, total_duration) or None.

        Anchor app criteria:
        1. Most time spent in that app
        2. Returned to multiple times
        3. Not a support app (unless dominant)
        """
        if not sessions:
            return None

        # Calculate time per app and return count
        app_durations = defaultdict(float)
        app_names = {}
        app_returns = defaultdict(int)

        prev_app = None
        for session in sessions:
            app_durations[session.app_bundle_id] += session.duration_seconds
            app_names[session.app_bundle_id] = session.app_name

            # Count returns to this app
            if prev_app != session.app_bundle_id:
                app_returns[session.app_bundle_id] += 1
            prev_app = session.app_bundle_id

        # Find app with most time that was returned to
        candidates = []
        total_time = sum(app_durations.values())

        for bundle_id, duration in app_durations.items():
            percentage = duration / total_time if total_time > 0 else 0
            returns = app_returns[bundle_id]
            is_support = self._is_support_app(app_names[bundle_id])

            # Score: duration percentage + return bonus - support penalty
            score = percentage + (returns * 0.05) - (0.2 if is_support else 0)

            candidates.append({
                'bundle_id': bundle_id,
                'app_name': app_names[bundle_id],
                'duration': duration,
                'percentage': percentage,
                'returns': returns,
                'is_support': is_support,
                'score': score
            })

        # Sort by score
        candidates.sort(key=lambda x: x['score'], reverse=True)

        if not candidates:
            return None

        best = candidates[0]

        # Must meet minimum anchor criteria
        if best['percentage'] >= self.MIN_ANCHOR_PERCENTAGE or best['returns'] >= 3:
            return (best['bundle_id'], best['app_name'], best['duration'])

        return None

    def _detect_task_clusters(self, sessions: List[Session]) -> List[TaskCluster]:
        """
        Detect task clusters in a list of sessions using sliding window.

        Algorithm:
        1. Use 30-minute sliding windows
        2. In each window, find anchor app
        3. If anchor app meets criteria, create task cluster
        4. Classify detours (quick checks vs. distractions)
        """
        if not sessions:
            return []

        clusters = []
        window_size = timedelta(minutes=self.CLUSTER_WINDOW_MINUTES)

        # Sort sessions by start time
        sorted_sessions = sorted(sessions, key=lambda s: s.start_time)

        i = 0
        while i < len(sorted_sessions):
            window_start = sorted_sessions[i].start_time
            window_end = window_start + window_size

            # Get all sessions in this window
            window_sessions = []
            j = i
            while j < len(sorted_sessions) and sorted_sessions[j].start_time < window_end:
                window_sessions.append(sorted_sessions[j])
                j += 1

            # Skip if too few sessions
            if len(window_sessions) < 2:
                i += 1
                continue

            # Find anchor app
            anchor_info = self._find_anchor_app(window_sessions)

            if anchor_info:
                anchor_bundle_id, anchor_name, anchor_duration = anchor_info

                # Calculate total duration
                total_duration = sum(s.duration_seconds for s in window_sessions)
                actual_end = max(s.end_time for s in window_sessions)

                # Find support apps
                support_apps = []
                for session in window_sessions:
                    if session.app_bundle_id != anchor_bundle_id:
                        support_apps.append((session.app_name, session.duration_seconds))

                # Aggregate support apps
                support_aggregated = defaultdict(float)
                for app_name, duration in support_apps:
                    support_aggregated[app_name] += duration
                support_apps_sorted = sorted(
                    support_aggregated.items(),
                    key=lambda x: x[1],
                    reverse=True
                )

                # Determine cluster type
                anchor_percentage = anchor_duration / total_duration if total_duration > 0 else 0
                num_apps = len(set(s.app_bundle_id for s in window_sessions))

                if anchor_percentage >= 0.75 and num_apps <= 3:
                    cluster_type = 'anchor_focused'
                elif len(window_sessions) >= 4 and num_apps >= 3:
                    cluster_type = 'multi_app_task'
                else:
                    cluster_type = 'flow_state'

                # Check if qualifies as deep work
                is_deep_work = (
                    total_duration >= DEEP_WORK_THRESHOLD_SECONDS or
                    anchor_duration >= DEEP_WORK_THRESHOLD_SECONDS
                )

                cluster = TaskCluster(
                    sessions=window_sessions,
                    anchor_app=anchor_bundle_id,
                    anchor_app_name=anchor_name,
                    start_time=window_start,
                    end_time=actual_end,
                    total_duration=total_duration,
                    anchor_duration=anchor_duration,
                    support_apps=support_apps_sorted,
                    is_deep_work=is_deep_work,
                    cluster_type=cluster_type
                )

                clusters.append(cluster)

                # Skip ahead to avoid overlapping windows
                i = j
            else:
                i += 1

        return clusters

    def analyze_date(self, target_date: datetime) -> Dict:
        """
        Analyze all sessions for a given date and detect task clusters.

        Returns summary statistics and detected clusters.
        """
        from datetime import time

        # Get all sessions for the date
        start_time = datetime.combine(target_date, time(6, 0, 0))
        end_time = datetime.combine(target_date, time(22, 0, 0))

        sessions = self.db_session.query(Session).filter(
            Session.start_time >= start_time,
            Session.start_time < end_time
        ).order_by(Session.start_time).all()

        if not sessions:
            return {
                'date': target_date.date(),
                'total_sessions': 0,
                'task_clusters': [],
                'task_deep_work_sessions': 0,
                'traditional_deep_work_sessions': 0,
                'additional_deep_work_captured': 0
            }

        # Detect task clusters
        clusters = self._detect_task_clusters(sessions)

        # Count traditional deep work
        traditional_deep_work = sum(1 for s in sessions if s.is_deep_work)

        # Count task-based deep work
        task_deep_work = sum(1 for c in clusters if c.is_deep_work)

        # Calculate additional deep work captured
        # (sessions that wouldn't count as deep work individually)
        cluster_session_ids = set()
        for cluster in clusters:
            if cluster.is_deep_work:
                for session in cluster.sessions:
                    if not session.is_deep_work:
                        cluster_session_ids.add(session.id)

        additional_captured = len(cluster_session_ids)

        return {
            'date': target_date.date(),
            'total_sessions': len(sessions),
            'task_clusters': clusters,
            'task_deep_work_sessions': task_deep_work,
            'traditional_deep_work_sessions': traditional_deep_work,
            'additional_deep_work_captured': additional_captured,
            'total_deep_work_sessions': max(traditional_deep_work, task_deep_work)
        }

    def get_cluster_summary(self, cluster: TaskCluster) -> str:
        """Generate human-readable summary of a task cluster."""
        duration_min = cluster.total_duration / 60
        anchor_min = cluster.anchor_duration / 60
        anchor_pct = (cluster.anchor_duration / cluster.total_duration * 100) if cluster.total_duration > 0 else 0

        support_summary = ", ".join([
            f"{app} ({dur/60:.1f}m)"
            for app, dur in cluster.support_apps[:3]
        ])

        return (
            f"{cluster.cluster_type.upper()}: {duration_min:.1f}m total "
            f"({anchor_pct:.0f}% in {cluster.anchor_app_name})\n"
            f"  Anchor: {cluster.anchor_app_name} ({anchor_min:.1f}m)\n"
            f"  Support: {support_summary if support_summary else 'None'}\n"
            f"  Deep Work: {'✓' if cluster.is_deep_work else '✗'}"
        )

    def close(self):
        """Close database session."""
        if self.db_session:
            self.db_session.close()


def main():
    """Test the task cluster analyzer."""
    from datetime import date

    analyzer = TaskClusterAnalyzer()
    try:
        # Analyze today
        today = datetime.now()
        results = analyzer.analyze_date(today)

        print(f"\n📊 Task Cluster Analysis for {results['date']}")
        print(f"{'='*60}")
        print(f"Total sessions: {results['total_sessions']}")
        print(f"Traditional deep work: {results['traditional_deep_work_sessions']}")
        print(f"Task-based deep work: {results['task_deep_work_sessions']}")
        print(f"Additional sessions captured: {results['additional_deep_work_captured']}")
        print(f"\n🎯 Detected {len(results['task_clusters'])} task clusters:\n")

        for i, cluster in enumerate(results['task_clusters'], 1):
            print(f"{i}. {cluster.start_time.strftime('%I:%M %p')}")
            print(f"   {analyzer.get_cluster_summary(cluster)}\n")

    finally:
        analyzer.close()


if __name__ == '__main__':
    main()
