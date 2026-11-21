"""账号、邀请码与数据隔离。"""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.db import connect, now
from app.main import create_app

API = "/api/v1"


def seed_invite(db_path, code="WS-TEST01", uses=5):
    conn = connect(db_path)
    try:
        conn.execute("INSERT INTO invite_codes(code,max_uses,used_count,expires_at,note,created_at) VALUES (?,?,0,?,?,?)",
                     (code, uses, "", "test", now()))
    finally:
        conn.close()


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=tmp_path / "app.db", file_root=tmp_path / "files",
                        max_file_bytes=1024 * 1024, auth_required=True)
    with TestClient(create_app(settings), base_url="http://127.0.0.1") as test_client:
        # 建表由应用生命周期完成，邀请码必须在其后写入
        seed_invite(settings.db_path, code="WS-TEST01", uses=5)
        seed_invite(settings.db_path, code="WS-ONCE", uses=1)
        yield test_client


def register(client, username, password="password123", code="WS-TEST01"):
    return client.post(API + "/auth/register",
                       json={"username": username, "password": password, "inviteCode": code})


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_register_then_me(client):
    body = register(client, "alice").json()
    assert body["token"] and body["user"]["username"] == "alice"
    me = client.get(API + "/auth/me", headers=auth(body["token"]))
    assert me.status_code == 200 and me.json()["user"]["username"] == "alice"


def test_api_requires_login(client):
    assert client.get(API + "/desktop/projects").status_code == 401


def test_login_and_wrong_password(client):
    register(client, "alice")
    assert client.post(API + "/auth/login", json={"username": "alice", "password": "nope12345"}).status_code == 401
    ok = client.post(API + "/auth/login", json={"username": "alice", "password": "password123"})
    assert ok.status_code == 200 and ok.json()["token"]


def test_bad_invite_and_duplicate_user(client):
    assert register(client, "alice", code="WS-NOPE").status_code == 422
    assert register(client, "alice").status_code == 201
    assert register(client, "alice").status_code == 409


def test_invite_use_limit(client):
    assert register(client, "user1", code="WS-ONCE").status_code == 201
    assert register(client, "user2", code="WS-ONCE").status_code == 422


def test_short_password_and_bad_username(client):
    assert register(client, "alice", password="short").status_code == 422
    assert register(client, "a b", password="password123").status_code == 422


def test_projects_are_isolated_between_users(client):
    ta = register(client, "alice").json()["token"]
    tb = register(client, "bob").json()["token"]

    created = client.post(API + "/desktop/projects", json={"name": "alice 的项目"}, headers=auth(ta))
    assert created.status_code in (200, 201)
    pid = created.json()["id"]

    assert client.get(API + "/desktop/projects", headers=auth(ta)).json()[0]["id"] == pid
    assert client.get(API + "/desktop/projects", headers=auth(tb)).json() == []
    assert client.patch(API + f"/desktop/projects/{pid}", json={"name": "改名"}, headers=auth(tb)).status_code == 404
    assert client.delete(API + f"/desktop/projects/{pid}", headers=auth(tb)).status_code == 404


def test_cross_user_material_version_and_export_denied(client):
    ta = register(client, "alice").json()["token"]
    tb = register(client, "bob").json()["token"]
    project = client.post(API + "/desktop/projects", json={"name": "p"}, headers=auth(ta)).json()

    uploaded = client.post(f"{API}/projects/{project['id']}/materials", headers=auth(ta),
                           files={"file": ("a.txt", b"hello world", "text/plain")})
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    mid, vid = body["material_id"], body["version_id"]

    assert client.get(f"{API}/materials/{mid}/versions", headers=auth(ta)).status_code == 200
    assert client.get(f"{API}/versions/{vid}/export", headers=auth(ta)).status_code == 200

    assert client.get(f"{API}/materials/{mid}/versions", headers=auth(tb)).status_code == 404
    assert client.get(f"{API}/versions/{vid}/export", headers=auth(tb)).status_code == 404
    assert client.get(f"{API}/projects/{project['id']}/materials", headers=auth(tb)).status_code == 404
    assert client.post(f"{API}/materials/{mid}/versions", headers=auth(tb),
                       files={"file": ("b.txt", b"x", "text/plain")},
                       data={"source_version_id": vid}).status_code == 404
    assert client.get(f"{API}/tasks/does-not-exist", headers=auth(tb)).status_code == 404
