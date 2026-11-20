"""Fixed review pipeline. No agent commands, file changes or external tool execution."""
import asyncio
from collections import defaultdict
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from time import monotonic
from typing import Protocol

from pydantic import ValidationError

from app.material_review import MaterialError, load_knowledge, load_profile, validate_review_output

from .models import (AgentConfig, Attempt, ChunkReview, Evidence, Failure, Issue, Location, ReviewError, ReviewResult,
                     RunMeta, SuggestionDraft, utcnow)
from .prompt import plan_chunks
from .scope import confirm_scope, digest, preview_scope
from .skills import select_skill

IMPACT = {"invalidates": "high", "weakens": "medium", "presentation": "low"}
ORDER = {"high": 0, "medium": 1, "low": 2}
RETRY_HINTS = {
    "invalid_criterion": "\n重新输出：criterion 只能复制 standards 中的 id；standard_index 只能复制该 id 的一个 options.index。不要填写序号或自造 ID。",
    "invalid_evidence": "\n重新输出：逐字复制本次片段里的连续原文及对应 ref；无法核对的项直接省略。",
    "invalid_output": "\n重新输出：只返回包含 dimensions 和 issues 两个数组的 JSON 对象；只使用规定的字段。",
}


class ImageReader(Protocol):
    def __call__(self, image) -> bytes: ...


class Provider(Protocol):
    name: str
    model: str

    async def complete(self, chunk, *, image_bytes=None) -> str: ...


def _unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _json_constant(_):
    raise ValueError("invalid JSON constant")


def _approved_images(scope, config, reader):
    result = {}
    if scope.images and reader is None:
        raise ReviewError("image_unavailable", "当前没有可读取所选 PPT 图片的本地接口。")
    for image in scope.images:
        if not 0 < image.bytes <= config.max_image_bytes:
            raise ReviewError("image_too_large", "选中的 PPT 图片超过单图上限，请取消选择或提交适当大小的副本。")
        try:
            raw = reader(image)
        except Exception as exc:
            raise ReviewError("image_unavailable", "无法读取所选 PPT 图片，请重新解析材料。") from exc
        if not isinstance(raw, bytes):
            raise ReviewError("image_changed", "读取的图片格式无效，请重新解析和确认。")
        signature_ok = raw.startswith(b"\x89PNG\r\n\x1a\n") if image.mime_type == "image/png" else raw.startswith(b"\xff\xd8\xff")
        if not signature_ok or len(raw) != image.bytes or sha256(raw).hexdigest() != image.sha256:
            raise ReviewError("image_changed", "选中的 PPT 图片与确认时不一致，请重新解析和确认。")
        result[image.block_id] = raw
    return result


@dataclass(frozen=True)
class Grounded:
    location: Location
    evidence: Evidence

    def b_evidence(self):
        return {"block_id": self.location.block_id, "source": self.location.source.model_dump(mode="json"), "excerpt": self.evidence.quote}

    def key(self):
        return self.location.block_id, self.location.char_start, self.location.char_end, self.evidence.image_sha256


def _ground(claim, chunk, fragments):
    span = fragments.get(claim.ref)
    if span is not None and claim.quote and claim.quote.strip():
        offset = span.text.find(claim.quote)
        if offset >= 0:
            start = span.start + offset
            return Grounded(Location(block_id=span.block_id, source=span.source, char_start=start, char_end=start + len(claim.quote)),
                            Evidence(kind="text", quote=claim.quote))
    if chunk.image and claim.ref == chunk.image[0] and claim.quote is None:
        img = chunk.image[1]
        return Grounded(Location(block_id=img.block_id, source=img.source),
                        Evidence(kind="image", quote=None, image_sha256=img.sha256))
    raise ReviewError("invalid_evidence", "评审引用无法对应到本次确认的原文或图片。", retriable=True)


def _checked_chunk(raw, chunk, profile, max_bytes):
    try:
        if not isinstance(raw, str) or not raw.strip():
            raise ReviewError("empty_output", "模型没有返回评审文本。", retriable=True)
        if len(raw.encode("utf-8")) > max_bytes:
            raise ReviewError("response_too_large", "模型输出超过大小上限。", retriable=True)
        shaped = ChunkReview.model_validate(json.loads(raw, object_pairs_hook=_unique, parse_constant=_json_constant))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ReviewError("invalid_output", "模型返回的内容不符合评审 JSON 结构。", retriable=True) from exc
    dimensions = {d["id"]: d for d in profile["dimensions"]}
    fragments = {f.ref: f for f in chunk.fragments}
    seen = set()
    candidates, issues = [], []
    for finding in shaped.dimensions:
        if finding.criterion in seen or finding.criterion not in dimensions:
            raise ReviewError("invalid_criterion", "模型返回了未知或重复的评分维度。", retriable=True)
        seen.add(finding.criterion)
        grounded = [_ground(claim, chunk, fragments) for claim in finding.evidence]
        cites = {ref.key(): ref for ref in grounded}
        candidates.append((finding, list(cites.values())))
    for finding in shaped.issues:
        criterion = dimensions.get(finding.criterion)
        if criterion is None or finding.standard_index >= len(criterion["criteria"]):
            raise ReviewError("invalid_criterion", "模型引用的评审标准不属于当前配置。", retriable=True)
        ref = _ground(finding.evidence, chunk, fragments)
        signature = [finding.criterion, finding.standard_index, ref.key()]
        issues.append(Issue(id="issue-" + digest(signature)[:24], location=ref.location, severity=IMPACT[finding.impact],
                            criterion=criterion["id"], criterion_name=criterion["name"], standard_index=finding.standard_index,
                            review_standard=criterion["criteria"][finding.standard_index], evidence=ref.evidence, suggestion=finding.suggestion))
    return candidates, issues


