import asyncio
from copy import deepcopy
from hashlib import sha256
import json
import subprocess
import sys

import httpx
import pytest

from app.material_review import load_knowledge, load_profile, validate_review_output
from app.review_agent import (AgentConfig, Approval, DeepSeekProvider, Failure, MemoryGateway, MockProvider, ReviewAgent,
                              ReviewError, Selection, TextSlice, edit_suggestion, preview_scope)
from app.review_agent.images import LocalPptxImages
from app.review_agent.prompt import plan_chunks
from app.review_agent.skills import retrieve, select_skill
from task_c_tests.samples import OFF_SCOPE, make_samples, make_task


@pytest.fixture(scope="session")
def samples(tmp_path_factory):
    path = tmp_path_factory.mktemp("c_materials")
    make_samples(path)
    return path


@pytest.fixture
def test_config():
    return AgentConfig(timeout_seconds=0.08, task_timeout_seconds=2.0, retries=1)


class TestStore:
    __test__ = False
    calls = 0
    hidden = "only-in-authorization-header"

    def read(self):
        self.calls += 1
        return self.hidden


def completed(content):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})


def model_text(payload, *, criterion="methodology", quote=None, issue=True):
    item = payload["approved_text"][0]
    ev = {"ref": item["ref"], "quote": quote or item["text"]}
    dim = {"criterion": criterion, "score": 4, "rationale": "只依据当前片段核对。", "evidence": [ev]}
    row = {"criterion": criterion, "standard_index": 0, "impact": "weakens", "evidence": ev, "suggestion": "增加可重复的验证步骤。"}
    return json.dumps({"dimensions": [dim], "issues": [row] if issue else []}, ensure_ascii=False)


def user_payload(request):
    body = json.loads(request.content)
    user = body["messages"][1]["content"]
    return body, json.loads(user if isinstance(user, str) else user[0]["text"])


def with_approval(task):
    scope = preview_scope(task)
    return task.model_copy(update={"approval": Approval(text_digest=scope.text_digest, image_digest=scope.image_digest)})


def deep(task, config, transport, *, reader=None, store=None, gateway=None):
    store = store or TestStore()
    gateway = gateway or MemoryGateway([task])
    provider = DeepSeekProvider(config, transport=httpx.MockTransport(transport), credentials=store)
    result = asyncio.run(ReviewAgent(gateway, provider, image_reader=reader).run(task.task_id))
    return result, gateway, store


@pytest.mark.parametrize("name,criterion,severity,location,number", [
    ("paper.docx", "methodology", "high", "paragraph", 4),
    ("proposal.pdf", "budget", "medium", "page", 2),
    ("defense.pptx", "pacing", "medium", "slide", 2),
])
def test_mock_closed_loop_and_manual_anchors(samples, name, criterion, severity, location, number):
    file = samples / name
    original = sha256(file.read_bytes()).hexdigest()
    task = make_task(file)
    gateway = MemoryGateway([task])
    outcome = asyncio.run(ReviewAgent(gateway, MockProvider()).run(task.task_id))
    assert gateway.states[task.task_id] == "completed"
    assert len(outcome.issues) == 1
    item = outcome.issues[0]
    assert (item.criterion, item.severity, getattr(item.location.source, location)) == (criterion, severity, number)
    assert item.review_standard == next(x["criteria"][0] for x in load_profile(task.profile_id)["dimensions"] if x["id"] == criterion)
    block = next(b for b in task.document["blocks"] if b["id"] == item.location.block_id)
    assert block["text"][item.location.char_start:item.location.char_end] == item.evidence.quote
    assert outcome.meta.profile_version == 1 and outcome.meta.skill_version == 1
    assert outcome.total_score is None
    validate_review_output(outcome.review, task.profile_id, document=task.document)
    draft = edit_suggestion(outcome, item.id, "补充一段可执行的复核步骤。")
    revised = edit_suggestion(outcome, item.id, "列出三次相互独立的复核记录。", previous=draft)
    assert draft.version == 1 and revised.version == 2 and revised.previous == draft.suggestion
    assert outcome.issues[0].suggestion == draft.previous
    assert sha256(file.read_bytes()).hexdigest() == original


