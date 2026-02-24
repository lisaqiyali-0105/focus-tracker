"""
Flask web dashboard for activity visualization.
"""
import sys
import os
from pathlib import Path

# Add project root to Python path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from flask import Flask, jsonify, render_template, request
from flask_cors import CORS
from datetime import datetime, timedelta
from sqlalchemy import func, and_, text

from database.models import (
    Session, Category, AppSwitch,
    get_session, get_engine
)
from tracker.task_cluster_analyzer import TaskClusterAnalyzer
from config.logging import setup_logging
from config.settings import FLASK_HOST, FLASK_PORT, FLASK_DEBUG

logger = setup_logging('dashboard')

app = Flask(__name__)
CORS(app)

# Working hours configuration (6 AM - 10 PM)
WORK_START_HOUR = 6
WORK_END_HOUR = 22  # 10 PM

def get_working_hours_range(target_date):
    """Get datetime range for working hours (6 AM - 10 PM) on a given date."""
    from datetime import time
    start_time = datetime.combine(target_date, time(WORK_START_HOUR, 0, 0))
    end_time = datetime.combine(target_date, time(WORK_END_HOUR, 0, 0))
    return start_time, end_time

# Initialize database
get_engine()


def get_db():
    """Get database session."""
    return get_session()


def _parse_target_date(date_str=None):
    """Parse a YYYY-MM-DD date string, defaulting to today."""
    if date_str:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    return datetime.utcnow().date()


@app.route('/')
def index():
    """Serve main dashboard page."""
    return render_template('index.html')


@app.route('/simple')
def simple():
    """Serve simple test page."""
    return render_template('simple.html')


@app.route('/style/pastel')
def style_pastel():
    """Serve pastel minimalist style dashboard."""
    return render_template('style_pastel.html')


@app.route('/style/glass')
def style_glass():
    """Serve glassmorphism style dashboard."""
    return render_template('style_glass.html')


@app.route('/style/neo')
def style_neo():
    """Serve neo-brutalist style dashboard."""
    return render_template('style_neo.html')


@app.route('/styles')
def styles_index():
    """Serve styles preview page."""
    return render_template('styles_index.html')


@app.route('/api/overview')
def overview():
    """Get daily overview statistics.

    Query params:
        date: YYYY-MM-DD (default: today)
    """
    db = get_db()
    try:
        target_date = _parse_target_date(request.args.get('date'))
        start_time, end_time = get_working_hours_range(target_date)

        # Get sessions for the day
        sessions = db.query(Session).filter(
            and_(
                Session.start_time >= start_time,
                Session.start_time <= end_time
            )
        ).all()

        # Calculate metrics
        total_tracked = sum(s.duration_seconds for s in sessions)
        total_sessions = len(sessions)
        rapid_switches = sum(1 for s in sessions if s.is_rapid_switch)
        deep_work_sessions = sum(1 for s in sessions if s.is_deep_work)
        split_screen_sessions = sum(1 for s in sessions if s.is_split_screen)
        split_screen_time = sum(s.duration_seconds for s in sessions if s.is_split_screen)

        # Get app switches
        switches = db.query(AppSwitch).filter(
            and_(
                AppSwitch.timestamp >= start_time,
                AppSwitch.timestamp <= end_time
            )
        ).count()

        # Analyze task clusters
        analyzer = TaskClusterAnalyzer(db)
        cluster_analysis = analyzer.analyze_date(datetime.combine(target_date, datetime.min.time()))

        task_deep_work = cluster_analysis['task_deep_work_sessions']
        additional_captured = cluster_analysis['additional_deep_work_captured']

        # Use task-based deep work for focus score (more accurate)
        effective_deep_work = max(deep_work_sessions, task_deep_work)

        # Calculate focus score
        focus_score = _calculate_focus_score(
            total_tracked, switches, rapid_switches, total_sessions
        )

        return jsonify({
            'date': target_date.isoformat(),
            'total_tracked_seconds': total_tracked,
            'total_tracked_hours': round(total_tracked / 3600, 2),
            'total_sessions': total_sessions,
            'total_switches': switches,
            'rapid_switches': rapid_switches,
            'deep_work_sessions': deep_work_sessions,
            'task_deep_work_sessions': task_deep_work,
            'effective_deep_work_sessions': effective_deep_work,
            'additional_sessions_captured': additional_captured,
            'split_screen_sessions': split_screen_sessions,
            'split_screen_hours': round(split_screen_time / 3600, 2),
            'focus_score': focus_score
        })

    finally:
        db.close()


