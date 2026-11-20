"""Run from the project root: python -m unittest discover -s tests -v."""

import hashlib
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from xml.sax.saxutils import escape

import httpx
from websockets.sync.client import connect as websocket_connect


ROOT = Path(__file__).resolve().parents[1]
API = "/api/v1"
FILE_LIMIT = 100 * 1024 * 1024
TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "pdf": "application/pdf",
}


def office_file(extension="docx", text="问赛测试"):
    if extension == "docx":
        part = "word/document.xml"
        document = (
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f"<w:body><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:body></w:document>"
        )
    else:
        part = "ppt/presentation.xml"
        document = '<p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>'
    manifest = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        f'<Override PartName="/{part}" ContentType="{TYPES[extension]}.main+xml"/></Types>'
    )
    relationships = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'relationships/officeDocument" Target="{part}"/></Relationships>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
        package.writestr("[Content_Types].xml", manifest)
        package.writestr("_rels/.rels", relationships)
        package.writestr(part, document)
    return output.getvalue()


def write_pdf(path, target_size=None):
    """Create a blank PDF. Whitespace before the xref table gives an exact size."""
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << >> >>",
    ]
    # Padding before xref keeps the first object easy to locate for PDF readers.
    def serialize(padding):
        head = io.BytesIO(b"")
        head.write(b"%PDF-1.4\n")
        offsets = []
        for i, obj in enumerate(objects, 1):
            offsets.append(head.tell())
            head.write(f"{i} 0 obj\n".encode() + obj + b"\nendobj\n")
        xref = head.tell() + padding
        tail = b"xref\n0 4\n0000000000 65535 f \n"
        for offset in offsets:
            tail += f"{offset:010} 00000 n \n".encode()
        tail += f"trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
        return head.getvalue(), tail

    padding = 0
    for _ in range(5):
        head, tail = serialize(padding)
        if target_size is None or len(head) + padding + len(tail) == target_size:
            break
        padding = target_size - len(head) - len(tail)
    else:
        raise ValueError("Could not size test PDF")
    with path.open("wb") as doc:
        doc.write(head)
        block = b" " * (1024 * 1024)
        remaining = padding
        while remaining:
            count = min(len(block), remaining)
            doc.write(block[:count])
            remaining -= count
        doc.write(tail)


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="wensai-accept-")
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.file_root = self.directory / "projects"
        with closing(socket.socket()) as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"
        self.environment = {k: v for k, v in os.environ.items() if not k.startswith("WENSAI_")}
        self.environment.update(
            WENSAI_DB_PATH=str(self.directory / "review.db"),
            WENSAI_FILE_ROOT=str(self.file_root),
            WENSAI_PORT=str(self.port),
            WENSAI_ENV="development",
            WENSAI_MOCK_STEP_SECONDS="0.35",
            PYTHONDONTWRITEBYTECODE="1",
        )
        self.log_path = self.directory / "service.log"
        self.process = None
        self.addCleanup(self.stop)
        self.client = httpx.Client(base_url=self.base, timeout=45, trust_env=False)
        self.addCleanup(self.client.close)
        self.start()

    def start(self):
        with self.log_path.open("ab") as log:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "app"], cwd=ROOT, env=self.environment,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            )
        deadline = time.monotonic() + 15
        while self.process.poll() is None and time.monotonic() < deadline:
            try:
                if self.client.get("/health", timeout=1).json().get("status") == "ok":
                    return
            except (ValueError, httpx.HTTPError):
                pass
            time.sleep(0.05)
        self.fail("Service failed to start:\n" + self.log_path.read_text(errors="replace"))

    def stop(self, force=False):
        if self.process and self.process.poll() is None:
            if force:
                self.process.kill()
            else:
                self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def expect(self, response, status):
        self.assertEqual(response.status_code, status, response.text[:1500] if response.is_error else "")
        return response.json()

    def expect_error(self, response, status):
        body = self.expect(response, status)
        self.assertTrue(body["error"]["code"])
        self.assertTrue(body["error"]["message"])
        return body["error"]["code"]

    def project(self):
        return self.expect(self.client.post(API + "/projects", json={"name": "测试项目"}), 201)["id"]

    def upload(self, project, name, data, mime=None):
        return self.client.post(API + f"/projects/{project}/materials", files={
            "file": (name, data, mime or TYPES.get(name.rsplit(".", 1)[-1], "application/octet-stream")),
        })

    def material(self, project=None):
        return self.expect(self.upload(project or self.project(), "申报书.docx", office_file()), 201)

    def add_version(self, material, base, text):
        return self.client.post(API + f"/materials/{material}/versions",
                                data={"source_version_id": base},
                                files={"file": ("修改稿.docx", text, TYPES["docx"])})

    def task(self, version):
        task = self.expect(self.client.post(API + "/tasks", json={"version_id": version}), 201)
        self.assertEqual(task["status"], "queued")
        return task["id"]

    def wait_status(self, task, expected):
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            body = self.expect(self.client.get(API + f"/tasks/{task}"), 200)
            if body["status"] == expected:
                return body
            if body["status"] in {"completed", "cancelled", "failed"}:
                self.fail(f"Expected {expected}, got {body}")
            time.sleep(0.03)
        self.fail(f"Timeout waiting for {expected}: {task}")

    def events(self, task, after=0):
        return self.expect(self.client.get(API + f"/tasks/{task}/events",
                                           params={"after": after}), 200)["items"]

    def test_health_cors_validation_and_lookup(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        for origin in ("http://localhost:5173", "http://127.0.0.1:5173"):
            response = self.client.options(API + "/projects", headers={
                "Origin": origin, "Access-Control-Request-Method": "POST",
            })
            self.assertEqual(response.headers.get("access-control-allow-origin"), origin)
        unknown = self.client.options(API + "/projects", headers={
            "Origin": "https://example.invalid", "Access-Control-Request-Method": "POST",
        })
        self.assertNotIn("access-control-allow-origin", unknown.headers)
        self.expect_error(self.client.post(API + "/projects", json={}), 422)
        project = self.project()
        self.assertEqual(self.client.get(API + f"/projects/{project}").json()["id"], project)
        self.expect_error(self.client.get(API + "/projects/af63c571-8f6c-4e55-9a25-733745254621"), 404)

        self.assertTrue(any(p["id"] == project for p in self.client.get(API + "/projects").json()))

    def test_formats_and_invalid_uploads(self):
        project = self.project()
        for ext in ("docx", "pptx"):
            with self.subTest(ext=ext):
                self.expect(self.upload(project, "真实材料." + ext, office_file(ext)), 201)
        pdf = self.directory / "valid.pdf"
        write_pdf(pdf)
        self.expect(self.upload(project, pdf.name, pdf.read_bytes()), 201)
        # 整合版新增 TXT/Markdown 支持：合法 UTF-8 文本应被接受（原 A 版本仅支持 Office/PDF）
        self.expect(self.upload(project, "memo.txt", b"hello"), 201)
        self.expect_error(self.upload(project, "memo.bin", b"hello"), 415)
        self.expect_error(self.upload(project, "memo.pdf", b"hello"), 415)
        self.expect_error(self.upload(project, "memo.docx", office_file("pptx")), 415)
        self.expect_error(self.upload(project, "../outside.docx", office_file()), 400)
        self.assertFalse((self.file_root / "outside.docx").exists())
        materials = self.expect(self.client.get(API + f"/projects/{project}/materials"), 200)
        self.assertEqual(len(materials), 4)

    def test_exact_100_mib_and_one_byte_over(self):
        project = self.project()
        pdf = self.directory / "boundary.pdf"
        write_pdf(pdf, FILE_LIMIT)
        with pdf.open("rb") as source:
            self.expect(self.upload(project, pdf.name, source), 201)
        with pdf.open("ab") as source:
            source.write(b"\n")
        with pdf.open("rb") as source:
            self.expect_error(self.upload(project, pdf.name, source), 413)
        self.assertEqual(len(list((self.file_root / project / "raw").iterdir())), 1)

    def test_two_revisions_are_immutable_and_concurrent_saves_do_not_fork(self):
        original = office_file(text="第一稿")
        second = office_file(text="第二稿")
        third = office_file(text="第三稿")
        project = self.project()
        v1 = self.expect(self.upload(project, "材料.docx", original), 201)
        m = v1["material_id"]
        v2 = self.expect(self.add_version(m, v1["version_id"], second), 201)
        v3 = self.expect(self.add_version(m, v2["version_id"], third), 201)
        versions = (v1, v2, v3)
        for number, (meta, data) in enumerate(zip(versions, (original, second, third)), start=1):
            self.assertEqual(meta["version_no"], number)
            self.assertEqual(meta["sha256"], hashlib.sha256(data).hexdigest())
            if number > 1:
                self.assertEqual(meta["source_version_id"], versions[number - 2]["version_id"])
            export = self.client.get(API + "/versions/" + meta["version_id"] + "/export")
            self.assertEqual(export.status_code, 200)
            self.assertIn("attachment", export.headers["Content-Disposition"])
            self.assertEqual(export.content, data)
        with ThreadPoolExecutor(max_workers=2) as pool:
            calls = [pool.submit(self.add_version, m, v3["version_id"], office_file(text=t)) for t in ("甲", "乙")]
            self.assertEqual(sorted(item.result().status_code for item in calls), [201, 409])
        self.assertEqual(len(list((self.file_root / project / "working").iterdir())), 3)
        history = self.expect(self.client.get(API + f"/materials/{m}/versions"), 200)
        self.assertEqual(sorted(v["version_no"] for v in history), [1, 2, 3, 4])

    def test_replay_and_result_after_worker_finishes(self):
        task = self.task(self.material()["version_id"])
        socket_url = f"ws://127.0.0.1:{self.port}{API}/tasks/{task}/events/ws"
        with websocket_connect(socket_url + "?after=0", open_timeout=4) as ws:
            first = json.loads(ws.recv(timeout=5))
            self.assertEqual((first["seq"], first["status"]), (1, "pending"))
        self.wait_status(task, "running")
        root = API + f"/tasks/{task}"
        self.expect_error(self.client.get(root + "/result"), 409)
        # Ordinary API calls finish while the Agent is still working.
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses = list(pool.map(self.client.get, ["/health", API + "/projects"] * 4))
        self.assertTrue(all(r.status_code == 200 for r in responses))
        self.assertEqual(responses[0].json()["status"], "ok")
        self.assertEqual(len(responses[1].json()), 1)
        self.assertEqual(self.client.get(root).json()["status"], "running")
        self.wait_status(task, "completed")
        replay = self.events(task, after=first["seq"])
        with websocket_connect(socket_url + "?after=1", open_timeout=4) as ws:
            frames = [json.loads(ws.recv(timeout=4)) for _ in replay]
        self.assertEqual(frames, replay)
        page = self.expect(self.client.get(root + "/events", params={"after": 0, "limit": 2}), 200)
        self.assertEqual(page["next_after"], 2)
        self.assertEqual([event["seq"] for event in page["items"]], [1, 2])
        journal = self.events(task)
        self.assertEqual([row["seq"] for row in journal], list(range(1, len(journal) + 1)))
        self.assertEqual([row["status"] for row in journal], ["pending", "queued", "running", "completed"])
        result = self.expect(self.client.get(root + "/result"), 200)
        self.assertTrue(0 <= result["overall_score"] <= 100)
        self.assertTrue(result["dimensions"])
        self.assertTrue(result["findings"][0]["suggestions"])
        self.stop()
        self.start()
        self.assertEqual(self.client.get(root + "/result").json(), result)
        self.assertEqual(self.events(task), journal)
        self.expect_error(self.client.post(root + "/retry"), 409)

    def test_cancel_retry_and_failed_attempt_retry(self):
        project = self.project()
        version = self.material(project)["version_id"]
        task = self.task(version)
        root = API + f"/tasks/{task}"
        self.wait_status(task, "running")
        self.expect(self.client.post(root + "/cancel"), 200)
        self.wait_status(task, "cancelled")
        self.expect(self.client.post(root + "/retry"), 200)
        self.assertEqual(self.wait_status(task, "completed")["attempt"], 2)
        self.assertEqual([e["status"] for e in self.events(task)], [
            "pending", "queued", "running", "cancelling", "cancelled", "queued", "running", "completed",
        ])
        # Simulate a missing source file only in this temporary project.
        source, = (self.file_root / project / "raw").iterdir()
        held = self.directory / "held.docx"
        source.rename(held)
        failed_task = self.task(version)
        failed = self.wait_status(failed_task, "failed")
        self.assertEqual(failed["error_code"], "MATERIAL_UNAVAILABLE")
        self.assertTrue(failed["error_message"])
        held.rename(source)
        self.expect(self.client.post(API + f"/tasks/{failed_task}/retry"), 200)
        self.assertEqual(self.wait_status(failed_task, "completed")["attempt"], 2)
        self.assertEqual([e["status"] for e in self.events(failed_task)], [
            "pending", "queued", "running", "failed", "queued", "running", "completed",
        ])

    def test_hard_restart_recovers_inflight_and_queued_jobs(self):
        version = self.material()["version_id"]
        active = self.task(version)
        self.wait_status(active, "running")
        queued = self.task(version)
        self.stop(force=True)
        self.start()
        self.assertEqual(self.wait_status(active, "failed")["error_code"], "WORKER_INTERRUPTED")
        self.wait_status(queued, "completed")
        self.expect(self.client.post(API + f"/tasks/{active}/retry"), 200)
        self.wait_status(active, "completed")
        journal = self.events(active)
        self.assertEqual([e["status"] for e in journal], [
            "pending", "queued", "running", "failed", "queued", "running", "completed",
        ])


if __name__ == "__main__":
    unittest.main()
