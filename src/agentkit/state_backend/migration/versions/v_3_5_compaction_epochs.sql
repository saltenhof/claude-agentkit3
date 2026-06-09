CREATE TABLE IF NOT EXISTS compaction_epochs (
    project_key TEXT NOT NULL,
    story_id TEXT NOT NULL,
    epoch INTEGER NOT NULL DEFAULT 0,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_key, story_id)
);
