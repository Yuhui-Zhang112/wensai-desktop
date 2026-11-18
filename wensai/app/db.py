"""SQLite 连接、短写事务、版本迁移和离线初始化入口。"""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .config import PROJECT_ROOT, Settings

MIGRATIONS = PROJECT_ROOT / "migrations"


def now() -> str:
    """ISO 8601 UTC 时间，按时间排序时可以直接比较字符串。"""
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def new_id() -> str:
    return str(uuid4())


def connect(db_path: str | Path) -> sqlite3.Connection:
    # FastAPI 可在不同线程中进入和退出同步依赖，每个请求仍拥有独立的连接。
    conn = sqlite3.connect(db_path, timeout=10.0, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=FULL")
    except BaseException:
        conn.close()
        raise
    return conn


@contextmanager
def session(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """先获取写锁，再读取队列状态或分配事件序号。异常退出时整体回滚。"""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _statements(script: str) -> Iterator[str]:
    # executescript 会隐式提交。逐语句执行可将表、触发器和版本号一起提交。
    lines: list[str] = []
    for line in script.splitlines(keepends=True):
        lines.append(line)
        if sqlite3.complete_statement("".join(lines)):
            yield "".join(lines)
            lines.clear()
    if any(line.strip() and not line.lstrip().startswith("--") for line in lines):
        raise ValueError("迁移脚本末尾存在未完成的 SQL 语句")


def initialize(db_path: str | Path) -> None:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    scripts = sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql"))
    versions = [int(script.name.split("_", 1)[0]) for script in scripts]
    if not scripts or versions != list(range(1, len(scripts) + 1)):
        raise RuntimeError("数据库迁移脚本缺失，或版本号不连续")
    with session(path) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if journal_mode.lower() != "wal":
            raise RuntimeError("无法启用 SQLite WAL，请使用本机磁盘")
        with transaction(conn):
            current = conn.execute("PRAGMA user_version").fetchone()[0]
            if current > len(scripts):
                raise RuntimeError("此数据库的版本高于当前程序支持的版本")
            for version, script in zip(versions[current:], scripts[current:]):
                for sql in _statements(script.read_text(encoding="utf-8")):
                    conn.execute(sql)
                conn.execute(f"PRAGMA user_version={version}")


def main() -> None:
    parser = argparse.ArgumentParser(description="问赛 SQLite 数据库初始化与迁移")
    parser.add_argument("--db", type=Path, help="目标 SQLite 文件，默认读取服务配置")
    args = parser.parse_args()
    path = args.db.resolve() if args.db else Settings.from_env().db_path
    initialize(path)
    print(f"数据库初始化完成：{path}")


if __name__ == "__main__":
    main()
