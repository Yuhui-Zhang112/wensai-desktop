"""把本地后端打成 Tauri 需要的 sidecar 可执行文件。

产物：../frontend/src-tauri/binaries/review-api-<target-triple>[.exe]
Tauri 的 externalBin 声明为 "binaries/review-api"，会自动补 target triple 后缀。

用法：python scripts/build_sidecar.py
"""
from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARIES = ROOT.parent / "frontend" / "src-tauri" / "binaries"

SEP = ";" if sys.platform == "win32" else ":"
EXE = ".exe" if sys.platform == "win32" else ""

HIDDEN = [
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.loops.asyncio",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.http.h11_impl",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.protocols.websockets.websockets_impl",
    "uvicorn.lifespan.on",
    "app.main",
    "app.desktop",
    "app.material_review",
    "app.review_agent",
]


def target_triple() -> str:
    machine = platform.machine().lower()
    if machine in ("arm64", "aarch64"):
        arch = "aarch64"
    else:
        arch = "x86_64"
    if sys.platform == "win32":
        return f"{arch}-pc-windows-msvc"
    if sys.platform == "darwin":
        return f"{arch}-apple-darwin"
    return f"{arch}-unknown-linux-gnu"


def main() -> int:
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile",
        "--name", "review-api",
        "--collect-data", "app",
        "--add-data", f"migrations{SEP}migrations",
        "--console",
    ]
    for mod in HIDDEN:
        args += ["--hidden-import", mod]
    args.append("desktop_entry.py")

    print("[build] " + " ".join(args))
    subprocess.run(args, cwd=ROOT, check=True)

    built = ROOT / "dist" / f"review-api{EXE}"
    if not built.exists():
        print(f"[build] 未找到产物 {built}", file=sys.stderr)
        return 1

    BINARIES.mkdir(parents=True, exist_ok=True)
    dest = BINARIES / f"review-api-{target_triple()}{EXE}"
    shutil.copy2(built, dest)
    print(f"[build] sidecar -> {dest} ({dest.stat().st_size / 1024 / 1024:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