def test_actual_client_body_is_scoped_and_audit_contains_no_material(samples, test_config):
    task = make_task(samples / "paper.docx")
    sent = []
    def transport(request):
        sent.append(request)
        assert str(request.url) == "https://api.deepseek.com/chat/completions"
        assert request.headers["Authorization"] == "Bearer " + TestStore.hidden
        assert "未授权片段" not in request.content.decode()
        body, payload = user_payload(request)
        assert "tools" not in body and "files" not in body
        assert body["response_format"] == {"type": "json_object"}
        assert body["thinking"] == {"type": "disabled"}
        assert payload["approved_text"] == [{"kind": "paragraph", "ref": "t1", "text": task.document["blocks"][-1]["text"][task.selection.text[0].start:]}]
        assert "word/document.xml" not in request.content.decode()
        return completed(model_text(payload))
    result, gateway, store = deep(task, test_config, transport)
    assert store.calls == 1 and len(sent) == 1 and result.meta.status == "completed"
    assert gateway.results[task.task_id] == result
    audit = gateway.attempts[0].model_dump_json()
    assert not any(text in audit for text in ["所有实验", TestStore.hidden, OFF_SCOPE])
    assert gateway.attempts[0].http_status == 200 and gateway.attempts[0].request_time


def test_unconfirmed_changed_text_and_image_send_nothing(samples, test_config):
    calls = []
    def transport(request):
        calls.append(request)
        return completed("{}")
    unchecked = make_task(samples / "paper.docx", approval=False)
    changed = make_task(samples / "paper.docx")
    doc = deepcopy(changed.document)
    doc["blocks"][-1]["text"] = doc["blocks"][-1]["text"].replace("一次", "三次")
    changed = changed.model_copy(update={"document": doc})
    pictured = make_task(samples / "defense.pptx", image=True)
    pictured = pictured.model_copy(update={"approval": Approval(text_digest=pictured.approval.text_digest)})
    for task, code in ((unchecked, "text_confirmation_required"), (changed, "text_confirmation_required"),
                       (pictured, "image_confirmation_required")):
        def never_read(_):
            pytest.fail("unconfirmed image must not be opened")
        result, gateway, store = deep(task, test_config, transport, reader=never_read)
        assert isinstance(result, Failure) and result.code == code
        assert gateway.states[task.task_id] == "failed" and gateway.attempts == [] and store.calls == 0
    assert calls == []


def test_confirmed_vision_uploads_only_the_selected_embedded_bytes(samples, test_config):
    file = samples / "defense.pptx"
    task = make_task(file, image=True)
    preview = preview_scope(task)
    reader = LocalPptxImages(file)
    count = []
    def transport(req):
        body, payload = user_payload(req)
        content = body["messages"][1]["content"]
        assert "file" not in body and "tools" not in body
        assert OFF_SCOPE not in req.content.decode()
        if isinstance(content, str):
            assert payload["approved_text"][0]["slide"] == 2
            return completed(model_text(payload, criterion="pacing"))
        count.append(content[1])
        assert payload["approved_text"] == []
        assert payload["images"][0]["slide"] == 2
        import base64
        ref = payload["images"][0]["ref"]
        encoded = content[1]["image_url"]["url"]
        assert encoded.startswith("data:image/png;base64,")
        assert sha256(base64.b64decode(encoded.split(",", 1)[1])).hexdigest() == preview.images[0].sha256
        ev = {"ref": ref, "quote": None}
        return completed(json.dumps({"dimensions": [{"criterion": "hierarchy", "score": 4, "rationale": "图片本身缺少标签。", "evidence": [ev]}],
                                     "issues": [{"criterion": "hierarchy", "standard_index": 0, "impact": "presentation", "evidence": ev,
                                                 "suggestion": "增加清晰的图题。"}]}))
    result, gateway, _ = deep(task, test_config, transport, reader=reader)
    assert isinstance(result, Failure) is False
    assert len(count) == 1 and [a.image_count for a in gateway.attempts] == [0, 1]
    issue = next(i for i in result.issues if i.evidence.kind == "image")
    assert issue.location.source.slide == 2 and issue.evidence.image_sha256 == preview.images[0].sha256
    assert issue.evidence.quote is None
    validate_review_output(result.review, task.profile_id, document=task.document)


def test_changed_image_and_incompatible_model_fail_before_auth(samples, test_config):
    task = make_task(samples / "defense.pptx", image=True)
    def never_send(_):
        pytest.fail("no outbound HTTP request")
    result, gateway, store = deep(task, test_config, never_send, reader=lambda _: b"changed")
    assert result.code == "image_changed" and not gateway.attempts and store.calls == 0
    result, gateway, store = deep(task, test_config.model_copy(update={"model": "deepseek-v4-pro"}), never_send)
    assert result.code == "model_no_vision" and not gateway.attempts and store.calls == 0