def _clashes(issue, kept):
    a, b = issue.location, kept.location
    if (issue.criterion, issue.standard_index, a.block_id) != (kept.criterion, kept.standard_index, b.block_id):
        return False
    if a.char_start is None or b.char_start is None:
        return a.char_start is None and b.char_start is None
    common = min(a.char_end, b.char_end) - max(a.char_start, b.char_start)
    return common > 0 and common >= 0.6 * min(a.char_end - a.char_start, b.char_end - b.char_start)


def _merge(task, profile, results, meta):
    dimensions = defaultdict(list)
    issues = []
    for candidate_rows, issue_rows in results:
        for finding, evidence in candidate_rows:
            dimensions[finding.criterion].append((finding, evidence))
        issues.extend(issue_rows)
    kept = []
    for issue in sorted(issues, key=lambda item: (ORDER[item.severity], item.location.block_id, item.location.char_start or 0, item.id)):
        if not any(_clashes(issue, prior) for prior in kept):
            kept.append(issue)

    rows = []
    for d in profile["dimensions"]:
        id = d["id"]
        candidates = dimensions.get(id, [])
        if not candidates:
            rows.append({"id": id, "status": "insufficient_evidence", "score": None,
                         "rationale": "已确认且成功评审的范围内无可引用证据。", "evidence": [], "suggestions": []})
            continue
        evidence, used_rows = {}, []
        for finding, cites in candidates:
            new = [(ref.key(), ref) for ref in cites if ref.key() not in evidence]
            if new:
                used_rows.append(finding)
                evidence.update(new)
        # Each chunk with new evidence contributes one score; overlapping citations do not vote twice.
        score = round(sum(row.score for row in used_rows) / len(used_rows))
        rationale = "；".join(dict.fromkeys(row.rationale for row in used_rows[:3]))[:1400]
        suggestions = list(dict.fromkeys(item.suggestion for item in kept if item.criterion == id))[:6]
        rows.append({"id": id, "status": "evaluated", "score": score, "rationale": rationale,
                     "evidence": [ref.b_evidence() for ref in list(evidence.values())[:8]], "suggestions": suggestions})
    count = sum(r["score"] is not None for r in rows)
    lead = "Mock：固定教学样例，仅供验收。" if meta.provider == "mock" else "DeepSeek：只评审已确认的材料范围。"
    review = {"profile_id": profile["id"], "summary": f"{lead} {count}/{len(rows)} 个维度有证据，发现 {len(kept)} 条去重问题。",
              "dimensions": rows, "priority_actions": [{"priority": i.severity, "action": i.suggestion, "block_id": i.location.block_id}
                                                       for i in kept[:10]]}
    try:
        validate_review_output(review, profile["id"], document=task.document)
    except MaterialError as exc:
        raise ReviewError("invalid_review", "合并结果无法通过 B 的结构或证据校验。") from exc
    weights = {d["id"]: d["weight"] for d in profile["dimensions"]}
    total = round(sum(item["score"] * weights[item["id"]] for item in rows) / 10, 1) if count == len(rows) else None
    return ReviewResult(meta=meta, review=review, issues=kept, total_score=total)


