"""
SQLAlchemy ORM models for activity tracking database.
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Float, DateTime,
    Boolean, Text, ForeignKey, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
import os
from pathlib import Path

Base = declarative_base()


class Activity(Base):
    """Raw window capture events (every 3 seconds)."""
    __tablename__ = 'activities'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    app_bundle_id = Column(String(255), nullable=False, index=True)
    app_name = Column(String(255), nullable=False)
    window_title = Column(Text, nullable=True)  # NULL for sensitive apps
    is_sensitive = Column(Boolean, default=False)

    # For anonymized tracking
    window_title_hash = Column(String(64), nullable=True)  # SHA256 hash

    # For split screen detection
    visible_apps = Column(Text, nullable=True)  # JSON array of visible app names

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_timestamp_app', 'timestamp', 'app_bundle_id'),
    )


class Category(Base):
    """AI-driven activity categories."""
    __tablename__ = 'categories'

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    color_hex = Column(String(7))  # For visualization
    is_productive = Column(Boolean, default=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    sessions = relationship('Session', back_populates='category')


class Session(Base):
    """Aggregated activity sessions (5-minute grouping)."""
    __tablename__ = 'sessions'

    id = Column(Integer, primary_key=True)
    start_time = Column(DateTime, nullable=False, index=True)
    end_time = Column(DateTime, nullable=False)
    duration_seconds = Column(Float, nullable=False)

    app_bundle_id = Column(String(255), nullable=False, index=True)
    app_name = Column(String(255), nullable=False)
    window_title = Column(Text, nullable=True)  # Aggregated/representative title
    window_title_hash = Column(String(64), nullable=True)

    is_sensitive = Column(Boolean, default=False)
    is_rapid_switch = Column(Boolean, default=False)  # < 30 seconds
    is_deep_work = Column(Boolean, default=False)  # > 25 minutes
    is_split_screen = Column(Boolean, default=False)  # Multiple apps visible simultaneously

    # For split screen sessions
    visible_apps = Column(Text, nullable=True)  # JSON array of visible app names

    category_id = Column(Integer, ForeignKey('categories.id'), nullable=True, index=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    category = relationship('Category', back_populates='sessions')
    ai_categorization = relationship('AICategorization', back_populates='session', uselist=False)

    __table_args__ = (
        Index('idx_start_time_app', 'start_time', 'app_bundle_id'),
        Index('idx_category', 'category_id', 'start_time'),
    )


class AICategorization(Base):
    """AI categorization results with confidence scores."""
    __tablename__ = 'ai_categorizations'

    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey('sessions.id'), nullable=False, unique=True, index=True)
    category_id = Column(Integer, ForeignKey('categories.id'), nullable=False)

    confidence_score = Column(Float, nullable=False)  # 0.0 to 1.0
    reasoning = Column(Text)  # Why this category?

    # API tracking
    api_tokens_used = Column(Integer)
    api_cost_usd = Column(Float)
    cached = Column(Boolean, default=False)  # From prompt cache

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    session = relationship('Session', back_populates='ai_categorization')


class SensitiveApp(Base):
    """User-configured sensitive apps to exclude/anonymize."""
    __tablename__ = 'sensitive_apps'

    id = Column(Integer, primary_key=True)
    bundle_id = Column(String(255), unique=True, nullable=False, index=True)
    app_name = Column(String(255))

    # Sensitivity levels
    ANONYMIZE = 'anonymize'  # Hash window title
    EXCLUDE = 'exclude'      # Don't track at all

    sensitivity_level = Column(String(20), nullable=False, default=ANONYMIZE)

    # Pattern matching
    window_title_patterns = Column(Text)  # JSON array of regex patterns

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class AppSwitch(Base):
    """ADHD-specific tracking of context switches."""
    __tablename__ = 'app_switches'

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, nullable=False, index=True)

    from_app_bundle_id = Column(String(255), nullable=False)
    from_app_name = Column(String(255))
    from_duration_seconds = Column(Float)  # How long in previous app

    to_app_bundle_id = Column(String(255), nullable=False)
    to_app_name = Column(String(255))

    is_rapid = Column(Boolean, default=False)  # Previous session < 30s
    switch_count_in_minute = Column(Integer, default=1)  # Switches in rolling 1-min window

    created_at = Column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index('idx_timestamp_from', 'timestamp', 'from_app_bundle_id'),
    )


class DailyReport(Base):
    """Precomputed daily metrics for dashboard performance."""
    __tablename__ = 'daily_reports'

    id = Column(Integer, primary_key=True)
    date = Column(DateTime, nullable=False, unique=True, index=True)

    # Summary metrics
    total_tracked_seconds = Column(Float, default=0)
    total_sessions = Column(Integer, default=0)
    total_switches = Column(Integer, default=0)
    rapid_switches = Column(Integer, default=0)
    deep_work_sessions = Column(Integer, default=0)

    # Focus score (0-100)
    focus_score = Column(Float)

    # Top apps (JSON)
    top_apps_json = Column(Text)  # [{"app": "...", "duration": ...}, ...]
    category_breakdown_json = Column(Text)  # {"Work": 3600, "Entertainment": 1200, ...}

    # Best focus time
    best_focus_hour = Column(Integer)  # 0-23

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# Database initialization
def get_engine(db_path=None):
    """Create SQLAlchemy engine."""
    if db_path is None:
        db_path = os.getenv('DATABASE_PATH', 'data/activities.db')

    # Ensure directory exists
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(f'sqlite:///{db_path}', echo=False)
    return engine


def init_db(db_path=None):
    """Initialize database with all tables."""
    engine = get_engine(db_path)
    Base.metadata.create_all(engine)

    # Create default categories
    Session = sessionmaker(bind=engine)
    session = Session()

    default_categories = [
        {'name': 'Work', 'description': 'Professional work tasks', 'color_hex': '#3B82F6', 'is_productive': True},
        {'name': 'Communication', 'description': 'Email, messaging, meetings', 'color_hex': '#10B981', 'is_productive': True},
        {'name': 'Learning', 'description': 'Reading, courses, documentation', 'color_hex': '#8B5CF6', 'is_productive': True},
        {'name': 'Research', 'description': 'Web browsing for information', 'color_hex': '#06B6D4', 'is_productive': True},
        {'name': 'Creative', 'description': 'Design, writing, art', 'color_hex': '#F59E0B', 'is_productive': True},
        {'name': 'Entertainment', 'description': 'Videos, games, social media', 'color_hex': '#EF4444', 'is_productive': False},
        {'name': 'Social', 'description': 'Social media, forums', 'color_hex': '#EC4899', 'is_productive': False},
        {'name': 'Utilities', 'description': 'System tools, settings', 'color_hex': '#6B7280', 'is_productive': True},
    ]

    for cat_data in default_categories:
        existing = session.query(Category).filter_by(name=cat_data['name']).first()
        if not existing:
            category = Category(**cat_data)
            session.add(category)

    # Add default sensitive apps
    default_sensitive = [
        {'bundle_id': 'com.1password', 'app_name': '1Password', 'sensitivity_level': 'anonymize'},
        {'bundle_id': 'com.lastpass', 'app_name': 'LastPass', 'sensitivity_level': 'anonymize'},
        {'bundle_id': 'com.dashlane', 'app_name': 'Dashlane', 'sensitivity_level': 'anonymize'},
        {'bundle_id': 'com.bitwarden', 'app_name': 'Bitwarden', 'sensitivity_level': 'anonymize'},
        {'bundle_id': 'com.apple.KeychainAccess', 'app_name': 'Keychain Access', 'sensitivity_level': 'exclude'},
    ]

    for sensitive_data in default_sensitive:
        existing = session.query(SensitiveApp).filter_by(bundle_id=sensitive_data['bundle_id']).first()
        if not existing:
            sensitive_app = SensitiveApp(**sensitive_data)
            session.add(sensitive_app)

    session.commit()
    session.close()

    return engine


def get_session(db_path=None):
    """Get database session."""
    engine = get_engine(db_path)
    Session = sessionmaker(bind=engine)
    return Session()