@pytest.mark.parametrize("mode,code,attempts", [
    ("network", "provider_network", 2), ("timeout", "provider_timeout", 2), ("bad_json", "invalid_output", 2),
    ("duplicate", "invalid_output", 2), ("empty", "empty_output", 2), ("bad_evidence", "invalid_evidence", 2),
    ("bad_criterion", "invalid_criterion", 2), ("401", "provider_auth", 1), ("redirect", "provider_rejected", 1),
    ("length", "output_truncated", 2)
])
def test_failure_modes_bounded_and_never_store_raw_result(samples, test_config, mode, code, attempts):
    task = make_task(samples / "paper.docx")
    async def transport(request):
        if mode == "network":
            raise httpx.ConnectError("raw-provider-private-response", request=request)
        if mode == "timeout":
            await asyncio.sleep(10)
        if mode == "bad_json":
            return completed("raw-provider-private-response")
        if mode == "duplicate":
            return completed('{"dimensions":[],"dimensions":[],"issues":[]}')
        if mode == "empty":
            return completed("  ")
        if mode == "bad_evidence":
            return completed(model_text(user_payload(request)[1], quote="这句从未出现在所选原文。"))
        if mode == "bad_criterion":
            return completed(model_text(user_payload(request)[1], criterion="made-up"))
        if mode == "401":
            return httpx.Response(401, text="raw-provider-private-response")
        if mode == "redirect":
            return httpx.Response(307, headers={"Location": "https://example.org/not-allowed"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "{"}, "finish_reason": "length"}]})
    result, gateway, _ = deep(task, test_config, transport)
    assert isinstance(result, Failure) and result.code == code
    assert gateway.states[task.task_id] == "failed" and not gateway.results and len(gateway.attempts) == attempts
    assert not any("raw-provider-private-response" in a.model_dump_json() or TestStore.hidden in a.model_dump_json() for a in gateway.attempts)
    assert "raw-provider-private-response" not in result.model_dump_json()


def test_transient_retry_after_rate_limit_is_saved_once(samples, test_config):
    task = make_task(samples / "paper.docx")
    calls = []
    def transport(request):
        calls.append(request.content)
        if len(calls) == 1:
            return httpx.Response(429)
        return completed(model_text(user_payload(request)[1]))
    result, gateway, _ = deep(task, test_config, transport)
    assert calls[0] == calls[1]
    assert result.meta.status == "completed" and len(gateway.results) == 1
    assert [(a.status, a.error_code) for a in gateway.attempts] == [("failed", "provider_rate_limit"), ("completed", None)]


def test_criterion_retry_enumerates_options_without_expanding_approved_scope(samples, test_config):
    task = make_task(samples / "paper.docx")
    bodies = []
    def transport(request):
        body, payload = user_payload(request)
        mapping = {item["id"]: item["options"] for item in payload["standards"]}
        assert [option["index"] for option in mapping["methodology"]] == [0, 1]
        bodies.append(body)
        response = json.loads(model_text(payload))
        response["issues"][0]["standard_index"] = 2 if len(bodies) == 1 else 1
        return completed(json.dumps(response, ensure_ascii=False))
    result, gateway, _ = deep(task, test_config, transport)
    assert result.meta.status == "completed"
    assert result.issues[0].standard_index == 1
    assert bodies[0]["messages"][1] == bodies[1]["messages"][1]
    assert "options.index" in bodies[1]["messages"][0]["content"]
    assert [(a.error_code, a.http_status) for a in gateway.attempts] == [("invalid_criterion", 200), (None, 200)]


