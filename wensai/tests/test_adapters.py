"""Exercise the integration contract through the API, including the actual worker and SQLite."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
import tempfile
import unittest

import httpx

from app.config import Settings
from app.db import session
from app.main import create_app


SAMPLE = Path(__file__).resolve().parents[1] / "examples" / "campus-plan.docx"


class ParserFixture:
    parser_key = "test-parser/v1"

    def __init__(self):
        self.calls = 0
        self.invalid = False

    def parse(self, request, checkpoint):
        checkpoint()
        if not request.file_path.is_file():
            raise FileNotFoundError(request.file_path)
        self.calls += 1
        if self.invalid:
            return {"score": float("nan")}
        return {"sections": [{"heading": "验证计划"}], "call": self.calls}


class AgentFixture:
    def __init__(self):
        self.invalid = False

    def review(self, request, checkpoint):
        checkpoint()
        return {"summary": request.parsed_content["sections"][0]["heading"],
                "overall_score": 150 if self.invalid else 90, "dimensions": [], "findings": []}


class AdapterIntegration(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="wensai-adapters-")
        self.addCleanup(temp.cleanup)
        self.settings = Settings(db_path=Path(temp.name) / "test.db", file_root=Path(temp.name) / "files")
        self.parser = ParserFixture()
        self.agent = AgentFixture()

    @asynccontextmanager
    async def service(self):
        app = create_app(self.settings, parser=self.parser, agent=self.agent)
        async with app.router.lifespan_context(app), httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1/api/v1/"
        ) as client:
            yield client

    async def upload(self, client):
        project = (await client.post("projects", json={"name": "适配器测试"})).raise_for_status().json()["id"]
        res = await client.post(f"projects/{project}/materials",
                                files={"file": (SAMPLE.name, SAMPLE.read_bytes())})
        return res.raise_for_status().json()["version_id"]

    async def run_task(self, client, version, retry_id=None):
        if retry_id:
            task = await client.post(f"tasks/{retry_id}/retry")
        else:
            task = await client.post("tasks", json={"version_id": version})
        path = "tasks/" + task.raise_for_status().json()["id"]
        for _ in range(300):
            data = (await client.get(path)).raise_for_status().json()
            if data["status"] in {"completed", "failed", "cancelled"}:
                return data
            await asyncio.sleep(0.02)
        self.fail("Timed out waiting for worker")

    async def test_parse_cache_survives_restart_and_refreshes_after_rules_change(self):
        async with self.service() as client:
            version = await self.upload(client)
            first = await self.run_task(client, version)
            self.assertEqual(first["status"], "completed")
            report = (await client.get("tasks/" + first["id"] + "/result")).raise_for_status().json()
            self.assertEqual((report["summary"], report["overall_score"]), ("验证计划", 90))
        async with self.service() as client:
            self.assertEqual((await self.run_task(client, version))["status"], "completed")
            self.assertEqual(self.parser.calls, 1)
            self.parser.parser_key = "test-parser/v2"
            self.assertEqual((await self.run_task(client, version))["status"], "completed")
            self.assertEqual(self.parser.calls, 2)
        with session(self.settings.db_path) as conn:
            row = conn.execute("SELECT parser_key,parsed_json,parsed_at FROM material_versions WHERE id=?",
                               (version,)).fetchone()
        self.assertEqual(row["parser_key"], self.parser.parser_key)
        self.assertTrue(row["parsed_at"])
        self.assertEqual(json.loads(row["parsed_json"])["call"], 2)

    async def test_invalid_parser_and_agent_results_fail_then_retry_without_partial_report(self):
        async with self.service() as client:
            version = await self.upload(client)
            self.parser.invalid = True
            with self.assertLogs("app.worker", level="ERROR"):
                first = await self.run_task(client, version)
            self.assertEqual(first["error_code"], "PARSER_FAILED")
            self.parser.invalid = False
            self.agent.invalid = True
            with self.assertLogs("app.worker", level="ERROR"):
                second = await self.run_task(client, version, retry_id=first["id"])
            self.assertEqual(second["error_code"], "AGENT_FAILED")
            self.assertEqual((await client.get("tasks/" + first["id"] + "/result")).status_code, 409)
            with session(self.settings.db_path) as conn:
                self.assertEqual(conn.execute("SELECT count(*) FROM review_runs").fetchone()[0], 0)
            self.agent.invalid = False
            third = await self.run_task(client, version, retry_id=first["id"])
            self.assertEqual((third["status"], third["attempt"]), ("completed", 3))
            self.assertEqual(self.parser.calls, 2)