class ReviewAgent:
    def __init__(self, gateway, provider: Provider, config: AgentConfig | None = None, *, image_reader: ImageReader | None = None):
        self.gateway = gateway
        self.provider = provider
        self.config = config or getattr(provider, "config", None) or AgentConfig()
        if getattr(provider, "config", self.config) != self.config:
            raise ValueError("Provider and agent must share the same configuration.")
        self.image_reader = image_reader

    async def preview(self, task_id):
        return preview_scope(await self.gateway.load(task_id))

    async def _attempt(self, chunk, task, profile, skill, images, deadline):
        raw_config = self.config
        request_chunk = chunk
        for attempt in range(1, 2 + raw_config.retries):
            remaining = deadline - monotonic()
            if remaining <= 0:
                raise ReviewError("task_timeout", "评审超过任务总时限。")
            start, requested = monotonic(), utcnow()
            status = "failed"
            error = None
            http_status = None
            try:
                async with asyncio.timeout(min(raw_config.timeout_seconds, remaining)):
                    raw = await self.provider.complete(request_chunk, image_bytes=images[chunk.image[1].block_id] if chunk.image else None)
                if self.provider.name == "deepseek":
                    http_status = 200
                checked = _checked_chunk(raw, chunk, profile, raw_config.max_response_bytes)
                status = "completed"
            except ReviewError as exc:
                error = exc
            except TimeoutError:
                error = ReviewError("provider_timeout", "模型请求超时。", retriable=True)
            except Exception:
                error = ReviewError("provider_failure", "评审服务运行异常。")
            await self.gateway.audit(Attempt(task_id=task.task_id, profile_id=profile["id"], profile_version=profile["version"],
                skill_id=skill.id, skill_version=skill.version, model=self.provider.model, chunk=chunk.number, attempt=attempt,
                request_time=requested, duration_ms=round((monotonic() - start) * 1000), status=status,
                error_code=error.code if error else None,
                http_status=error.http_status if error and error.http_status is not None else http_status,
                input_bytes=request_chunk.input_bytes, image_count=int(chunk.image is not None)))
            if error is None:
                return checked
            if not error.retriable or attempt > raw_config.retries:
                raise error
            hint = RETRY_HINTS.get(error.code, "")
            expanded = chunk.input_bytes + len(hint.encode("utf-8"))
            request_chunk = replace(chunk, system=chunk.system + hint, input_bytes=expanded) if expanded <= raw_config.input_limit_bytes else chunk
            delay = min(0.2 * 2 ** (attempt - 1), 1.6)
            if monotonic() + delay >= deadline:
                raise ReviewError("task_timeout", "评审超过任务总时限。")
            await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    async def run(self, task_id):
        task = await self.gateway.load(task_id)
        profile = skill = None
        setup_error = None
        try:
            profile = load_profile(task.profile_id)
            skill = select_skill(profile, task.document.get("format"))
        except (MaterialError, ReviewError) as exc:
            setup_error = ReviewError("profile_invalid", "无法加载评审配置。") if isinstance(exc, MaterialError) else exc
        meta = RunMeta(task_id=task.task_id, revision_id=task.revision_id, profile_id=task.profile_id,
                       profile_version=profile["version"] if profile else None, skill_id=skill.id if skill else None,
                       skill_version=skill.version if skill else None, provider=self.provider.name,
                       model=self.provider.model, started_at=utcnow(), status="running")
        if not await self.gateway.claim(task, meta):
            raise ReviewError("task_conflict", "任务已被执行，或确认后内容变化。")
        deadline = monotonic() + self.config.task_timeout_seconds
        try:
            if setup_error:
                raise setup_error
            scope = preview_scope(task)
            confirm_scope(task, scope)
            if scope.images and self.provider.name == "deepseek" and self.provider.model != "deepseek-flash":
                raise ReviewError("model_no_vision", "当前模型不支持图片。请切换 deepseek-flash 或仅确认文本。")
            images = _approved_images(scope, self.config, self.image_reader)
            library = load_knowledge(profile["knowledge_refs"])
            chunks = plan_chunks(scope, profile, skill, library, self.config)
            meta = meta.model_copy(update={"text_count": len(scope.text), "image_count": len(images), "chunk_count": len(chunks),
                                           "reference_ids": sorted({ref for chunk in chunks for ref in chunk.references})})
            checked = []
            for chunk in chunks:
                checked.append(await self._attempt(chunk, task, profile, skill, images, deadline))
            if monotonic() >= deadline:
                raise ReviewError("task_timeout", "评审超过任务总时限。")
            result = _merge(task, profile, checked, meta.model_copy(update={"status": "completed", "finished_at": utcnow()}))
            await self.gateway.complete(result)
            return result
        except asyncio.CancelledError:
            failure = Failure(meta=meta.model_copy(update={"status": "failed", "finished_at": utcnow()}),
                              code="task_cancelled", message="评审任务已取消。")
            await asyncio.shield(self.gateway.fail(failure))
            raise
        except (MaterialError, ReviewError, ValidationError) as exc:
            error = exc if isinstance(exc, ReviewError) else ReviewError("invalid_review_data", "评审输入或输出无法校验。")
        except Exception:
            error = ReviewError("review_failed", "评审未完成，请重试或检查本地评审服务。")
        failure = Failure(meta=meta.model_copy(update={"status": "failed", "finished_at": utcnow()}), code=error.code, message=str(error))
        await self.gateway.fail(failure)
        return failure


def edit_suggestion(result: ReviewResult, issue_id: str, suggestion: str, *, previous: SuggestionDraft | None = None):
    """Produce a user-edited suggestion diff for A; never touch source files or the saved review."""
    issue = next((item for item in result.issues if item.id == issue_id), None)
    if issue is None:
        raise ReviewError("unknown_issue", "找不到评审问题。")
    if previous and (previous.issue_id, previous.task_id, previous.revision_id) != (issue.id, result.meta.task_id, result.meta.revision_id):
        raise ReviewError("draft_conflict", "建议草稿不属于此原文版本或评审问题。")
    try:
        return SuggestionDraft(task_id=result.meta.task_id, revision_id=result.meta.revision_id, issue_id=issue.id,
                               version=previous.version + 1 if previous else 1,
                               previous=previous.suggestion if previous else issue.suggestion, suggestion=suggestion)
    except ValidationError as exc:
        raise ReviewError("suggestion_invalid", "修改建议不能为空，长度不得超过 700 字。") from exc
