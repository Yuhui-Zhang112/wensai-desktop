ALTER TABLE desktop_tasks ADD COLUMN execution_mode TEXT NOT NULL DEFAULT 'pipeline';
ALTER TABLE desktop_tasks ADD COLUMN goal TEXT NOT NULL DEFAULT '';
ALTER TABLE desktop_tasks ADD COLUMN parent_task_id TEXT REFERENCES desktop_tasks(id);
ALTER TABLE desktop_tasks ADD COLUMN intent_digest TEXT;
ALTER TABLE desktop_tasks ADD COLUMN agent_context TEXT NOT NULL DEFAULT '';
ALTER TABLE desktop_tasks ADD COLUMN agent_answer TEXT;
ALTER TABLE desktop_tasks ADD COLUMN termination TEXT;
CREATE TABLE agent_steps (
 task_id TEXT NOT NULL REFERENCES desktop_tasks(id), seq INTEGER NOT NULL,
 action TEXT NOT NULL, status TEXT NOT NULL, label TEXT NOT NULL,
 observation_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(task_id,seq)
);
