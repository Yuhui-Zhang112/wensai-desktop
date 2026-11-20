from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import subprocess
import sys
from zipfile import ZipFile

import pytest

from app.material_review import (MaterialError, build_review_input, check_document, fix_docx, load_knowledge, load_profile,
                                 parse_document, validate_catalog, validate_document, validate_review_output)
from app.material_review.catalog import ROOT
from task_b_tests.make_samples import make_samples


@pytest.fixture(scope="module")
def samples(tmp_path_factory):
    root = tmp_path_factory.mktemp("materials")
    make_samples(root)
    return root


def test_word_content_is_located(samples):
    doc = parse_document(samples / "academic_ok.docx")
    validate_document(doc)
    assert doc.title == "雨水采集传感器校准实验"
    assert doc.metadata["page_count"] is None
    assert doc.metadata["sections"][0]["margins_cm"]["top"] == 2.54
    image = next(b for b in doc.blocks if b.type == "image")
    assert image.attrs["alt"] == "教学样例中的传感器示意图"
    assert image.source.part == "word/document.xml" and image.source.paragraph
    assert image.attrs["sha256"] and image.parent_id in image.id
    table = next(b for b in doc.blocks if b.type == "table")
    cell = table.attrs["rows"][1][1]
    assert cell["text"] == "8 mL"
    assert any(b.id.startswith(cell["path"] + "/") and b.text == "8 mL" for b in doc.blocks)
    equation = next(b for b in doc.blocks if b.type == "formula")
    assert equation.text == "y=2x" and equation.attrs["display"]
    assert any(b.attrs.get("role") == "header" and b.text == "任务 B 教学验收样例" for b in doc.blocks)


def test_slides_include_fonts_notes_and_tables(samples):
    doc = parse_document(samples / "defense_ok.pptx")
    validate_document(doc)
    assert doc.metadata["page_count"] == 3
    title = next(b for b in doc.blocks if b.type == "heading")
    assert title.source.slide == 1 and title.attrs["runs"][0]["size_pt"] == 32.0
    assert title.source.bbox and title.source.coordinate_space == "slide_pt"
    table = next(b for b in doc.blocks if b.type == "table")
    assert table.source.slide == 2 and table.attrs["rows"][1][1]["text"] == "十组"
    assert any(b.type == "slide" and b.attrs.get("notes") == "先说明目标，建议 40 秒。" for b in doc.blocks)
    assert any(b.type == "image" and b.source.slide == 2 and b.attrs["available"] for b in doc.blocks)


def test_pdf_includes_text_image_table_formula_and_native_pages(samples):
    doc = parse_document(samples / "material.pdf")
    validate_document(doc)
    assert doc.metadata["page_count"] == 2
    assert next(b for b in doc.blocks if b.type == "formula").text == "y = 2x"
    assert next(b for b in doc.blocks if b.type == "image").source.page == 1
    assert next(b for b in doc.blocks if b.type == "table").attrs["rows"][1][1]["text"] == "8 mL"
    assert any(b.source.page == 2 and "Second page" in b.text for b in doc.blocks)
    scan = parse_document(samples / "scan_like.pdf")
    assert any(w["code"] == "pdf_no_text_layer" and w["source"]["page"] == 1 for w in scan.warnings)


def test_text_formats_retain_original_and_line_positions(samples):
    doc = parse_document(samples / "material.txt")
    validate_document(doc)
    assert doc.raw_text.encode() == (samples / "material.txt").read_bytes()
    assert [b.level for b in doc.blocks if b.type == "heading"] == [1, 2]
    assert doc.blocks[-1].source.line_start == 4
    md = parse_document(samples / "material.md")
    validate_document(md)
    assert md.raw_text == (samples / "material.md").read_text(encoding="utf-8")
    assert [b.level for b in md.blocks if b.type == "heading"] == [1, 2]
    assert next(b for b in md.blocks if b.type == "image").attrs["reference"] == "images/prototype.png"
    assert [b.text.strip() for b in md.blocks if b.type == "formula"] == ["y=2x", "x=1", "y=2x"]


@pytest.mark.parametrize("filename", ["academic_ok.docx", "academic_errors.docx", "proposal_ok.docx", "proposal_errors.docx",
                                      "defense_ok.pptx", "defense_errors.pptx"])
def test_checks_match_independent_expected_defects(samples, filename):
    spec = json.loads((samples / "expected_format_findings.json").read_text())[filename]
    doc = parse_document(samples / filename)
    result = check_document(doc, spec["profile"], rendered_page_count=spec.get("rendered_page_count"))
    assert {row["rule_id"] for row in result["findings"] if row["status"] == "fail"} == set(spec["fail"])


def test_unmeasured_pages_are_not_guessed(samples):
    result = check_document(parse_document(samples / "proposal_ok.docx"), "competition-proposal-v1")
    assert next(row for row in result["findings"] if row["rule_id"] == "proposal-pages")["status"] == "needs_review"


