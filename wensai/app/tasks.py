"""Task HTTP API and a resumable WebSocket over the durable SQLite event log."""
import asyncio
import json
import sqlite3
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, StringConstraints
from starlette.concurrency import run_in_threadpool

from .agent import Dimension
from .common import ApiError, get_db
from .db import new_id, now, session, transaction

router = APIRouter(prefix="/tasks", tags=["任务与评审"])
DB = Annotated[sqlite3.Connection, Depends(get_db)]
Id = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Cursor = Annotated[int, Query(ge=0, le=9223372036854775807)]
Status = Literal["pending", "queued", "running", "completed", "failed", "cancelling", "cancelled"]


class NewTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: Id
    profile_id: Id = "default"


class Task(BaseModel):
    id: str
    version_id: str
    profile_id: str
    status: Status
    attempt: int
    error_code: str | None
    error_message: str | None
    created_at: str
    updated_at: str


class TaskEvent(BaseModel):
    id: str
    task_id: str
    seq: int
    status: Status
    message: str
    created_at: str
    updated_at: str


class EventPage(BaseModel):
    items: list[TaskEvent]
    next_after: int


class SavedSuggestion(BaseModel):
    id: str
    content: str


class SavedFinding(BaseModel):
    id: str
    category: str
    severity: str
    location: str
    description: str
    suggestions: list[SavedSuggestion]


class ReviewResult(BaseModel):
    id: str
    task_id: str
    version_id: str
    profile_id: str
    overall_score: float
    summary: str
    dimensions: list[Dimension]
    findings: list[SavedFinding]
    created_at: str
    updated_at: str


def _task(conn, task_id):
    row = conn.execute(
        """SELECT id, material_version_id AS version_id, profile_id, status, attempt,
                  error_code, error_message, created_at, updated_at FROM tasks WHERE id=?""",
        (task_id,),
    ).fetchone()
    if row is None:
        raise ApiError(404, "TASK_NOT_FOUND", "任务不存在。")
    return dict(row)


def append_event(conn, task_id, status, message):
    conn.execute(
        """INSERT INTO task_events(id, task_id, seq, status, message)
           SELECT ?, ?, COALESCE(MAX(seq), 0) + 1, ?, ? FROM task_events WHERE task_id=?""",
        (new_id(), task_id, status, message, task_id),
    )


def change_state(conn, task_id, status, message, *, error_code=None, error_message=None):
    """Caller owns a write transaction. The migration enforces all allowed transitions."""
    conn.execute(
        """UPDATE tasks SET status=?, attempt=attempt+?, updated_at=?, error_code=?, error_message=?
           WHERE id=?""",
        (status, int(status == "queued"), now(), error_code, error_message, task_id),
    )
    append_event(conn, task_id, status, message)


@router.post("", response_model=Task, status_code=201, summary="对指定材料版本创建评审任务")
def create_task(payload: NewTask, request: Request, conn: DB):
    with transaction(conn):
        if not conn.execute("SELECT 1 FROM material_versions WHERE id=?", (payload.version_id,)).fetchone():
            raise ApiError(404, "VERSION_NOT_FOUND", "材料版本不存在。")
        if not conn.execute("SELECT 1 FROM review_profiles WHERE id=?", (payload.profile_id,)).fetchone():
            raise ApiError(404, "PROFILE_NOT_FOUND", "评审配置不存在。")
        task_id = new_id()
        conn.execute(
            "INSERT INTO tasks(id, material_version_id, profile_id) VALUES (?, ?, ?)",
            (task_id, payload.version_id, payload.profile_id),
        )
        append_event(conn, task_id, "pending", "任务已创建。")
        change_state(conn, task_id, "queued", "第 1 次评审已排队。")
        result = _task(conn, task_id)
    request.app.state.worker.wake()
    return result


@router.get("/{task_id}", response_model=Task, summary="查询任务状态及尝试次数")
def get_task(task_id: str, conn: DB):
    return _task(conn, task_id)


