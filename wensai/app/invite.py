"""邀请码管理命令行。

    python -m app.invite create --uses 10 --days 30 --note "中期演示"
    python -m app.invite list
"""
from __future__ import annotations

import argparse
import secrets
from datetime import datetime, timedelta, timezone

from .config import Settings
from .db import connect, initialize, now


def _code() -> str:
    return "WS-" + secrets.token_hex(4).upper()


def main() -> int:
    parser = argparse.ArgumentParser(description="问赛邀请码管理")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="生成邀请码")
    create.add_argument("--uses", type=int, default=1, help="可使用次数")
    create.add_argument("--days", type=int, default=30, help="有效天数，0 表示长期")
    create.add_argument("--note", default="", help="备注，例如发给谁")
    sub.add_parser("list", help="列出邀请码")
    args = parser.parse_args()

    settings = Settings.from_env()
    initialize(settings.db_path)
    conn = connect(settings.db_path)
    try:
        if args.command == "create":
            code = _code()
            expires = ""
            if args.days > 0:
                expires = (datetime.now(timezone.utc) + timedelta(days=args.days)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
            conn.execute("INSERT INTO invite_codes(code,max_uses,used_count,expires_at,note,created_at) VALUES (?,?,0,?,?,?)",
                         (code, args.uses, expires, args.note, now()))
            print(f"邀请码：{code}")
            print(f"可用次数：{args.uses}　有效期：{'长期' if not expires else args.days} 天")
            print("把邀请码发给对方，他打开网页注册时填写。")
            return 0
        rows = conn.execute("SELECT code,max_uses,used_count,expires_at,note FROM invite_codes ORDER BY created_at DESC").fetchall()
        if not rows:
            print("还没有邀请码。用 python -m app.invite create 生成。")
            return 0
        print(f"{'邀请码':<14}{'已用/上限':<12}{'过期时间':<26}备注")
        for row in rows:
            print(f"{row['code']:<14}{row['used_count']}/{row['max_uses']:<9}{row['expires_at'] or '长期':<26}{row['note'] or ''}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
