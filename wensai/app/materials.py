"""Projects, imported materials, append-only revisions and version downloads."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse
from starlette.types import Receive, Scope, Send

from . import storage
from .common import ApiError, get_db
from .db import new_id, now, transaction

router = APIRouter(tags=["项目、材料与版本"])
Database = Annotated[sqlite3.Connection, Depends(get_db)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)


class ProjectView(BaseModel):
    id: str
    name: str
    description: str
    created_at: str
    updated_at: str


class MaterialView(BaseModel):
    id: str
    project_id: str
    name: str
    created_at: str
    updated_at: str


class VersionView(BaseModel):
    project_id: str
    material_id: str
    version_id: str
    version_no: int
    source_version_id: str | None
    file_id: str
    original_name: str
    mime_type: str
    size_bytes: int
    sha256: str
    created_at: str
    updated_at: str


VERSION_QUERY = """
    SELECT f.project_id, v.material_id, v.id AS version_id, v.version_no,
           v.parent_version_id AS source_version_id, v.file_id, f.original_name,
           f.mime_type, f.size_bytes, f.sha256, v.created_at, v.updated_at
      FROM material_versions AS v JOIN files AS f ON f.id = v.file_id
"""


def project_record(conn: sqlite3.Connection, project_id: str) -> dict:
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if row is None:
        raise ApiError(404, "PROJECT_NOT_FOUND", "找不到该项目。")
    return dict(row)


def material_record(conn: sqlite3.Connection, material_id: str) -> dict:
    row = conn.execute("SELECT * FROM materials WHERE id = ?", (material_id,)).fetchone()
    if row is None:
        raise ApiError(404, "MATERIAL_NOT_FOUND", "找不到该材料。")
    return dict(row)


def latest_version(conn: sqlite3.Connection, material_id: str, source_id: str) -> sqlite3.Row:
    latest = conn.execute(VERSION_QUERY + """
        WHERE v.material_id = ? ORDER BY v.version_no DESC LIMIT 1
    """, (material_id,)).fetchone()
    if latest is None or source_id != latest["version_id"]:
        raise ApiError(409, "VERSION_CONFLICT", "来源版本已过期或不属于该材料，请刷新版本列表。")
    return latest


def record_version(conn: sqlite3.Connection, project_id: str, material_id: str,
                   stored: storage.StoredUpload, source_id: str | None, number: int) -> dict:
    conn.execute("""
        INSERT INTO files(id,project_id,relative_path,original_name,mime_type,size_bytes,sha256)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (stored.id, project_id, stored.relative_path, stored.original_name, stored.mime_type,
          stored.size_bytes, stored.sha256))
    version_id = new_id()
    conn.execute("""
        INSERT INTO material_versions(id,material_id,file_id,version_no,parent_version_id)
        VALUES (?, ?, ?, ?, ?)
    """, (version_id, material_id, stored.id, number, source_id))
    return dict(conn.execute(VERSION_QUERY + " WHERE v.id = ?", (version_id,)).fetchone())


@router.post("/projects", status_code=201, response_model=ProjectView, summary="创建本地项目")
def create_project(body: ProjectCreate, request: Request, conn: Database):
    project_id = new_id()
    file_root = request.app.state.settings.file_root
    storage.initialize_project(file_root, project_id)
    try:
        with transaction(conn):
            conn.execute("INSERT INTO projects(id,name,description) VALUES (?,?,?)",
                         (project_id, body.name, body.description))
            result = project_record(conn, project_id)
    except BaseException:
        storage.remove_empty_project(file_root, project_id)
        raise
    return result


@router.get("/projects", response_model=list[ProjectView], summary="查询项目列表")
def list_projects(conn: Database):
    return [dict(row) for row in conn.execute("SELECT * FROM projects ORDER BY created_at DESC,id")]


@router.get("/projects/{project_id}", response_model=ProjectView, summary="查询项目信息")
def get_project(project_id: str, conn: Database):
    return project_record(conn, project_id)


