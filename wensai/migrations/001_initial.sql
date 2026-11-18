-- 应用通过 app.db.initialize 在写事务中执行本目录内的连续编号迁移。
CREATE TABLE projects (
    id TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE materials (
    id TEXT NOT NULL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX materials_by_project ON materials(project_id, created_at);

CREATE TABLE files (
    id TEXT NOT NULL PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    relative_path TEXT NOT NULL CHECK (length(relative_path) > 0),
    original_name TEXT NOT NULL,
    mime_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
    sha256 TEXT NOT NULL CHECK (length(sha256) = 64 AND sha256 NOT GLOB '*[^0-9a-f]*'),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(project_id, relative_path)
);

CREATE TABLE material_versions (
    id TEXT NOT NULL PRIMARY KEY,
    material_id TEXT NOT NULL REFERENCES materials(id),
    file_id TEXT NOT NULL REFERENCES files(id),
    version_no INTEGER NOT NULL CHECK (version_no >= 1),
    parent_version_id TEXT REFERENCES material_versions(id),
    change_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(material_id, version_no),
    CHECK ((version_no = 1 AND parent_version_id IS NULL)
        OR (version_no > 1 AND parent_version_id IS NOT NULL))
);
CREATE INDEX versions_by_file ON material_versions(file_id);
CREATE INDEX versions_by_parent ON material_versions(parent_version_id);
CREATE TRIGGER version_ownership BEFORE INSERT ON material_versions
WHEN (SELECT project_id FROM files WHERE id = NEW.file_id) <>
     (SELECT project_id FROM materials WHERE id = NEW.material_id)
  OR (NEW.parent_version_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM material_versions
        WHERE id = NEW.parent_version_id AND material_id = NEW.material_id
          AND version_no < NEW.version_no
    ))
BEGIN
    SELECT RAISE(ABORT, 'invalid version lineage');
END;

CREATE TABLE review_profiles (
    id TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
INSERT INTO review_profiles(id, name) VALUES ('default', '通用竞赛文档演示');

CREATE TABLE tasks (
    id TEXT NOT NULL PRIMARY KEY,
    material_version_id TEXT NOT NULL REFERENCES material_versions(id),
    profile_id TEXT NOT NULL DEFAULT 'default' REFERENCES review_profiles(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN (
        'pending','queued','running','completed','failed','cancelling','cancelled'
    )),
    attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX tasks_by_status ON tasks(status, created_at, id);
CREATE INDEX tasks_by_version ON tasks(material_version_id);
CREATE INDEX tasks_by_profile ON tasks(profile_id);
CREATE TRIGGER task_initial_status BEFORE INSERT ON tasks
WHEN NEW.status <> 'pending'
BEGIN
    SELECT RAISE(ABORT, 'invalid initial task status');
END;
CREATE TRIGGER task_status_transition BEFORE UPDATE OF status ON tasks
WHEN OLD.status <> NEW.status AND NOT (
    (OLD.status = 'pending' AND NEW.status = 'queued') OR
    (OLD.status = 'queued' AND NEW.status = 'running') OR
    (OLD.status = 'running' AND NEW.status IN ('completed','failed','cancelling')) OR
    (OLD.status = 'cancelling' AND NEW.status = 'cancelled') OR
    (OLD.status IN ('failed','cancelled') AND NEW.status = 'queued')
)
BEGIN
    SELECT RAISE(ABORT, 'invalid task status transition');
END;

CREATE TABLE task_events (
    id TEXT NOT NULL PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    seq INTEGER NOT NULL CHECK (seq >= 1),
    status TEXT NOT NULL CHECK (status IN (
        'pending','queued','running','completed','failed','cancelling','cancelled'
    )),
    message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    UNIQUE(task_id, seq)
);
CREATE TRIGGER event_sequence BEFORE INSERT ON task_events
WHEN NEW.seq <> (SELECT coalesce(max(seq),0) + 1 FROM task_events WHERE task_id = NEW.task_id)
BEGIN
    SELECT RAISE(ABORT, 'invalid event sequence');
END;

CREATE TABLE review_runs (
    id TEXT NOT NULL PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES tasks(id),
    overall_score REAL NOT NULL CHECK (overall_score >= 0 AND overall_score <= 100),
    summary TEXT NOT NULL,
    dimensions_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);

CREATE TABLE review_findings (
    id TEXT NOT NULL PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES review_runs(id),
    category TEXT NOT NULL,
    severity TEXT NOT NULL,
    location TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX findings_by_run ON review_findings(run_id);

CREATE TABLE suggestions (
    id TEXT NOT NULL PRIMARY KEY,
    finding_id TEXT NOT NULL REFERENCES review_findings(id),
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX suggestions_by_finding ON suggestions(finding_id);

CREATE TABLE settings (
    id TEXT NOT NULL PRIMARY KEY,
    key TEXT NOT NULL UNIQUE,
    value_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
    updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
