-- Add visible_apps column to activities table for split screen detection
-- This stores a JSON array of all visible apps at the time of activity capture

ALTER TABLE activities ADD COLUMN visible_apps TEXT;  -- JSON array of app names

-- Add index for better query performance
CREATE INDEX IF NOT EXISTS idx_activities_visible_apps ON activities(visible_apps);

-- Add multi_app flag to sessions table
ALTER TABLE sessions ADD COLUMN is_split_screen BOOLEAN DEFAULT FALSE;
ALTER TABLE sessions ADD COLUMN visible_apps TEXT;  -- JSON array for the session

CREATE INDEX IF NOT EXISTS idx_sessions_split_screen ON sessions(is_split_screen);