@router.get("/projects/{project_id}/materials", response_model=list[MaterialView], summary="查询项目材料")
def list_materials(project_id: str, conn: Database):
    project_record(conn, project_id)
    return [dict(row) for row in conn.execute("""
        SELECT * FROM materials WHERE project_id = ? ORDER BY created_at DESC,id
    """, (project_id,))]


@router.post("/projects/{project_id}/materials", response_model=VersionView,
             status_code=201, summary="导入原始材料并生成第一版")
def import_material(project_id: str, request: Request, conn: Database,
                    file: Annotated[UploadFile, File(description="DOCX、PPTX 或 PDF 原始文件")]):
    project_record(conn, project_id)
    settings = request.app.state.settings
    stored = storage.store_upload(settings.file_root, project_id, "raw", file.filename,
                                  file.file, settings.max_file_bytes)
    try:
        with transaction(conn):
            material_id = new_id()
            conn.execute("INSERT INTO materials(id,project_id,name) VALUES (?,?,?)",
                         (material_id, project_id, stored.original_name))
            result = record_version(conn, project_id, material_id, stored, None, 1)
    except BaseException:
        storage.safe_unlink(settings.file_root, project_id, stored.relative_path)
        raise
    return result


@router.get("/materials/{material_id}/versions", response_model=list[VersionView],
            summary="按版本号顺序查看版本历史")
def list_versions(material_id: str, conn: Database):
    material_record(conn, material_id)
    return [dict(row) for row in conn.execute(
        VERSION_QUERY + " WHERE v.material_id = ? ORDER BY v.version_no", (material_id,))]


@router.post("/materials/{material_id}/versions", response_model=VersionView,
             status_code=201, summary="基于最新版本接受修改，保存一个新版本")
def add_version(material_id: str, request: Request, conn: Database,
                file: Annotated[UploadFile, File(description="修改后的完整文件")],
                source_version_id: Annotated[str, Form(min_length=1, max_length=128)]):
    project_id = material_record(conn, material_id)["project_id"]
    latest = latest_version(conn, material_id, source_version_id)
    _, extension = storage.check_name(file.filename)
    if latest["mime_type"] != storage.MIME_TYPES[extension]:
        raise ApiError(415, "VERSION_TYPE_MISMATCH", "修改稿的文件类型须与原稿一致。")
    settings = request.app.state.settings
    # Keep slow copying and type validation outside SQLite's write lock.
    stored = storage.store_upload(settings.file_root, project_id, "working", file.filename,
                                  file.file, settings.max_file_bytes)
    try:
        with transaction(conn):
            latest = latest_version(conn, material_id, source_version_id)
            result = record_version(conn, project_id, material_id, stored, source_version_id,
                                    latest["version_no"] + 1)
            conn.execute("UPDATE materials SET updated_at = ? WHERE id = ?", (now(), material_id))
    except BaseException:
        storage.safe_unlink(settings.file_root, project_id, stored.relative_path)
        raise
    return result


class VersionDownload(FileResponse):
    """Release the per-request export copy on completion or disconnect."""
    def __init__(self, root: Path, project_id: str, relative: str, path: Path, **kwargs):
        super().__init__(path, **kwargs)
        self._file_root = root
        self._project_id = project_id
        self._relative = relative

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await run_in_threadpool(storage.safe_unlink, self._file_root, self._project_id, self._relative)


@router.get("/versions/{version_id}/export", response_class=FileResponse, summary="下载指定版本",
            responses={200: {"content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}}}})
def export_version(version_id: str, request: Request, conn: Database):
    row = conn.execute("""
        SELECT f.project_id,f.relative_path,f.original_name,f.mime_type,f.sha256
        FROM material_versions AS v JOIN files AS f ON f.id=v.file_id WHERE v.id=?
    """, (version_id,)).fetchone()
    if row is None:
        raise ApiError(404, "VERSION_NOT_FOUND", "找不到该版本。")
    file_root = request.app.state.settings.file_root
    path, relative = storage.copy_export(file_root, row["project_id"], row["relative_path"],
                                         row["original_name"], row["sha256"])
    return VersionDownload(file_root, row["project_id"], relative, path, media_type=row["mime_type"],
                           filename=row["original_name"], headers={"Cache-Control": "no-store"})
