"""Local preview and acceptance interface. No network command auto-confirms content."""
import argparse
import asyncio
import getpass
from hashlib import file_digest
import json
import os
from pathlib import Path
import sys

from pydantic import ValidationError

from app.material_review import MaterialError, load_profile, parse_document

from . import (AgentConfig, Approval, DeepSeekProvider, Failure, MemoryGateway, MockProvider, ReviewAgent, ReviewError,
               Selection, SystemCredentialStore, TaskInput, preview_scope)
from .images import LocalPptxImages
from .scope import ALLOWED_TEXT, DESTINATION
from .skills import SKILLS, describe_skill


def parser():
    parser = argparse.ArgumentParser(description="问赛任务 C：本地 Agent、审批预览与 DeepSeek 验收")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("configure-key", help="在系统密钥管理器中交互保存 DeepSeek key")
    commands.add_parser("key-status", help="检查专用系统凭据是否存在，不显示凭据")
    skill = commands.add_parser("skill", help="输出 Skill 合约")
    skill.add_argument("profile")
    inspect = commands.add_parser("inspect", help="列出材料可选择的内容块；仅本地读取")
    inspect.add_argument("file", type=Path)
    for command in ("preview", "run"):
        sub = commands.add_parser(command)
        sub.add_argument("file", type=Path)
        sub.add_argument("--profile", required=True)
        sub.add_argument("--selection", type=Path, required=True)
        sub.add_argument("--task-id", default="local-review")
        if command == "run":
            sub.add_argument("--provider", choices=("mock", "deepseek"), default="mock")
            sub.add_argument("--text-digest", required=True)
            sub.add_argument("--image-digest")
            sub.add_argument("--config", type=Path)
    return parser


def _print(value, stream=sys.stdout):
    stream.buffer.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def _task(args, doc, approval=None, *, revision_id):
    return TaskInput(task_id=args.task_id, revision_id=revision_id, profile_id=args.profile, document=doc,
                     selection=Selection.model_validate_json(args.selection.read_bytes()), approval=approval)


def main():
    args = parser().parse_args()
    try:
        if args.command == "configure-key":
            if not sys.stdin.isatty():
                raise ReviewError("interactive_terminal_required", "请在交互式终端配置凭据，勿通过参数、脚本或聊天提供。")
            SystemCredentialStore().write(getpass.getpass("DeepSeek API Key: "))
            _print({"credential_configured": True})
            return 0
        if args.command == "key-status":
            try:
                SystemCredentialStore().read()
            except ReviewError as exc:
                if exc.code != "credential_missing":
                    raise
                _print({"credential_configured": False})
                return 0
            _print({"credential_configured": True})
            return 0
        if args.command == "skill":
            profile = load_profile(args.profile)
            _print(describe_skill(SKILLS[profile["material_type"]], profile))
            return 0
        # Hash the file around parsing so the CLI never binds old parsed text to a newer local revision.
        with args.file.open("rb") as f:
            revision = file_digest(f, "sha256").hexdigest()
        doc = parse_document(args.file).to_dict()
        with args.file.open("rb") as f:
            if revision != file_digest(f, "sha256").hexdigest():
                raise ReviewError("material_changed", "文件在解析过程中发生变化，请重新打开。")
        if args.command == "inspect":
            blocks = [{"block_id": b["id"], "type": b["type"], "source": b["source"],
                       "characters": len(b["text"]), "text_preview": b["text"][:160]}
                      for b in doc["blocks"] if b["type"] in ALLOWED_TEXT and b["text"].strip()]
            images = [{"block_id": b["id"], "source": b["source"], "mime_type": b["attrs"].get("mime_type"),
                       "bytes": b["attrs"].get("bytes")} for b in doc["blocks"]
                      if doc["format"] == "pptx" and b["type"] == "image" and b["attrs"].get("available")]
            _print({"revision_id": revision, "text_candidates": blocks, "image_candidates": images})
        elif args.command == "preview":
            result = preview_scope(_task(args, doc, revision_id=revision))
            _print({"external_provider": DESTINATION, **result.model_dump(mode="json")})
        else:
            approval = Approval(text_digest=args.text_digest, image_digest=args.image_digest)
            task = _task(args, doc, approval, revision_id=revision)
            config = AgentConfig.model_validate_json(args.config.read_bytes()) if args.config else AgentConfig()
            gateway = MemoryGateway([task])
            provider = MockProvider() if args.provider == "mock" else DeepSeekProvider(config)
            runner = ReviewAgent(gateway, provider, config, image_reader=LocalPptxImages(args.file))
            result = asyncio.run(runner.run(args.task_id))
            record = {**result.model_dump(mode="json"), "audit": [x.model_dump(mode="json") for x in gateway.attempts]}
            _print(record)
            return 2 if isinstance(result, Failure) else 0
    except (ReviewError, ValidationError, MaterialError, OSError, ValueError) as exc:
        if isinstance(exc, (ReviewError, MaterialError)):
            error = {"code": exc.code, "message": str(exc)}
        elif isinstance(exc, OSError):
            error = {"code": "file_unavailable", "message": "无法读取本地文件。"}
        else:
            error = {"code": "invalid_cli_input", "message": "本地选择、评审配置或确认摘要的格式无效。"}
        _print({"error": error}, sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    os.environ["PYMUPDF_MESSAGE"] = "logging:level=10"
    os.environ["PYMUPDF_LOG"] = "logging:level=10"
    os.environ["PYMUPDF_SUGGEST_LAYOUT_ANALYZER"] = "0"
    raise SystemExit(main())
