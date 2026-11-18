"""One cooperative worker per local service. SQLite is the durable task queue."""
from dataclasses import replace
import json
import logging
import threading

from .agent import DocumentParser, MockAgent, ReviewAgent, ReviewOutput, ReviewRequest
from .common import ApiError
from .config import Settings
from .db import new_id, now, session, transaction
from .storage import resolve_file
from .tasks import change_state

log = logging.getLogger(__name__)


class _Cancelled(Exception):
    pass


class _Stopping(Exception):
    pass


class _MissingFile(Exception):
    pass


class _ParserFailed(Exception):
    pass


class Worker:
    def __init__(self, settings: Settings, agent: ReviewAgent | None = None,
                 parser: DocumentParser | None = None):
        self.parser = parser
        self.settings = settings
        self.agent = agent if agent is not None else MockAgent(settings.mock_step_seconds)
        self._wakeup = threading.Event()
        self._stopping = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        self._recover()
        self._stopping.clear()
        self._thread = threading.Thread(target=self._loop, name="wensai-review", daemon=True)
        self._thread.start()

    def wake(self):
        self._wakeup.set()

    def stop(self):
        self._stopping.set()
        self.wake()
        if self._thread is not None:
            self._thread.join()

    def _recover(self):
        with session(self.settings.db_path) as conn, transaction(conn):
            abandoned = conn.execute(
                "SELECT id,status FROM tasks WHERE status IN ('pending','running','cancelling') ORDER BY rowid"
            ).fetchall()
            for row in abandoned:
                if row["status"] == "pending":
                    change_state(conn, row["id"], "queued", "服务恢复，任务已进入队列。")
                elif row["status"] == "cancelling":
                    change_state(conn, row["id"], "cancelled", "服务恢复，已完成上次取消请求。")
                else:
                    self._interrupted(conn, row["id"])

    @staticmethod
    def _interrupted(conn, task_id):
        message = "Worker 中断，可重试此任务。"
        change_state(conn, task_id, "failed", "WORKER_INTERRUPTED：" + message,
                     error_code="WORKER_INTERRUPTED", error_message=message)

    def _claim(self):
        with session(self.settings.db_path) as conn, transaction(conn):
            row = conn.execute(
                "SELECT id FROM tasks WHERE status='queued' ORDER BY updated_at,rowid LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            task_id = row["id"]
            change_state(conn, task_id, "running", "Worker 已开始评审。")
            return task_id

    def _loop(self):
        recovery_needed = False
        while not self._stopping.is_set():
            try:
                if recovery_needed:
                    self._recover()
                    recovery_needed = False
                self._wakeup.clear()
                task_id = self._claim()
                if task_id is None:
                    self._wakeup.wait(1)
                else:
                    self._execute(task_id)
            except Exception:
                # A transaction that cannot be committed must not strand a running task.
                log.exception("Worker 无法完成数据库操作，将再次检查队列")
                recovery_needed = True
                self._stopping.wait(1)

    def _input(self, task_id):
        with session(self.settings.db_path) as conn:
            row = conn.execute(
                """SELECT t.id AS task_id, t.attempt, t.material_version_id AS version_id,
                          t.profile_id, p.config_json, f.project_id, f.relative_path,
                          f.original_name, f.mime_type, f.sha256
                   FROM tasks t JOIN review_profiles p ON p.id=t.profile_id
                   JOIN material_versions v ON v.id=t.material_version_id
                   JOIN files f ON f.id=v.file_id WHERE t.id=?""", (task_id,),
            ).fetchone()
        try:
            path = resolve_file(self.settings.file_root, row["project_id"], row["relative_path"])
        except (OSError, ApiError, ValueError) as exc:
            raise _MissingFile from exc
        return ReviewRequest(
            task_id=task_id, attempt=row["attempt"], version_id=row["version_id"],
            profile_id=row["profile_id"], profile=json.loads(row["config_json"]),
            project_id=row["project_id"], original_name=row["original_name"],
            mime_type=row["mime_type"], sha256=row["sha256"], file_path=path,
        )

    def _parse(self, request, checkpoint):
        parser = self.parser
        if parser is None:
            return request
        key = getattr(parser, "parser_key", None)
        if not isinstance(key, str) or not key.strip():
            raise _ParserFailed("parser_key must be a non-empty string")
        with session(self.settings.db_path) as conn:
            cached = conn.execute(
                "SELECT parsed_json FROM material_versions WHERE id=? AND parser_key=?",
                (request.version_id, key),
            ).fetchone()
        if cached is not None and cached["parsed_json"] is not None:
            return replace(request, parsed_content=json.loads(cached["parsed_json"]))

        try:
            content = parser.parse(request, checkpoint)
            if not isinstance(content, dict):
                raise TypeError("expected a JSON object")
            encoded = json.dumps(content, allow_nan=False, separators=(",", ":"))
            canonical = json.loads(encoded)
            if canonical != content:
                raise ValueError("parsed content contains non-JSON keys or values")
        except (_Cancelled, _Stopping):
            raise
        except Exception as exc:
            raise _ParserFailed from exc

        checkpoint()
        with session(self.settings.db_path) as conn, transaction(conn):
            status = conn.execute("SELECT status FROM tasks WHERE id=?", (request.task_id,)).fetchone()
            if status["status"] == "cancelling":
                raise _Cancelled()
            timestamp = now()
            conn.execute(
                """UPDATE material_versions SET parser_key=?, parsed_json=?, parsed_at=?, updated_at=?
                   WHERE id=?""", (key, encoded, timestamp, timestamp, request.version_id),
            )
        return replace(request, parsed_content=canonical)

    def _checkpoint(self, task_id):
        if self._stopping.is_set():
            raise _Stopping()
        with session(self.settings.db_path) as conn:
            row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row["status"] == "cancelling":
            raise _Cancelled()

    def _execute(self, task_id):
        output = None
        error_code = None
        error_message = None
        def checkpoint():
            self._checkpoint(task_id)

        try:
            request = self._input(task_id)
            checkpoint()
            request = self._parse(request, checkpoint)
            checkpoint()
            output = ReviewOutput.model_validate(self.agent.review(request, checkpoint))
        except (_Cancelled, _Stopping):
            pass
        except _ParserFailed:
            log.exception("文档解析适配器执行失败 task_id=%s", task_id)
            error_code = "PARSER_FAILED"
            error_message = "解析适配器执行失败或返回了无效的 JSON 对象，详见服务日志。"
        except _MissingFile:
            error_code = "MATERIAL_UNAVAILABLE"
            error_message = "材料文件不可读取，请检查本地存储后重试。"
        except Exception:
            log.exception("评审适配器执行失败 task_id=%s", task_id)
            error_code = "AGENT_FAILED"
            error_message = "评审适配器执行失败或返回了无效结果，详见服务日志。"

        # A cancellation that committed before this write always wins. Even if the
        # adapter already returned, no result is exposed for a cancelled task.
        with session(self.settings.db_path) as conn, transaction(conn):
            row = conn.execute("SELECT status FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row["status"] == "cancelling":
                change_state(conn, task_id, "cancelled", "任务已取消。")
            elif self._stopping.is_set():
                self._interrupted(conn, task_id)
            elif error_code:
                change_state(conn, task_id, "failed", f"{error_code}：{error_message}",
                             error_code=error_code, error_message=error_message)
            else:
                self._save(conn, task_id, output)
                change_state(conn, task_id, "completed", "评审结果已保存。")

    @staticmethod
    def _save(conn, task_id, output: ReviewOutput):
        run_id = new_id()
        dimensions = [dimension.model_dump() for dimension in output.dimensions]
        conn.execute(
            """INSERT INTO review_runs(id,task_id,overall_score,summary,dimensions_json)
               VALUES(?,?,?,?,?)""",
            (run_id, task_id, output.overall_score, output.summary, json.dumps(dimensions, ensure_ascii=False)),
        )
        for finding in output.findings:
            finding_id = new_id()
            conn.execute(
                """INSERT INTO review_findings(id,run_id,category,severity,location,description)
                   VALUES(?,?,?,?,?,?)""",
                (finding_id, run_id, finding.category, finding.severity, finding.location, finding.description),
            )
            conn.executemany(
                "INSERT INTO suggestions(id,finding_id,content) VALUES(?,?,?)",
                [(new_id(), finding_id, content) for content in finding.suggestions],
            )
