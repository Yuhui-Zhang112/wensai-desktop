"""账号与会话：邀请码注册、scrypt 密码、Bearer 会话、按用户隔离数据。

单机桌面模式（WENSAI_AUTH=off）完全不受影响；
服务端模式（WENSAI_AUTH=on）下，除登录/注册与静态页外的所有 /api/ 请求都需要有效会话。
"""
from __future__ import annotations

import base64
import contextvars
import hashlib
import hmac
import os
import secrets
from datetime import datetime, timedelta, timezone

from .db import connect, new_id, now

SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
SESSION_DAYS = 30
PUBLIC_PREFIXES = ("/api/v1/auth/",)
PUBLIC_EXACT = {"/health", "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}

_current_user: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_user", default=None)


def current_user() -> str | None:
    """当前请求的用户 id；单机模式下恒为 None。"""
    return _current_user.get()


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def hash_password(password: str) -> str:
    if not isinstance(password, str) or not 8 <= len(password) <= 200:
        raise ValueError("密码长度需在 8–200 之间。")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P, dklen=32)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(digest)}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        target = _unb64(digest)
        calc = hashlib.scrypt(password.encode("utf-8"), salt=_unb64(salt),
                              n=int(n), r=int(r), p=int(p), dklen=len(target))
        return hmac.compare_digest(calc, target)
    except Exception:
        return False


def _expired(value: str) -> bool:
    return value <= datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def create_session(db_path, user_id: str) -> dict:
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    conn = connect(db_path)
    try:
        conn.execute("INSERT INTO sessions(token,user_id,created_at,expires_at) VALUES (?,?,?,?)",
                     (token, user_id, now(), expires))
    finally:
        conn.close()
    return {"token": token, "expiresAt": expires}


def resolve_token(token: str, db_path) -> dict | None:
    if not token:
        return None
    conn = connect(db_path)
    try:
        row = conn.execute(
            "SELECT s.token, s.expires_at, u.id, u.username FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=?",
            (token,)).fetchone()
    finally:
        conn.close()
    if row is None or _expired(row["expires_at"]):
        return None
    return {"id": row["id"], "username": row["username"]}


def revoke(token: str, db_path) -> None:
    conn = connect(db_path)
    try:
        conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    finally:
        conn.close()


def consume_invite(conn, code: str) -> None:
    """原子地占用一次邀请码。已过期、超次或不存在时抛出 ValueError。"""
    row = conn.execute("SELECT * FROM invite_codes WHERE code=?", (code.strip().upper(),)).fetchone()
    if row is None:
        raise ValueError("邀请码不存在。")
    if row["expires_at"] and _expired(row["expires_at"]):
        raise ValueError("邀请码已过期。")
    used = conn.execute("UPDATE invite_codes SET used_count=used_count+1 WHERE code=? AND used_count<max_uses",
                        (row["code"],)).rowcount
    if used != 1:
        raise ValueError("邀请码已用完。")


def owner_clause(column: str) -> tuple[str, tuple]:
    """按当前用户追加过滤条件；单机模式返回空条件。"""
    user_id = current_user()
    if not user_id:
        return "", ()
    return f" AND {column}=?", (user_id,)


class AuthMiddleware:
    """纯 ASGI 中间件：校验 Bearer 会话，并把用户写入 scope/contextvar。"""

    def __init__(self, app, settings):
        self.app = app
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.settings.auth_required:
            return await self.app(scope, receive, send)

        path = scope["path"]
        if path in PUBLIC_EXACT or path.startswith(PUBLIC_PREFIXES) or not path.startswith("/api/"):
            return await self.app(scope, receive, send)

        token = ""
        for key, value in scope.get("headers", []):
            if key == b"authorization":
                raw = value.decode("latin-1").strip()
                if raw.lower().startswith("bearer "):
                    token = raw[7:].strip()
                break

        user = resolve_token(token, self.settings.db_path)
        if user is None:
            body = b'{"error":{"code":"UNAUTHORIZED","message":"\\u8bf7\\u5148\\u767b\\u5f55\\u3002"}}'
            await send({"type": "http.response.start", "status": 401,
                        "headers": [(b"content-type", b"application/json; charset=utf-8"),
                                    (b"content-length", str(len(body)).encode())]})
            await send({"type": "http.response.body", "body": body})
            return

        scope.setdefault("state", {})["user_id"] = user["id"]
        scope["state"]["username"] = user["username"]
        token_handle = _current_user.set(user["id"])
        try:
            return await self.app(scope, receive, send)
        finally:
            _current_user.reset(token_handle)
