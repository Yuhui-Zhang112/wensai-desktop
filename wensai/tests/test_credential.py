"""DeepSeek 凭据接口：只写钥匙串，永不回显。"""
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.desktop import credential_store
from app.main import create_app
from app.review_agent import ReviewError

API = "/api/v1/desktop/settings/credential"


class FakeStore:
    def __init__(self):
        self.key = None

    def read(self):
        if not self.key:
            raise ReviewError("credential_missing", "系统密钥管理器尚未配置 DeepSeek 凭据。")
        return self.key

    def write(self, key):
        self.key = key

    def delete(self):
        self.key = None


@pytest.fixture
def client(tmp_path):
    settings = Settings(db_path=tmp_path / "app.db", file_root=tmp_path / "files", max_file_bytes=1024 * 1024)
    app = create_app(settings)
    store = FakeStore()
    app.dependency_overrides[credential_store] = lambda: store
    with TestClient(app, base_url="http://127.0.0.1") as test_client:
        test_client.store = store
        yield test_client


def test_status_reports_unconfigured(client):
    body = client.get(API).raise_for_status().json()
    assert body["configured"] is False
    assert body["provider"] == "deepseek"


def test_save_then_status(client):
    client.put(API, json={"apiKey": "sk-test-1234567890"}).raise_for_status()
    assert client.get(API).json()["configured"] is True
    assert client.store.key == "sk-test-1234567890"


def test_response_never_echoes_key(client):
    body = client.put(API, json={"apiKey": "sk-test-abcdefgh"}).json()
    assert "sk-test-abcdefgh" not in str(body)
    assert "apiKey" not in body


def test_rejects_too_short(client):
    assert client.put(API, json={"apiKey": "short"}).status_code == 422


def test_rejects_inner_whitespace(client):
    assert client.put(API, json={"apiKey": "sk-abc def ghijkl"}).status_code == 422


def test_delete_clears_credential(client):
    client.put(API, json={"apiKey": "sk-test-1234567890"}).raise_for_status()
    client.delete(API).raise_for_status()
    assert client.get(API).json()["configured"] is False


def test_unknown_field_is_rejected(client):
    assert client.put(API, json={"apiKey": "sk-test-1234567890", "extra": 1}).status_code == 422
