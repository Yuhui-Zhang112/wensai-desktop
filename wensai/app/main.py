"""本地 API 的构建入口。"""

import asyncio
import logging
import sqlite3
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from . import materials, tasks
from .common import ApiError, ErrorEnvelope, error_response, get_db
from .config import Settings
from .db import initialize, session
from .auth import AuthMiddleware
from .http import JsonCORSMiddleware, LocalRequestPolicy
from .instance import instance_lock
from .storage import recover_storage
from .worker import Worker
from .desktop import router as desktop_router
from .auth_api import router as auth_router
from .desktop_engine import Engine

logger = logging.getLogger("uvicorn.error")


def create_app(settings=None, agent=None, parser=None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        db_lock = settings.db_path.with_name(settings.db_path.name + ".service.lock")
        with instance_lock(db_lock), instance_lock(settings.file_root / ".service.lock"):
            initialize(settings.db_path)
            with session(settings.db_path) as conn:
                recover_storage(conn, settings.file_root)
            worker = Worker(settings, agent=agent, parser=parser)
            app.state.worker = worker
            worker.start()
            desktop_engine = Engine(settings)
            app.state.desktop_engine = desktop_engine
            desktop_engine.start()
            try:
                yield
            finally:
                await asyncio.to_thread(desktop_engine.stop)
                await asyncio.to_thread(worker.stop)

    app = FastAPI(title="问赛 · 本地评审 API", version="1.0.0",
                  description="竞赛材料归档、版本管理和异步评审。默认使用演示 Agent。",
                  responses={"4XX": {"model": ErrorEnvelope, "description": "请求或资源状态错误"},
                             "5XX": {"model": ErrorEnvelope, "description": "服务或数据库错误"}},
                  lifespan=lifespan)
    app.state.settings = settings
    app.add_middleware(AuthMiddleware, settings=settings)
    app.add_middleware(LocalRequestPolicy, settings=settings)
    if settings.cors_origins:
        app.add_middleware(JsonCORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
                           allow_headers=["Content-Type"], expose_headers=["Content-Disposition"])

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, exc: ApiError):
        return error_response(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, exc: RequestValidationError):
        fields = [{"field": list(error["loc"]), "message": error["msg"]} for error in exc.errors()]
        return error_response(422, "VALIDATION_ERROR", "请检查请求参数。", fields)

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, exc: HTTPException):
        codes = {400: "BAD_REQUEST", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 413: "REQUEST_TOO_LARGE"}
        return error_response(exc.status_code, codes.get(exc.status_code, "HTTP_ERROR"),
                              str(exc.detail), headers=exc.headers)

    @app.exception_handler(sqlite3.OperationalError)
    async def database_error(_request: Request, exc: sqlite3.OperationalError):
        if getattr(exc, "sqlite_errorcode", None) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
            return error_response(503, "DATABASE_BUSY", "数据库正忙，请稍后重试。")
        logger.exception("数据库操作失败")
        return error_response(500, "DATABASE_ERROR", "数据库操作失败，请查看服务日志。")

    @app.exception_handler(Exception)
    async def unexpected_error(_request: Request, _exc: Exception):
        return error_response(500, "INTERNAL_ERROR", "服务处理失败，请查看服务日志。")

    @app.get("/health", tags=["服务"], summary="启动及数据库可读性检查")
    def health(db: sqlite3.Connection = Depends(get_db)):
        db.execute("SELECT 1 FROM projects LIMIT 1").fetchone()
        return {"status": "ok"}

    app.include_router(auth_router, prefix="/api/v1")
    app.include_router(materials.router, prefix="/api/v1")
    app.include_router(tasks.router, prefix="/api/v1")
    app.include_router(desktop_router, prefix="/api/v1")
    return app
