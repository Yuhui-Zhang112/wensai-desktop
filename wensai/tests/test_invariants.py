"""Verify storage and database guarantees against disposable local fixtures."""
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from uuid import uuid4

from app.config import Settings
from app.db import session


ROOT = Path(__file__).resolve().parents[1]


class Invariants(unittest.TestCase):
    def test_production_pins_ipv4_loopback(self):
        settings = Settings(environment="production", host="0.0.0.0", cors_origins=("*",))
        self.assertEqual(settings.host, "127.0.0.1")
        self.assertFalse(settings.cors_origins)

    def test_repeatable_migration_and_wal(self):
        expected = {"projects", "materials", "material_versions", "files", "tasks", "task_events",
                    "review_profiles", "review_runs", "review_findings", "suggestions", "settings"}
        with tempfile.TemporaryDirectory() as temp:
            db = Path(temp) / "custom" / "local.db"
            for _ in range(2):
                run = subprocess.run(
                    [sys.executable, "-m", "app.db", "--db", str(db)], cwd=ROOT, capture_output=True,
                    env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, timeout=15,
                )
                self.assertEqual(run.returncode, 0, run.stderr.decode(errors="replace"))
            with session(db) as connection:
                self.assertEqual(connection.execute("PRAGMA journal_mode").fetchone()[0], "wal")
                self.assertEqual(connection.execute("PRAGMA foreign_keys").fetchone()[0], 1)
                self.assertGreaterEqual(connection.execute("PRAGMA user_version").fetchone()[0], 1)
                tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                self.assertTrue(expected <= tables, expected - tables)
                for table in expected:
                    columns = {r["name"] for r in connection.execute(f"PRAGMA table_info({table})")}
                    self.assertTrue({"id", "created_at", "updated_at"} <= columns, table)
                self.assertEqual(connection.execute("SELECT count(*) FROM review_profiles WHERE id='default'").fetchone()[0], 1)
                with self.assertRaises(sqlite3.IntegrityError):
                    connection.execute("INSERT INTO materials (id,project_id,name) VALUES ('m','missing','test')")

    def test_cleanup_refuses_path_outside_own_project(self):
        from app.storage import safe_unlink
        from app.common import ApiError

        with tempfile.TemporaryDirectory() as temp:
            file_root = Path(temp) / "projects"
            project = str(uuid4())
            own = file_root / project / "working"
            own.mkdir(parents=True)
            other_project = str(uuid4())
            other = file_root / other_project / "raw"
            other.mkdir(parents=True)
            sentinel = other / "fixture.txt"
            sentinel.write_text("保留", encoding="utf-8")
            for wrong in (str(sentinel.resolve()), f"../{other_project}/raw/fixture.txt"):
                with self.subTest(path=wrong), self.assertRaises(ApiError):
                    safe_unlink(file_root, project, wrong)
                self.assertEqual(sentinel.read_text(encoding="utf-8"), "保留")


if __name__ == "__main__":
    unittest.main()
