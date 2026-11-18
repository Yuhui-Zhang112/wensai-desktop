"""各路由共用的请求连接与错误格式。"""

from collections.abc import Iterator
import sqlite3

from fastapi import Request
from pydantic import BaseModel
from starlette.responses import JSONResponse

from .db import session


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    with session(request.app.state.settings.db_path) as connection:
        yield connection


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details=None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class InvalidField(BaseModel):
    field: list[str | int]
    message: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: list[InvalidField] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorInfo


def error_response(status: int, code: str, message: str, details=None, headers=None):
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse({"error": error}, status_code=status, headers=headers)
