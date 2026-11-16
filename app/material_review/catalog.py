"""Versioned profile and knowledge catalog used from A, C and the CLI."""
from hashlib import sha256
import json
from pathlib import Path
import re

from jsonschema import Draft202012Validator, SchemaError, ValidationError

from .model import MaterialError
from .rules import HANDLERS

ROOT = Path(__file__).resolve().parent
PROFILE_ID = re.compile(r"[a-z][a-z0-9-]+-v([1-9]\d*)", re.ASCII)
FORMATS = ("docx", "pptx", "pdf", "txt", "markdown")
MATERIALS = {"academic_paper", "competition_proposal", "ppt_defense"}


def _read(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise MaterialError("invalid_catalog", f"不能读取配置 {path.name}：{exc}") from exc


def _schema_check(schema, instance, label):
    try:
        Draft202012Validator(schema).validate(instance)
    except ValidationError as exc:
        path = ".".join(map(str, exc.absolute_path)) or "root"
        raise MaterialError("invalid_schema_data", f"{label} 的 {path} 不符合约定：{exc.message}") from exc


def _params_schema(properties, optional=()):
    return {"type": "object", "required": sorted(set(properties) - set(optional)), "properties": properties, "additionalProperties": False}


_POS_INT = {"type": "integer", "minimum": 1}
_PT = {"type": "number", "exclusiveMinimum": 0, "maximum": 400}
_NONEMPTY = {"type": "string", "minLength": 1}
PARAM_SCHEMAS = {
    "word_fonts": _params_schema({"eastAsia": _NONEMPTY, "latin": _NONEMPTY}),
    "word_size": _params_schema({"pt": {"type": "number", "minimum": 1, "maximum": 200, "multipleOf": 0.5}}),
    "word_spacing": _params_schema({"kind": {"enum": ["auto", "exact", "atLeast"]}, "value": _PT}),
    "word_margins": _params_schema({side: {"type": "number", "minimum": 0, "maximum": 15} for side in ("top", "bottom", "left", "right")}),
    "sections": _params_schema({"required": {"type": "object", "minProperties": 1, "additionalProperties": {
        "type": "array", "items": _NONEMPTY, "minItems": 1, "uniqueItems": True}}}),
    "page_count": _params_schema({"min": _POS_INT, "max": _POS_INT}, optional=("min",)),
    "file_submission": _params_schema({"formats": {"type": "array", "items": {"enum": list(FORMATS)}, "uniqueItems": True, "minItems": 1}, "max_bytes": _POS_INT}),
    "slides_metrics": _params_schema({"max_chars": _POS_INT}),
    "slides_fonts": _params_schema({"title_pt": _PT, "body_pt": _PT}),
    "slides_hierarchy": _params_schema({"min_title_delta_pt": _PT}),
}
WORD_ONLY = {"word_fonts", "word_size", "word_spacing", "word_margins", "word_captions", "word_formula"}
SLIDES_ONLY = {"slides_metrics", "slides_fonts", "slides_hierarchy"}


def _validate_profile(profile, id):
    _schema_check(_read(ROOT / "schemas" / "profile.schema.json"), profile, id)
    if profile["id"] != id or profile["version"] != int(PROFILE_ID.fullmatch(id).group(1)):
        raise MaterialError("invalid_profile", f"{id} 的文件名、id 与 version 不一致。")
    dims = [item["id"] for item in profile["dimensions"]]
    if len(set(dims)) != len(dims) or sum(item["weight"] for item in profile["dimensions"]) != 100:
        raise MaterialError("invalid_profile", f"{id} 的维度 ID 必须唯一且权重合计 100。")
    rule_ids = set()
    for rule in profile["format_rules"]:
        handler = rule["handler"]
        if rule["id"] in rule_ids or handler not in HANDLERS:
            raise MaterialError("invalid_profile", f"{id} 有重复规则 ID 或未注册的处理器：{rule['id']}/{handler}。")
        rule_ids.add(rule["id"])
        _schema_check(PARAM_SCHEMAS.get(handler, _params_schema({})), rule["params"], f"{id}/{rule['id']}")
        if (handler in WORD_ONLY and rule["formats"] != ["docx"]) or (handler in SLIDES_ONLY and rule["formats"] != ["pptx"]):
            raise MaterialError("invalid_profile", f"{id}/{rule['id']} 的适用文件类型有误。")
        if handler == "page_count" and rule["params"].get("min", 1) > rule["params"]["max"]:
            raise MaterialError("invalid_profile", f"{id}/{rule['id']} 的页数范围有误。")
    try:
        schema = profile["output_schema"]
        Draft202012Validator.check_schema(schema)
        if schema["properties"]["profile_id"]["const"] != id or set(schema["properties"]["dimensions"]["items"]["properties"]["id"]["enum"]) != set(dims):
            raise ValueError("输出 schema 的 profile 或维度不匹配")
    except (SchemaError, KeyError, TypeError, ValueError) as exc:
        raise MaterialError("invalid_profile", f"{id} 的 output_schema 不可用：{exc}") from exc


def _locked(root):
    lock = _read(root / "profiles.lock.json")
    if not isinstance(lock, dict) or not lock or not all(
        PROFILE_ID.fullmatch(k) and isinstance(v, str) and re.fullmatch(r"[0-9a-f]{64}", v) for k, v in lock.items()
    ):
        raise MaterialError("invalid_profile_lock", "profile 锁文件缺失或不符合格式。")
    return lock


def load_profile(profile_id: str, *, profiles_dir=None):
    root = Path(profiles_dir) if profiles_dir else ROOT / "profiles"
    if not isinstance(profile_id, str) or not PROFILE_ID.fullmatch(profile_id):
        raise MaterialError("unknown_profile", f"无效的 profile ID：{profile_id}")
    lock = _locked(root)
    if profile_id not in lock:
        raise MaterialError("unknown_profile", f"未发布的 profile：{profile_id}")
    try:
        raw = (root / f"{profile_id}.json").read_bytes()
    except OSError as exc:
        raise MaterialError("invalid_profile", f"找不到已发布的 profile：{profile_id}") from exc
    # Normalize line endings so a standard Git checkout does not alter the digest.
    normalized = raw.replace(b"\r\n", b"\n")
    if sha256(normalized).hexdigest() != lock[profile_id]:
        raise MaterialError("profile_changed", f"已发布的 {profile_id} 被修改；请新增版本并保留旧版文件及其校验值。")
    try:
        profile = json.loads(normalized.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise MaterialError("invalid_profile", f"{profile_id} 不是有效的 UTF-8 JSON：{exc}") from exc
    _validate_profile(profile, profile_id)
    return profile


def list_profiles():
    return sorted(_locked(ROOT / "profiles"))


def load_knowledge(ids=None):
    from .parse import parse_document

    root = ROOT / "knowledge"
    index = _read(root / "index.json")
    schema = _read(ROOT / "schemas" / "knowledge.schema.json")
    _schema_check(schema, index, "知识库索引")
    items = index["items"]
    known = {item["id"]: item for item in items}
    if len(known) != len(items):
        raise MaterialError("invalid_knowledge", "知识库包含重复资料 ID。")
    for item in items:
        if item["kind"] == "official_reference":
            continue
        case = item["case"]
        ref = known.get(case["criteria_ref"])
        if ref is None or ref["kind"] != "official_reference" or ref["competition"] != item["competition"] or ref["year"] != item["year"]:
            raise MaterialError("invalid_knowledge", f"{item['id']} 的规则引用无效。")
        local = (root / item["source"]["path"]).resolve()
        allowed_root = (root / "instructional_cases").resolve()
        if allowed_root not in local.parents or local.suffix != ".md" or not local.is_file():
            raise MaterialError("invalid_knowledge", f"{item['id']} 的案例出处未归档。")
        by_id = {block.id: block for block in parse_document(local).blocks}
        loc = case["issue_location"]
        block = by_id.get(loc["source"]["path"])
        if (block is None or case["original_text"] not in block.text or loc["filename"] != item["source"]["path"]
                or block.source.line_start != loc["source"]["line_start"] or block.source.line_end != loc["source"]["line_end"]):
            raise MaterialError("invalid_knowledge", f"{item['id']} 的问题位置无法回到原文。")
    if ids is None:
        return list(known.values())
    missing = set(ids) - known.keys()
    if missing:
        raise MaterialError("invalid_knowledge", f"知识库引用不存在：{', '.join(sorted(missing))}")
    return [known[id] for id in ids]


def validate_catalog():
    root = ROOT / "profiles"
    names = list_profiles()
    actual = {path.stem for path in root.glob("*-v*.json")}
    if set(names) != actual:
        raise MaterialError("invalid_profile_lock", "profile 文件和发布锁不一致。")
    knowledge = {item["id"]: item for item in load_knowledge()}
    for id in names:
        profile = load_profile(id)
        for ref in profile["knowledge_refs"]:
            item = knowledge.get(ref)
            if item is None or profile["material_type"] not in item["material_types"]:
                raise MaterialError("invalid_knowledge", f"{id} 引用的 {ref} 不存在或不适用于该材料类型。")
    return {"profiles": names, "knowledge_entries": len(knowledge),
            "official_sources": sum(item["kind"] == "official_reference" for item in knowledge.values()),
            "instructional_cases": sum(item["kind"] == "instructional_case" for item in knowledge.values()),
            "authorized_cases": sum(item["kind"] == "authorized_case" for item in knowledge.values())}


def validate_review_output(output, profile_id, *, document=None):
    profile = load_profile(profile_id)
    _schema_check(profile["output_schema"], output, "评审结果")
    ids = [item["id"] for item in output["dimensions"]]
    if len(set(ids)) != len(ids):
        raise MaterialError("invalid_review_output", "每个评审维度只允许出现一次。")
    if document is None:
        return
    payload = document.to_dict() if hasattr(document, "to_dict") else document
    blocks = {b["id"]: b for b in payload["blocks"]}
    def normalize(value):
        return " ".join(value.split())
    for item in output["dimensions"]:
        for evidence in item["evidence"]:
            block = blocks.get(evidence["block_id"])
            if block is None or any(block["source"].get(k) != v for k, v in evidence["source"].items()):
                raise MaterialError("invalid_evidence", f"{item['id']} 的证据定位无法核对。")
            if evidence["excerpt"] is None:
                if block["type"] not in {"image", "table", "formula", "slide", "shape"}:
                    raise MaterialError("invalid_evidence", f"{item['id']} 的文字证据缺少原文引文。")
                continue
            lines = [block["text"]]
            lines.extend(cell["text"] for row in block["attrs"].get("rows", []) for cell in row)
            quote = normalize(evidence["excerpt"])
            if not quote or quote not in normalize("\n".join(lines)):
                raise MaterialError("invalid_evidence", f"{item['id']} 的证据引文无法从原文定位。")
    for action in output["priority_actions"]:
        if action["block_id"] is not None and action["block_id"] not in blocks:
            raise MaterialError("invalid_evidence", "优先建议引用了不存在的原文位置。")


def validate_document(document):
    payload = document.to_dict() if hasattr(document, "to_dict") else document
    _schema_check(_read(ROOT / "schemas" / "document.schema.json"), payload, "文档结构")
    ids = set()
    for block in payload["blocks"]:
        if block["id"] != block["source"]["path"] or block["id"] in ids or (block["parent_id"] is not None and block["parent_id"] not in ids):
            raise MaterialError("invalid_document_source", f"重复、无效或顺序错误的定位：{block['id']}")
        ids.add(block["id"])
