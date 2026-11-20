"""review-api sidecar 入口。

由 Tauri 外壳（frontend/src-tauri/src/main.rs）以
`review-api.exe --host 127.0.0.1 --port 8765` 启动。

与 `python -m app` 的区别：
1. 数据目录放到用户可写的系统位置（打包后 _MEIPASS 是临时目录，不能存库）；
2. 允许 Tauri webview 的 Origin 访问本机 API；
3. 解析外壳传入的 --host/--port。
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path


def data_root() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "WenSai"


def main() -> int:
    parser = argparse.ArgumentParser(prog="review-api")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args, _ = parser.parse_known_args()

    root = data_root()
    (root / "projects").mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("WENSAI_DB_PATH", str(root / "wensai.sqlite3"))
    os.environ.setdefault("WENSAI_FILE_ROOT", str(root / "projects"))
    # Tauri 在 Windows 上的 webview Origin 是 http://tauri.localhost，
    # macOS/Linux 是 tauri://localhost；开发模式还要放行 Vite。
    os.environ.setdefault(
        "WENSAI_CORS_ORIGINS",
        "http://tauri.localhost,tauri://localhost,http://localhost:5173,http://127.0.0.1:5173",
    )

    import uvicorn

    from app.config import Settings
    from app.main import create_app

    settings = replace(Settings.from_env(), max_file_bytes=30 * 1024 * 1024)
    app = create_app(settings)
    print(f"[review-api] data={root} listen={args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port,
                log_level=settings.log_level, proxy_headers=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
