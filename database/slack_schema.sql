-- Slack tracking tables

-- Track Slack conversations (channels, DMs)
CREATE TABLE IF NOT EXISTS slack_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_name TEXT NOT NULL,
    conversation_type TEXT NOT NULL, -- 'channel', 'dm', 'activity_feed'
    workspace TEXT DEFAULT 'alpha-sense',
    last_viewed TIMESTAMP,
    view_count INTEGER DEFAULT 0,
    total_time_seconds REAL DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(conversation_name, workspace)
);

-- Track individual Slack views
CREATE TABLE IF NOT EXISTS slack_views (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    viewed_at TIMESTAMP NOT NULL,
    duration_seconds REAL NOT NULL,
    had_new_messages BOOLEAN DEFAULT FALSE,
    new_message_count INTEGER DEFAULT 0,
    FOREIGN KEY (conversation_id) REFERENCES slack_conversations(id)
);

-- Track important people (like manager)
CREATE TABLE IF NOT EXISTS slack_important_people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_identifier TEXT NOT NULL UNIQUE, -- name or pattern to match
    label TEXT NOT NULL, -- e.g., 'Manager', 'Direct Report', 'Executive'
    alert_on_new_messages BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_slack_views_time ON slack_views(viewed_at);
CREATE INDEX IF NOT EXISTS idx_slack_conversations_last_viewed ON slack_conversations(last_viewed);
