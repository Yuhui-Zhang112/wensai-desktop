"""Authorization is bound to the exact excerpts and image bytes, not a file name."""
from hashlib import sha256
from hmac import compare_digest
import json

from app.material_review import MaterialError, validate_document

from .models import ImagePreview, ReviewError, ScopePreview, SourceRef, TaskInput, TextPreview

ALLOWED_TEXT = {"title", "heading", "paragraph", "cell", "formula"}
MAX_TEXT_BYTES = 375000
DESTINATION = "https://api.deepseek.com/chat/completions"


def json_text(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(obj):
    return sha256(json_text(obj).encode("utf-8")).hexdigest()


def preview_scope(task: TaskInput) -> ScopePreview:
    try:
        validate_document(task.document)
    except MaterialError as exc:
        raise ReviewError("invalid_document", "无法验证 B 提供的材料结构和原文定位，请重新解析。") from exc
    blocks = {b["id"]: b for b in task.document["blocks"]}
    spans = []
    occupied = {}
    nbytes = 0
    for selected in task.selection.text:
        block = blocks.get(selected.block_id)
        if block is None or block["type"] not in ALLOWED_TEXT:
            raise ReviewError("invalid_scope", "选段不是可发送的文字块。")
        original = block["text"]
        end = len(original) if selected.end is None else selected.end
        if not selected.start < end <= len(original):
            raise ReviewError("invalid_scope", "选段超出了原文范围。")
        content = original[selected.start:end]
        if not content.strip():
            raise ReviewError("invalid_scope", "不能确认空白选段。")
        earlier = occupied.setdefault(selected.block_id, [])
        if any(max(s, selected.start) < min(e, end) for s, e in earlier):
            raise ReviewError("invalid_scope", "同一文字块的选段不能重叠。")
        earlier.append((selected.start, end))
        nbytes += len(content.encode("utf-8"))
        if nbytes > MAX_TEXT_BYTES:
            raise ReviewError("scope_too_large", "已选文本超过 375000 UTF-8 字节；请缩小范围后重新确认。")
        spans.append(TextPreview(block_id=block["id"], kind=block["type"], source=SourceRef.model_validate(block["source"]),
                                 start=selected.start, end=end, text=content))
    images = []
    if len(set(task.selection.images)) != len(task.selection.images):
        raise ReviewError("invalid_image_scope", "所选 PPT 图片重复。")
    for block_id in task.selection.images:
        block = blocks.get(block_id)
        if task.document["format"] != "pptx" or not block or block["type"] != "image":
            raise ReviewError("invalid_image_scope", "仅能选择 B 定位的 PPT 图片。")
        attrs = block["attrs"]
        mime = attrs.get("mime_type")
        if not attrs.get("available") or mime not in {"image/jpeg", "image/png"} or not attrs.get("sha256"):
            raise ReviewError("image_unsupported", "首版仅支持已内嵌的 PNG 或 JPEG；不会下载外链或转换原文件。")
        images.append(ImagePreview(block_id=block_id, source=SourceRef.model_validate(block["source"]), sha256=attrs["sha256"],
                                   mime_type=mime, bytes=attrs["bytes"], alt=attrs.get("alt")))
    key = {"contract": "wen-sai-c/1", "destination": DESTINATION, "task": task.task_id,
           "revision": task.revision_id, "profile": task.profile_id}
    return ScopePreview(task_id=task.task_id, revision_id=task.revision_id, profile_id=task.profile_id, text=spans, images=images,
                        text_digest=digest([key, "text", [s.model_dump(mode="json") for s in spans]]),
                        image_digest=digest([key, "images", [i.model_dump(mode="json") for i in images]]) if images else None)


def confirm_scope(task, scope):
    approval = task.approval
    if approval is None or not compare_digest(scope.text_digest, approval.text_digest):
        raise ReviewError("text_confirmation_required", "文本范围未确认或已经变化，请重新查看并确认。")
    expected = scope.image_digest
    confirmed = approval.image_digest
    if (expected and (not confirmed or not compare_digest(expected, confirmed))) or (not expected and confirmed):
        raise ReviewError("image_confirmation_required", "PPT 图片未单独确认或已经变化，请重新确认或取消选择。")