@app.route('/api/categories/summary')
def categories_summary():
    """Get time breakdown by category.

    Query params:
        date: YYYY-MM-DD (default: today)
    """
    db = get_db()
    try:
        target_date = _parse_target_date(request.args.get('date'))
        start_time, end_time = get_working_hours_range(target_date)

        # Query category breakdown
        results = db.query(
            Category.name,
            Category.color_hex,
            Category.is_productive,
            func.sum(Session.duration_seconds).label('total_seconds'),
            func.count(Session.id).label('session_count')
        ).join(
            Session, Session.category_id == Category.id
        ).filter(
            and_(
                Session.start_time >= start_time,
                Session.start_time <= end_time
            )
        ).group_by(Category.id).all()

        categories = []
        for name, color, is_productive, total_seconds, session_count in results:
            categories.append({
                'name': name,
                'color': color,
                'is_productive': is_productive,
                'total_seconds': total_seconds or 0,
                'total_hours': round((total_seconds or 0) / 3600, 2),
                'session_count': session_count or 0
            })

        # Sort by total time
        categories.sort(key=lambda x: x['total_seconds'], reverse=True)

        return jsonify({'categories': categories})

    finally:
        db.close()


@app.route('/api/sessions')
def sessions():
    """Get detailed session list.

    Query params:
        date: YYYY-MM-DD (default: today)
        limit: max number of sessions (default: 100)
    """
    db = get_db()
    try:
        target_date = _parse_target_date(request.args.get('date'))
        limit = int(request.args.get('limit', 100))

        start_time, end_time = get_working_hours_range(target_date)

        # Query sessions
        query = db.query(Session, Category).outerjoin(
            Category, Session.category_id == Category.id
        ).filter(
            and_(
                Session.start_time >= start_time,
                Session.start_time <= end_time
            )
        ).order_by(Session.start_time.desc()).limit(limit)

        session_list = []
        for session, category in query:
            # Enhanced session type detection
            duration = session.duration_seconds

            # Organizational: tidying, cleanup
            is_organizational = False
            if 30 < duration < 240 and session.window_title:
                title_lower = session.window_title.lower()
                org_keywords = ['untitled', 'new tab', 'tabs', 'downloads', 'settings', 'preferences', 'bookmark']
                is_organizational = any(keyword in title_lower for keyword in org_keywords)

            # Task-based: multi-app workflow
            is_task_based = (
                60 < duration < 600 and  # 1-10 minutes
                not session.is_rapid_switch and
                not is_organizational
            )

            # Focus session: sustained work
            is_focus = duration >= 300 and not session.is_deep_work  # 5-25 min

            session_list.append({
                'id': session.id,
                'start_time': session.start_time.isoformat(),
                'end_time': session.end_time.isoformat(),
                'duration_seconds': session.duration_seconds,
                'duration_minutes': round(session.duration_seconds / 60, 1),
                'app_name': session.app_name,
                'app_bundle_id': session.app_bundle_id,
                'window_title': session.window_title or '[sensitive]' if session.is_sensitive else session.window_title,
                'category': category.name if category else 'Uncategorized',
                'category_color': category.color_hex if category else '#9CA3AF',
                'is_rapid_switch': session.is_rapid_switch,
                'is_deep_work': session.is_deep_work,
                'is_sensitive': session.is_sensitive,
                'is_organizational': is_organizational,
                'is_task_based': is_task_based,
                'is_focus': is_focus,
                'is_split_screen': session.is_split_screen,
                'visible_apps': session.visible_apps
            })

        return jsonify({'sessions': session_list})

    finally:
        db.close()


