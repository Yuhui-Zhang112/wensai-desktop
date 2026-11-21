"""本地服务的统一配置。相对路径均以项目代码根目录为基准。"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
MAX_FILE_BYTES = 100 * 1024 * 1024
VITE_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def _project_path(value: str | Path) -> Path:
    return (PROJECT_ROOT / Path(value).expanduser()).resolve()


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = 8000
    db_path: Path = DATA_DIR / "wensai.sqlite3"
    file_root: Path = DATA_DIR / "projects"
    log_level: str = "info"
    cors_origins: tuple[str, ...] = VITE_ORIGINS
    max_file_bytes: int = MAX_FILE_BYTES
    mock_step_seconds: float = 0.15
    auth_required: bool = False

    def __post_init__(self) -> None:
        if self.environment not in {"development", "production", "test"}:
            raise ValueError("WENSAI_ENV 取 development、production 或 test")
        if not 1 <= self.port <= 65535:
            raise ValueError("WENSAI_PORT 必须在 1 和 65535 之间")
        if not self.host.strip():
            raise ValueError("WENSAI_HOST 不能为空")
        if not 1 <= self.max_file_bytes <= MAX_FILE_BYTES:
            raise ValueError("单文件上限必须在 1 字节和 100 MiB 之间")
        if not math.isfinite(self.mock_step_seconds) or self.mock_step_seconds < 0:
            raise ValueError("WENSAI_MOCK_STEP_SECONDS 必须是有限非负数")
        level = self.log_level.lower()
        if level not in {"critical", "error", "warning", "info", "debug", "trace"}:
            raise ValueError("未知的 WENSAI_LOG_LEVEL")
        object.__setattr__(self, "log_level", level)
        object.__setattr__(self, "db_path", _project_path(self.db_path))
        object.__setattr__(self, "file_root", _project_path(self.file_root))
        if self.environment == "production":
            object.__setattr__(self, "host", "127.0.0.1")
            object.__setattr__(self, "cors_origins", ())

    @classmethod
    def from_env(cls) -> Settings:
        env = os.environ
        origins = env.get("WENSAI_CORS_ORIGINS", ",".join(VITE_ORIGINS))
        return cls(
            environment=env.get("WENSAI_ENV", "development").lower(),
            host=env.get("WENSAI_HOST", "127.0.0.1"),
            port=int(env.get("WENSAI_PORT", "8000")),
            db_path=Path(env.get("WENSAI_DB_PATH", DATA_DIR / "wensai.sqlite3")),
            file_root=Path(env.get("WENSAI_FILE_ROOT", DATA_DIR / "projects")),
            log_level=env.get("WENSAI_LOG_LEVEL", "info"),
            cors_origins=tuple(s.strip() for s in origins.split(",") if s.strip()),
            mock_step_seconds=float(env.get("WENSAI_MOCK_STEP_SECONDS", "0.15")),
            auth_required=env.get("WENSAI_AUTH", "off").lower() in {"on", "1", "true", "yes"},
        )