def test_long_document_is_split_and_overlap_deduplicated(samples):
    task = make_task(samples / "paper.docx", approval=False)
    doc = deepcopy(task.document)
    block = doc["blocks"][-1]
    phrase = "所有实验只测量一次"
    block["text"] = "重复" * 105 + phrase + "不追加结论" * 1500
    task = with_approval(task.model_copy(update={"document": doc, "selection": Selection(text=[TextSlice(block_id=block["id"])])}))
    config = AgentConfig(input_limit_bytes=10000, fragment_max_chars=250, fragment_overlap_chars=55)
    profile = load_profile(task.profile_id)
    chunks = plan_chunks(preview_scope(task), profile, select_skill(profile, "docx"), load_knowledge(profile["knowledge_refs"]), config)
    assert len(chunks) > 1 and max(c.input_bytes for c in chunks) <= 10000
    assert sum(phrase in f.text for chunk in chunks for f in chunk.fragments) >= 2
    gateway = MemoryGateway([task])
    result = asyncio.run(ReviewAgent(gateway, MockProvider(), config).run(task.task_id))
    assert len(result.issues) == 1 and result.issues[0].location.char_start == 210
    assert len(next(d["evidence"] for d in result.review["dimensions"] if d["id"] == "methodology")) == 1


def test_only_relevant_authorized_reference_metadata_is_retrieved():
    p = load_profile("competition-proposal-v1")
    refs = load_knowledge(p["knowledge_refs"])
    picked = retrieve(refs, p, "预算分项数量单价依据")
    assert 1 <= len(picked) <= 3 and any(row["id"] == "case-dachuang-budget" for row in picked)
    copied = deepcopy(next(row for row in refs if row["id"] == "case-dachuang-budget"))
    copied.update(id="private-do-not-send", kind="authorized_case")
    response = retrieve([copied, *refs], p, "预算分项数量单价依据")
    assert response == picked and "original_text" not in json.dumps(response)


def test_middle_failure_does_not_publish_partial_review(samples):
    base = make_task(samples / "paper.docx", approval=False)
    doc = deepcopy(base.document)
    block = doc["blocks"][-1]
    block["text"] = "复查抽样对照数据。" * 900
    task = with_approval(base.model_copy(update={"document": doc, "selection": Selection(text=[TextSlice(block_id=block["id"])])}))
    calls = []
    def transport(request):
        calls.append(request)
        if len(calls) == 1:
            return completed(model_text(user_payload(request)[1], quote="复查抽样对照数据。"))
        return completed("not-json")
    cfg = AgentConfig(input_limit_bytes=10000, fragment_max_chars=450, retries=0)
    result, gateway, _ = deep(task, cfg, transport)
    assert result.code == "invalid_output" and [row.status for row in gateway.attempts] == ["completed", "failed"]
    assert gateway.states[task.task_id] == "failed" and not gateway.results


def test_backend_cancellation_finishes_without_publishing(samples):
    task = make_task(samples / "paper.docx")
    gateway = MemoryGateway([task])
    async def exercise():
        entered = asyncio.Event()
        async def transport(_request):
            entered.set()
            await asyncio.sleep(10)
        config = AgentConfig()
        provider = DeepSeekProvider(config, transport=httpx.MockTransport(transport), credentials=TestStore())
        job = asyncio.create_task(ReviewAgent(gateway, provider).run(task.task_id))
        await asyncio.wait_for(entered.wait(), 2)
        job.cancel()
        with pytest.raises(asyncio.CancelledError):
            await job
    asyncio.run(exercise())
    assert gateway.failures[task.task_id].code == "task_cancelled" and not gateway.results


def test_gateway_prevents_duplicate_runs(samples):
    task = make_task(samples / "paper.docx")
    gateway = MemoryGateway([task])
    agent = ReviewAgent(gateway, MockProvider())
    async def twice():
        await agent.run(task.task_id)
        with pytest.raises(ReviewError, match="已被执行"):
            await agent.run(task.task_id)
    asyncio.run(twice())
    assert len(gateway.results) == 1 and len(gateway.attempts) == 1


def test_cli_docs_and_approval_roundtrip(samples):
    file = samples / "live-check.md"
    args = [str(file), "--profile", "academic-paper-v1", "--selection", str(samples / "live-check-selection.json")]
    def invoke(*parts):
        return subprocess.run([sys.executable, "-m", "app.review_agent", *parts], capture_output=True, check=True)
    preview = json.loads(invoke("preview", *args).stdout)
    assert preview["external_provider"] == "https://api.deepseek.com/chat/completions" and preview["text"][0]["source"]["line_start"] == 3
    result = json.loads(invoke("run", *args, "--text-digest", preview["text_digest"]).stdout)
    assert result["meta"]["provider"] == "mock" and result["issues"][0]["location"]["source"]["line_start"] == 3
    skill = json.loads(invoke("skill", "academic-paper-v1").stdout)
    assert "ChunkReview" == skill["chunk_output_schema"]["title"]