@pytest.mark.parametrize("material,profile", [("academic", "academic-paper-v1"), ("proposal", "competition-proposal-v1")])
def test_adjustment_preserves_original_payload_and_other_parts(samples, tmp_path, material, profile):
    source = samples / f"{material}_errors.docx"
    original = sha256(source.read_bytes()).hexdigest()
    dst = tmp_path / "new_version.docx"
    result = fix_docx(source, dst, profile)
    assert sha256(source.read_bytes()).hexdigest() == original
    assert {x["rule_id"] for x in result["changes"]} == {"word-fonts", "word-size", "word-spacing", "word-margins"}
    before = parse_document(source)
    after = parse_document(dst)
    assert [(b.type, b.text, b.source.path) for b in before.blocks] == [(b.type, b.text, b.source.path) for b in after.blocks]
    with ZipFile(source) as old, ZipFile(dst) as new:
        assert set(old.namelist()) == set(new.namelist())
        assert all(old.read(name) == new.read(name) for name in old.namelist() if name != "word/document.xml")
    failures = {f["rule_id"] for f in result["after"]["findings"] if f["status"] == "fail"}
    assert {"headings", "captions"} <= failures
    assert not {"word-fonts", "word-size", "word-spacing", "word-margins"} & failures
    with pytest.raises(MaterialError, match="不能覆盖"):
        fix_docx(source, dst, profile)


def test_profiles_are_valid_versioned_and_knowledge_has_provenance(tmp_path):
    catalog = validate_catalog()
    assert catalog["profiles"] == ["academic-paper-v1", "competition-proposal-v1", "ppt-defense-v1"]
    assert catalog["official_sources"] >= 6 and catalog["instructional_cases"] == 6
    assert len({x["competition"] for x in load_knowledge() if x["kind"] == "official_reference"}) == 6
    for name in ("profiles.lock.json", "academic-paper-v1.json"):
        (tmp_path / name).write_bytes((ROOT / "profiles" / name).read_bytes())
    target = tmp_path / "academic-paper-v1.json"
    target.write_bytes(target.read_bytes().replace(b'"version": 1', b'"version": 2'))
    with pytest.raises(MaterialError) as exc:
        load_profile("academic-paper-v1", profiles_dir=tmp_path)
    assert exc.value.code == "profile_changed"


def test_agent_contract_validates_evidence_and_insufficient_evidence(samples):
    profile = "competition-proposal-v1"
    result = build_review_input(samples / "proposal_ok.docx", profile, rendered_page_count=2)
    doc = result["document"]
    b = next(b for b in doc["blocks"] if "十次模拟" in b["text"])
    evidence = {"block_id": b["id"], "source": b["source"], "excerpt": "在十次模拟降雨中测量水量"}
    output = {"profile_id": profile, "summary": "针对任务书练习。", "priority_actions": [],
              "dimensions": [{"id": d["id"], "status": "insufficient_evidence", "score": None, "rationale": "样例未覆盖。",
                              "evidence": [], "suggestions": []} for d in result["profile"]["dimensions"]]}
    output["dimensions"][0].update(status="evaluated", score=6, evidence=[evidence])
    validate_review_output(output, profile, document=doc)
    image = next(block for block in doc["blocks"] if block["type"] == "image")
    visual = deepcopy(output)
    visual["dimensions"][0]["evidence"].append({"block_id": image["id"], "source": image["source"], "excerpt": None})
    validate_review_output(visual, profile, document=doc)
    bad = deepcopy(output)
    bad["dimensions"][0]["evidence"][0]["excerpt"] = "不存在的实验结果"
    with pytest.raises(MaterialError) as exc:
        validate_review_output(bad, profile, document=doc)
    assert exc.value.code == "invalid_evidence"
    bad = deepcopy(output)
    bad["dimensions"][1]["score"] = 7
    with pytest.raises(MaterialError, match="不符合约定"):
        validate_review_output(bad, profile)


def test_parse_errors_and_cli(samples):
    with pytest.raises(MaterialError) as exc:
        parse_document(samples / "corrupt.docx")
    assert exc.value.code == "parse_failed"
    result = subprocess.run([sys.executable, "-m", "app.material_review", "parse", str(samples / "corrupt.docx")], capture_output=True)
    assert result.returncode == 2
    assert json.loads(result.stderr)["error"]["code"] == "parse_failed"
    pdf = subprocess.run([sys.executable, "-m", "app.material_review", "parse", str(samples / "material.pdf")], capture_output=True)
    assert pdf.returncode == 0
    assert json.loads(pdf.stdout)["metadata"]["page_count"] == 2


def test_invalid_inputs_do_not_fall_back_to_empty_documents(tmp_path):
    unsupported = tmp_path / "legacy.doc"
    with pytest.raises(MaterialError) as exc:
        parse_document(unsupported)
    assert exc.value.code == "unsupported_format"
    raw = tmp_path / "legacy.txt"
    raw.write_bytes("原文".encode("gb18030"))
    with pytest.raises(MaterialError) as exc:
        parse_document(raw)
    assert exc.value.code == "invalid_encoding"
    assert parse_document(raw, encoding="gb18030").raw_text == "原文"