@router.post("/{task_id}/cancel", response_model=Task, summary="请求取消正在运行的任务")
def cancel_task(task_id: str, conn: DB):
    with transaction(conn):
        task = _task(conn, task_id)
        if task["status"] != "running":
            raise ApiError(409, "INVALID_TASK_STATE", "仅运行中的任务可以请求取消。")
        change_state(conn, task_id, "cancelling", "已收到取消请求。")
        return _task(conn, task_id)


@router.post("/{task_id}/retry", response_model=Task, summary="重新排队失败或已取消的任务")
def retry_task(task_id: str, request: Request, conn: DB):
    with transaction(conn):
        task = _task(conn, task_id)
        if task["status"] not in {"failed", "cancelled"}:
            raise ApiError(409, "INVALID_TASK_STATE", "仅失败或已取消的任务可以重试。")
        attempt = task["attempt"] + 1
        change_state(conn, task_id, "queued", f"第 {attempt} 次评审已排队。")
        result = _task(conn, task_id)
    request.app.state.worker.wake()
    return result


def _events(conn, task_id, after, limit):
    rows = conn.execute(
        """SELECT id,task_id,seq,status,message,created_at,updated_at FROM task_events
           WHERE task_id=? AND seq>? ORDER BY seq LIMIT ?""",
        (task_id, after, limit),
    )
    return [dict(row) for row in rows]


@router.get("/{task_id}/events", response_model=EventPage, summary="按任务序号补齐事件")
def get_events(task_id: str, conn: DB, after: Cursor = 0, limit: Annotated[int, Query(ge=1, le=500)] = 100):
    _task(conn, task_id)
    items = _events(conn, task_id, after, limit)
    return {"items": items, "next_after": items[-1]["seq"] if items else after}


@router.websocket("/{task_id}/events/ws")
async def watch_events(websocket: WebSocket, task_id: str, after: Cursor = 0):
    db_path = websocket.app.state.settings.db_path

    def read_batch(cursor, check_task=False):
        with session(db_path) as conn:
            if check_task:
                _task(conn, task_id)
            return _events(conn, task_id, cursor, 100)

    await websocket.accept()
    try:
        batch = await run_in_threadpool(read_batch, after, True)
    except ApiError:
        await websocket.close(code=4404, reason="TASK_NOT_FOUND")
        return
    receive = asyncio.create_task(websocket.receive())
    try:
        while True:
            for event in batch:
                await websocket.send_json(event)
                after = event["seq"]
            if len(batch) < 100:
                await asyncio.wait({receive}, timeout=0.2)
            if receive.done():
                if receive.result()["type"] == "websocket.disconnect":
                    break
                receive = asyncio.create_task(websocket.receive())
            batch = await run_in_threadpool(read_batch, after)
    except WebSocketDisconnect:
        pass
    finally:
        receive.cancel()
        await asyncio.gather(receive, return_exceptions=True)


@router.get("/{task_id}/result", response_model=ReviewResult, summary="查询已完成任务的评审结果")
def get_result(task_id: str, conn: DB):
    task = _task(conn, task_id)
    if task["status"] != "completed":
        raise ApiError(409, "RESULT_NOT_READY", "任务完成后可读取评审结果。")
    run = dict(conn.execute("SELECT * FROM review_runs WHERE task_id=?", (task_id,)).fetchone())
    run["version_id"] = task["version_id"]
    run["profile_id"] = task["profile_id"]
    run["dimensions"] = json.loads(run.pop("dimensions_json"))
    findings = {
        row["id"]: {**dict(row), "suggestions": []}
        for row in conn.execute(
            """SELECT id,category,severity,location,description FROM review_findings
               WHERE run_id=? ORDER BY rowid""", (run["id"],),
        )
    }
    suggestions = conn.execute(
        """SELECT s.id,s.finding_id,s.content FROM suggestions s
           JOIN review_findings f ON f.id=s.finding_id WHERE f.run_id=? ORDER BY s.rowid""",
        (run["id"],),
    )
    for item in suggestions:
        findings[item["finding_id"]]["suggestions"].append({"id": item["id"], "content": item["content"]})
    run["findings"] = list(findings.values())
    return run