@app.route('/api/focus/analysis')
def focus_analysis():
    """Get ADHD-specific focus analysis metrics.

    Query params:
        date: YYYY-MM-DD (default: today)
    """
    db = get_db()
    try:
        target_date = _parse_target_date(request.args.get('date'))
        start_time, end_time = get_working_hours_range(target_date)

        # Get sessions
        sessions = db.query(Session).filter(
            and_(
                Session.start_time >= start_time,
                Session.start_time <= end_time
            )
        ).order_by(Session.start_time).all()

        # Calculate app diversity (unique apps)
        unique_apps = len(set(s.app_bundle_id for s in sessions))

        # Get hourly focus distribution (in local time)
        hourly_focus = {}
        for session in sessions:
            # Session times are stored in UTC, convert to local
            local_time = session.start_time
            hour = local_time.hour
            if hour not in hourly_focus:
                hourly_focus[hour] = 0
            hourly_focus[hour] += session.duration_seconds

        # Find best focus hour
        best_hour = max(hourly_focus.items(), key=lambda x: x[1])[0] if hourly_focus else None

        # Calculate average session duration
        avg_duration = sum(s.duration_seconds for s in sessions) / len(sessions) if sessions else 0

        # Get timezone info
        from datetime import timezone
        import time
        local_tz_offset = -time.timezone if time.daylight == 0 else -time.altzone
        local_tz_hours = local_tz_offset // 3600
        tz_name = time.tzname[time.daylight]

        return jsonify({
            'unique_apps': unique_apps,
            'average_session_duration_seconds': avg_duration,
            'average_session_duration_minutes': round(avg_duration / 60, 1),
            'best_focus_hour': best_hour,
            'timezone': tz_name,
            'timezone_offset': local_tz_hours,
            'hourly_distribution': [
                {'hour': hour, 'seconds': seconds}
                for hour, seconds in sorted(hourly_focus.items())
            ]
        })

    finally:
        db.close()


@app.route('/api/switches')
def switches():
    """Get app switching patterns.

    Query params:
        date: YYYY-MM-DD (default: today)
        rapid_only: true/false (default: false)
    """
    db = get_db()
    try:
        target_date = _parse_target_date(request.args.get('date'))
        rapid_only = request.args.get('rapid_only', 'false').lower() == 'true'

        start_time, end_time = get_working_hours_range(target_date)

        # Query switches
        query = db.query(AppSwitch).filter(
            and_(
                AppSwitch.timestamp >= start_time,
                AppSwitch.timestamp <= end_time
            )
        )

        if rapid_only:
            query = query.filter(AppSwitch.is_rapid == True)

        switches_list = []
        for switch in query.order_by(AppSwitch.timestamp).all():
            switches_list.append({
                'timestamp': switch.timestamp.isoformat(),
                'from_app': switch.from_app_name,
                'to_app': switch.to_app_name,
                'from_duration_seconds': switch.from_duration_seconds,
                'from_duration_minutes': round(switch.from_duration_seconds / 60, 1),
                'is_rapid': switch.is_rapid,
                'switch_count_in_minute': switch.switch_count_in_minute
            })

        return jsonify({'switches': switches_list})

    finally:
        db.close()


@app.route('/api/top-apps')
def top_apps():
    """Get top apps by time spent.

    Query params:
        date: YYYY-MM-DD (default: today)
        limit: number of apps (default: 5)
    """
    db = get_db()
    try:
        target_date = _parse_target_date(request.args.get('date'))
        limit = int(request.args.get('limit', 5))

        start_time, end_time = get_working_hours_range(target_date)

        # Query top apps
        results = db.query(
            Session.app_name,
            Session.app_bundle_id,
            func.sum(Session.duration_seconds).label('total_seconds'),
            func.count(Session.id).label('session_count')
        ).filter(
            and_(
                Session.start_time >= start_time,
                Session.start_time <= end_time
            )
        ).group_by(Session.app_bundle_id).order_by(
            func.sum(Session.duration_seconds).desc()
        ).limit(limit).all()

        apps = []
        for app_name, bundle_id, total_seconds, session_count in results:
            apps.append({
                'app_name': app_name,
                'bundle_id': bundle_id,
                'total_seconds': total_seconds,
                'total_hours': round(total_seconds / 3600, 2),
                'session_count': session_count
            })

        return jsonify({'apps': apps})

    finally:
        db.close()


