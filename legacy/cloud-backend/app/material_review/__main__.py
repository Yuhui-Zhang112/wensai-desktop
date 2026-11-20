"""Reference command-line interface for local verification and integration."""
import argparse
import json
import os
from pathlib import Path
import sys

from . import (MaterialError, build_review_input, check_document, fix_docx, load_knowledge, load_profile, parse_document,
               validate_catalog, validate_document, validate_review_output)


def _parser():
    parser = argparse.ArgumentParser(description="问赛任务 B：解析、检查、调整、评审配置校验")
    sub = parser.add_subparsers(dest="command", required=True)
    for action in ("parse", "check", "review-input"):
        p = sub.add_parser(action)
        p.add_argument("file", type=Path)
        p.add_argument("--encoding")
        if action != "parse":
            p.add_argument("--profile", required=True)
            p.add_argument("--rendered-page-count", type=int)
    adjust = sub.add_parser("fix-docx")
    adjust.add_argument("file", type=Path)
    adjust.add_argument("destination", type=Path)
    adjust.add_argument("--profile", required=True)
    adjust.add_argument("--rule", action="append")
    sub.add_parser("validate-profiles")
    show = sub.add_parser("profile")
    show.add_argument("id")
    sub.add_parser("knowledge")
    review = sub.add_parser("validate-output")
    review.add_argument("json_file", type=Path)
    review.add_argument("--profile", required=True)
    review.add_argument("--material", type=Path)
    return parser


def main():
    args = _parser().parse_args()
    try:
        if args.command == "validate-profiles":
            result = validate_catalog()
        elif args.command == "profile":
            result = load_profile(args.id)
        elif args.command == "knowledge":
            result = load_knowledge()
        elif args.command == "review-input":
            result = build_review_input(args.file, args.profile, encoding=args.encoding, rendered_page_count=args.rendered_page_count)
        elif args.command == "fix-docx":
            result = fix_docx(args.file, args.destination, args.profile, selected_rule_ids=args.rule)
        elif args.command == "validate-output":
            result = json.loads(args.json_file.read_text(encoding="utf-8-sig"))
            document = parse_document(args.material) if args.material else None
            validate_review_output(result, args.profile, document=document)
            result = {"valid": True, "profile_id": args.profile}
        else:
            parsed = parse_document(args.file, encoding=args.encoding)
            validate_document(parsed)
            result = parsed.to_dict() if args.command == "parse" else check_document(
                parsed, args.profile, rendered_page_count=args.rendered_page_count)
    except (MaterialError, OSError, ValueError) as exc:
        error = {"error": {"code": getattr(exc, "code", "operation_failed"), "message": str(exc)}}
        sys.stderr.buffer.write((json.dumps(error, ensure_ascii=False) + "\n").encode("utf-8"))
        return 2
    sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))
    return 0


if __name__ == "__main__":
    # Route optional PyMuPDF diagnostics away from the machine-readable streams.
    os.environ["PYMUPDF_MESSAGE"] = "logging:level=10"
    os.environ["PYMUPDF_LOG"] = "logging:level=10"
    os.environ["PYMUPDF_SUGGEST_LAYOUT_ANALYZER"] = "0"
    raise SystemExit(main())
