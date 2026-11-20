ALTER TABLE projects ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
ALTER TABLE materials ADD COLUMN archived INTEGER NOT NULL DEFAULT 0;
CREATE TABLE desktop_tasks (
 id TEXT PRIMARY KEY, material_id TEXT NOT NULL REFERENCES materials(id),
 version_id TEXT NOT NULL REFERENCES material_versions(id), profile TEXT NOT NULL,
 provider TEXT NOT NULL CHECK(provider IN ('mock','deepseek')),
 status TEXT NOT NULL, snapshot_json TEXT NOT NULL, result_json TEXT,
 decisions_json TEXT NOT NULL DEFAULT '{}', error TEXT, meta_json TEXT,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE desktop_events (
 task_id TEXT NOT NULL REFERENCES desktop_tasks(id), seq INTEGER NOT NULL,
 status TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(task_id,seq)
);
CREATE TABLE desktop_audits (
 id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES desktop_tasks(id),
 record_json TEXT NOT NULL, created_at TEXT NOT NULL
);