def _calculate_focus_score(total_seconds, total_switches, rapid_switches, total_sessions):
    """Calculate focus score (0-100) based on signals that actually have data.

    Components:
      - Hours tracked    (50 pts): rewards getting work done; maxes out at 8h
      - Rapid switch ratio (30 pts): penalises micro-context-switches (<30s)
      - Switches per hour  (20 pts): rewards steady rhythm; 60+/hr = 0 pts
    """
    if total_sessions == 0:
        return 0

    hours_tracked = total_seconds / 3600

    # Hours tracked (50 pts) — dominant signal
    hours_score = min(hours_tracked / 8.0 * 50, 50)

    # Rapid switch ratio (30 pts)
    rapid_ratio = rapid_switches / total_sessions
    rapid_score = max(30 * (1 - rapid_ratio), 0)

    # Switches per hour (20 pts) — 60/hr = 0 pts, 0/hr = 20 pts
    switches_per_hour = total_switches / hours_tracked if hours_tracked > 0 else 0
    rhythm_score = max(20 * (1 - switches_per_hour / 60.0), 0)

    return round(hours_score + rapid_score + rhythm_score, 1)


@app.route('/api/slack/summary')
def slack_summary():
    """Get Slack activity summary."""
    db = get_session()
    try:
        target_date = _parse_target_date(request.args.get('date'))
        start_time, end_time = get_working_hours_range(target_date)

        # Get conversations viewed today
        result = db.execute(text("""
            SELECT
                sc.conversation_name,
                sc.conversation_type,
                COUNT(sv.id) as view_count,
                SUM(sv.duration_seconds) as total_seconds,
                MAX(sv.viewed_at) as last_viewed,
                MAX(sv.new_message_count) as max_new_messages
            FROM slack_conversations sc
            JOIN slack_views sv ON sc.id = sv.conversation_id
            WHERE sv.viewed_at BETWEEN :start_time AND :end_time
            GROUP BY sc.id
            ORDER BY last_viewed DESC
        """), {'start_time': start_time, 'end_time': end_time})

        conversations = []
        for row in result:
            last_viewed = row[4]
            if isinstance(last_viewed, str):
                last_viewed_str = last_viewed
            elif last_viewed:
                last_viewed_str = last_viewed.isoformat()
            else:
                last_viewed_str = None

            conversations.append({
                'name': row[0],
                'type': row[1],
                'view_count': row[2],
                'total_seconds': float(row[3]),
                'total_minutes': round(float(row[3]) / 60, 1),
                'last_viewed': last_viewed_str,
                'had_new_messages': row[5] > 0 if row[5] else False
            })

        return jsonify({
            'date': target_date.isoformat(),
            'conversations': conversations,
            'total_conversations': len(conversations)
        })

    except Exception as e:
        logger.error(f"Error in slack_summary: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/api/slack/piecemeal')
def slack_piecemeal():
    """Get piecemeal messaging patterns (same conversation viewed multiple times in short window)."""
    from tracker.slack_analytics import SlackAnalytics

    try:
        target_date = _parse_target_date(request.args.get('date'))

        # Get important people filter (comma-separated)
        important_people_str = request.args.get('important_people', '')
        important_people = [p.strip() for p in important_people_str.split(',') if p.strip()]

        analytics = SlackAnalytics()
        patterns = analytics.get_piecemeal_message_patterns(
            target_date,
            important_people=important_people if important_people else None
        )
        analytics.close()

        return jsonify({
            'date': target_date.isoformat(),
            'piecemeal_patterns': patterns,
            'total_patterns': len(patterns)
        })

    except Exception as e:
        logger.error(f"Error in slack_piecemeal: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/slack/switching')
def slack_switching():
    """Get context switching cost metrics."""
    from tracker.slack_analytics import SlackAnalytics

    try:
        target_date = _parse_target_date(request.args.get('date'))

        analytics = SlackAnalytics()
        metrics = analytics.get_context_switching_cost(target_date)
        analytics.close()

        return jsonify({
            'date': target_date.isoformat(),
            'switching_metrics': metrics
        })

    except Exception as e:
        logger.error(f"Error in slack_switching: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/slack/response-times')
def slack_response_times():
    """Get response time patterns for conversations with new messages."""
    from tracker.slack_analytics import SlackAnalytics

    try:
        target_date = _parse_target_date(request.args.get('date'))

        # Get important people filter
        important_people_str = request.args.get('important_people', '')
        important_people = [p.strip() for p in important_people_str.split(',') if p.strip()]

        analytics = SlackAnalytics()
        patterns = analytics.get_response_time_patterns(
            target_date,
            important_people=important_people if important_people else None
        )
        analytics.close()

        return jsonify({
            'date': target_date.isoformat(),
            'response_patterns': patterns
        })

    except Exception as e:
        logger.error(f"Error in slack_response_times: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/slack/unread-important')
def slack_unread_important():
    """Get important conversations that haven't been checked recently."""
    from tracker.slack_analytics import SlackAnalytics

    try:
        # Get important people filter (required)
        important_people_str = request.args.get('important_people', '')
        if not important_people_str:
            return jsonify({'error': 'important_people parameter required'}), 400

        important_people = [p.strip() for p in important_people_str.split(',') if p.strip()]

        analytics = SlackAnalytics()
        conversations = analytics.get_unread_important_conversations(important_people)
        analytics.close()

        return jsonify({
            'important_conversations': conversations,
            'total_count': len(conversations)
        })

    except Exception as e:
        logger.error(f"Error in slack_unread_important: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/task-clusters')
def task_clusters():
    """Get task cluster analysis for a date.

    Query params:
        date: YYYY-MM-DD (default: today)

    Returns detected task clusters with anchor apps and deep work status.
    """
    db = get_db()
    try:
        target_date = _parse_target_date(request.args.get('date'))

        # Run task cluster analysis
        analyzer = TaskClusterAnalyzer(db)
        results = analyzer.analyze_date(datetime.combine(target_date, datetime.min.time()))

        # Format clusters for JSON
        clusters_json = []
        for cluster in results['task_clusters']:
            support_apps = [
                {
                    'app_name': app_name,
                    'duration_seconds': duration,
                    'duration_minutes': round(duration / 60, 1)
                }
                for app_name, duration in cluster.support_apps
            ]

            clusters_json.append({
                'start_time': cluster.start_time.isoformat(),
                'end_time': cluster.end_time.isoformat(),
                'total_duration_seconds': cluster.total_duration,
                'total_duration_minutes': round(cluster.total_duration / 60, 1),
                'anchor_app': cluster.anchor_app_name,
                'anchor_duration_seconds': cluster.anchor_duration,
                'anchor_duration_minutes': round(cluster.anchor_duration / 60, 1),
                'anchor_percentage': round(cluster.anchor_duration / cluster.total_duration * 100, 1) if cluster.total_duration > 0 else 0,
                'support_apps': support_apps,
                'num_sessions': len(cluster.sessions),
                'cluster_type': cluster.cluster_type,
                'is_deep_work': cluster.is_deep_work
            })

        return jsonify({
            'date': results['date'].isoformat(),
            'total_sessions': results['total_sessions'],
            'task_clusters': clusters_json,
            'task_deep_work_sessions': results['task_deep_work_sessions'],
            'traditional_deep_work_sessions': results['traditional_deep_work_sessions'],
            'additional_deep_work_captured': results['additional_deep_work_captured'],
            'total_deep_work_sessions': results['total_deep_work_sessions']
        })

    except Exception as e:
        logger.error(f"Error in task_clusters: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        db.close()


@app.route('/weekly')
def weekly():
    """Serve weekly summary dashboard."""
    return render_template('weekly.html')


@app.route('/api/weekly')
def weekly_overview():
    """Get weekly overview — 7 days of aggregated metrics.

    Query params:
        week_start: YYYY-MM-DD (default: 7 days ago)
    """
    db = get_db()
    try:
        week_start_str = request.args.get('week_start')
        if week_start_str:
            week_start = datetime.strptime(week_start_str, '%Y-%m-%d').date()
        else:
            week_start = (_parse_target_date() - timedelta(days=6))

        days = []
        for i in range(7):
            target_date = week_start + timedelta(days=i)
            start_time, end_time = get_working_hours_range(target_date)

            sessions = db.query(Session).filter(
                and_(
                    Session.start_time >= start_time,
                    Session.start_time <= end_time
                )
            ).all()

            switches = db.query(AppSwitch).filter(
                and_(
                    AppSwitch.timestamp >= start_time,
                    AppSwitch.timestamp <= end_time
                )
            ).count()

            total_seconds = sum(s.duration_seconds for s in sessions)
            total_sessions = len(sessions)
            rapid_switches = sum(1 for s in sessions if s.is_rapid_switch)
            deep_work = sum(1 for s in sessions if s.is_deep_work)
            focus_score = _calculate_focus_score(total_seconds, switches, rapid_switches, total_sessions)

            days.append({
                'date': target_date.isoformat(),
                'day_name': target_date.strftime('%a'),
                'total_tracked_seconds': total_seconds,
                'total_tracked_hours': round(total_seconds / 3600, 2),
                'focus_score': focus_score,
                'deep_work_sessions': deep_work,
                'rapid_switches': rapid_switches,
                'total_switches': switches,
                'total_sessions': total_sessions
            })

        # Weekly aggregates
        week_end = week_start + timedelta(days=6)
        week_start_dt, _ = get_working_hours_range(week_start)
        _, week_end_dt = get_working_hours_range(week_end)

        # Top apps for the week
        top_apps_results = db.query(
            Session.app_name,
            func.sum(Session.duration_seconds).label('total_seconds'),
            func.count(Session.id).label('session_count')
        ).filter(
            and_(
                Session.start_time >= week_start_dt,
                Session.start_time <= week_end_dt
            )
        ).group_by(Session.app_bundle_id).order_by(
            func.sum(Session.duration_seconds).desc()
        ).limit(7).all()

        top_apps = [
            {
                'app_name': app_name,
                'total_seconds': total_seconds,
                'total_hours': round(total_seconds / 3600, 2),
                'session_count': session_count
            }
            for app_name, total_seconds, session_count in top_apps_results
        ]

        # Category breakdown for the week
        cat_results = db.query(
            Category.name,
            Category.color_hex,
            Category.is_productive,
            func.sum(Session.duration_seconds).label('total_seconds')
        ).join(
            Session, Session.category_id == Category.id
        ).filter(
            and_(
                Session.start_time >= week_start_dt,
                Session.start_time <= week_end_dt
            )
        ).group_by(Category.id).order_by(
            func.sum(Session.duration_seconds).desc()
        ).all()

        categories = [
            {
                'name': name,
                'color': color,
                'is_productive': is_productive,
                'total_hours': round((total_seconds or 0) / 3600, 2)
            }
            for name, color, is_productive, total_seconds in cat_results
        ]

        # Previous week comparison
        prev_week_start = week_start - timedelta(days=7)
        prev_week_end = prev_week_start + timedelta(days=6)
        prev_start_dt, _ = get_working_hours_range(prev_week_start)
        _, prev_end_dt = get_working_hours_range(prev_week_end)

        prev_sessions = db.query(Session).filter(
            and_(
                Session.start_time >= prev_start_dt,
                Session.start_time <= prev_end_dt
            )
        ).all()

        prev_total_seconds = sum(s.duration_seconds for s in prev_sessions)
        prev_rapid = sum(1 for s in prev_sessions if s.is_rapid_switch)
        prev_switches = db.query(AppSwitch).filter(
            and_(
                AppSwitch.timestamp >= prev_start_dt,
                AppSwitch.timestamp <= prev_end_dt
            )
        ).count()
        prev_focus = _calculate_focus_score(prev_total_seconds, prev_switches, prev_rapid, len(prev_sessions))

        # Best day
        active_days = [d for d in days if d['total_tracked_hours'] >= 2]
        best_day = max(active_days, key=lambda d: d['focus_score']) if active_days else None

        week_total_seconds = sum(d['total_tracked_seconds'] for d in days)
        week_avg_focus = round(
            sum(d['focus_score'] for d in active_days) / len(active_days), 1
        ) if active_days else 0
        week_total_deep_work = sum(d['deep_work_sessions'] for d in days)

        return jsonify({
            'week_start': week_start.isoformat(),
            'week_end': week_end.isoformat(),
            'days': days,
            'top_apps': top_apps,
            'categories': categories,
            'summary': {
                'total_hours': round(week_total_seconds / 3600, 2),
                'avg_focus_score': week_avg_focus,
                'total_deep_work_sessions': week_total_deep_work,
                'active_days': len(active_days),
                'best_day': best_day
            },
            'vs_last_week': {
                'prev_total_hours': round(prev_total_seconds / 3600, 2),
                'prev_avg_focus': prev_focus,
                'hours_delta': round((week_total_seconds - prev_total_seconds) / 3600, 2),
                'focus_delta': round(week_avg_focus - prev_focus, 1),
            }
        })

    finally:
        db.close()


def main():
    """Run Flask development server."""
    logger.info(f"Starting dashboard on {FLASK_HOST}:{FLASK_PORT}")
    app.run(host=FLASK_HOST, port=FLASK_PORT, debug=FLASK_DEBUG)


if __name__ == '__main__':
    main()
