"""注册、登录、登出与会话查询。仅在服务端模式（WENSAI_AUTH=on）生效。"""
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field

from . import auth
from .common import ApiError
from .db import connect, new_id, now, transaction

router = APIRouter(prefix="/auth", tags=["账号"])


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=200)
    inviteCode: str = Field(min_length=4, max_length=64)


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=1, max_length=200)


def _db(request: Request):
    return connect(request.app.state.settings.db_path)


def _require_enabled(request: Request):
    if not request.app.state.settings.auth_required:
        raise ApiError(403, "AUTH_DISABLED", "当前是单机模式，不需要账号。")


def _payload(user_id: str, username: str, session: dict) -> dict:
    return {"token": session["token"], "expiresAt": session["expiresAt"],
            "user": {"id": user_id, "username": username}}


@router.get("/status", summary="服务端是否启用账号体系（公开）")
def status(request: Request):
    return {"authRequired": bool(request.app.state.settings.auth_required)}


@router.post("/register", status_code=201, summary="用邀请码注册")
def register(body: RegisterIn, request: Request):
    _require_enabled(request)
    username = body.username.strip()
    if not username.replace("_", "").replace("-", "").isalnum():
        raise ApiError(422, "INVALID_USERNAME", "用户名只能用字母、数字、下划线和短横线。")
    conn = _db(request)
    try:
        try:
            password_hash = auth.hash_password(body.password)
        except ValueError as error:
            raise ApiError(422, "INVALID_PASSWORD", str(error)) from error
        try:
            with transaction(conn):
                auth.consume_invite(conn, body.inviteCode)
                user_id = new_id()
                conn.execute("INSERT INTO users(id,username,password_hash,created_at) VALUES (?,?,?,?)",
                             (user_id, username, password_hash, now()))
        except ValueError as error:
            raise ApiError(422, "INVALID_INVITE", str(error)) from error
        except Exception as error:
            if "UNIQUE" in str(error).upper():
                raise ApiError(409, "USERNAME_TAKEN", "用户名已被占用。") from error
            raise
    finally:
        conn.close()
    return _payload(user_id, username, auth.create_session(request.app.state.settings.db_path, user_id))


@router.post("/login", summary="登录并获取会话")
def login(body: LoginIn, request: Request):
    _require_enabled(request)
    conn = _db(request)
    try:
        row = conn.execute("SELECT id, username, password_hash FROM users WHERE username=?",
                           (body.username.strip(),)).fetchone()
    finally:
        conn.close()
    if row is None or not auth.verify_password(body.password, row["password_hash"]):
        raise ApiError(401, "BAD_CREDENTIALS", "用户名或密码不正确。")
    return _payload(row["id"], row["username"], auth.create_session(request.app.state.settings.db_path, row["id"]))


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    return header[7:].strip() if header.lower().startswith("bearer ") else ""


@router.get("/me", summary="当前会话对应的用户")
def me(request: Request):
    _require_enabled(request)
    user = auth.resolve_token(_bearer(request), request.app.state.settings.db_path)
    if user is None:
        raise ApiError(401, "UNAUTHORIZED", "请先登录。")
    return {"user": {"id": user["id"], "username": user["username"]}}


@router.post("/logout", status_code=204, summary="注销当前会话")
def logout(request: Request):
    _require_enabled(request)
    auth.revoke(_bearer(request), request.app.state.settings.db_path)
    return None
