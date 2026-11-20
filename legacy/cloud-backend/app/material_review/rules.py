"""Deterministic checks. Unknown measurements are reported explicitly."""
from collections import Counter
from dataclasses import asdict
import re
from statistics import median

from .model import MaterialError, Source


LETTER = re.compile(r"[A-Za-z]")
CJK = re.compile(r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]")
CAPTION = re.compile(r"^(?P<kind>图|表|Figure|Fig\.?|Table)\s*(?P<num>[0-9]+(?:[.\-－—][0-9]+)*)(?!\d)", re.I)
NUMBERS = re.compile(r"\d+")
DISPLAY_NUMBER = re.compile(r"[(（]\s*\d+(?:[.\-]\d+)*\s*[)）]\s*$")
SECTION_PREFIX = re.compile(r"^(?:第[一二三四五六七八九十0-9]+[章节]\s*|[0-9]+(?:\.[0-9]+)*[.\s、]+|[一二三四五六七八九十]+[、.]\s*)")
TOC = re.compile(r"\bTOC(?:\s|$)", re.I)
NUMBERED_REF = re.compile(r"^(?:\[\s*\d+\s*\]|［\s*\d+\s*］|\d+[.、])\s*\S")


def finding(rule, status, message, source=None, observed=None, expected=None, fix=None):
    return {"rule_id": rule["id"], "severity": rule["severity"], "status": status, "message": message,
            "source": asdict(source) if isinstance(source, Source) else source, "observed": observed,
            "expected": expected, "fix": fix}


def _is_caption(block):
    return CAPTION.match(block.text.strip()) or block.attrs.get("style_id") == "Caption"


def _fields(block):
    return block.attrs.get("field_codes", [])


def _body(doc):
    extras = {b.parent_id for b in doc.blocks if b.type in {"formula", "image"} or b.attrs.get("role") == "textbox"}
    references = False
    for block in doc.blocks:
        if block.type == "heading" and block.attrs.get("role") == "body":
            references = bool(re.fullmatch(r"参考文献|References|Bibliography", SECTION_PREFIX.sub("", block.text.strip()), re.I))
        if (not references and block.type == "paragraph" and block.attrs.get("role") == "body"
                and block.source.path.startswith("docx/body/p/") and block.text.strip()
                and not _is_caption(block) and not _fields(block) and block.id not in extras):
            yield block


def _same_font(actual, expected):
    equivalents = {"宋体": "simsun", "新宋体": "nsimsun", "黑体": "simhei", "微软雅黑": "microsoftyahei"}
    def normalize(value):
        key = re.sub(r"\s+", "", value.casefold())
        return equivalents.get(key, key)
    return normalize(actual) == normalize(expected)


def word_fonts(doc, rule, _):
    p = rule["params"]
    for block in _body(doc):
        wrong, unknown = [], []
        for idx, run in enumerate(block.attrs["runs"], 1):
            value = run["text"]
            for char_pattern, axis in ((CJK, "eastAsia"), (LETTER, "latin")):
                if char_pattern.search(value):
                    face = run["fonts"].get("eastAsia") if axis == "eastAsia" else run["font"]
                    if face is None:
                        unknown.append({"run": idx, "axis": axis})
                    elif not _same_font(face, p[axis]):
                        wrong.append({"run": idx, "axis": axis, "font": face})
        if wrong or unknown:
            yield finding(rule, "fail" if wrong else "needs_review",
                          "正文含不符合要求的字体。" if wrong else "部分字体未能从样式或主题确认。",
                          block.source, {"mismatches": wrong, "unresolved": unknown}, p,
                          {"operation": "word_fonts", "path": block.id} if wrong else None)


def word_size(doc, rule, _):
    p = rule["params"]
    for block in _body(doc):
        sizes = [r["size_pt"] for r in block.attrs["runs"] if r["text"].strip()]
        wrong = sorted({v for v in sizes if v is not None and abs(v - p["pt"]) > 0.01})
        if wrong or not sizes or None in sizes:
            yield finding(rule, "fail" if wrong else "needs_review",
                          "正文字号与规范不一致。" if wrong else "正文含未能确认字号的文字。",
                          block.source, {"mismatches_pt": wrong, "unresolved": not sizes or None in sizes}, p,
                          {"operation": "word_size", "path": block.id} if wrong else None)


def word_spacing(doc, rule, _):
    p = rule["params"]
    for block in _body(doc):
        value = block.attrs["line_spacing"]
        if value is None:
            yield finding(rule, "needs_review", "没有可确认的正文行距。", block.source, expected=p)
        elif value["kind"] != p["kind"] or abs(value["value"] - p["value"]) > 0.01:
            yield finding(rule, "fail", "正文行距与规范不一致。", block.source, value, p,
                          {"operation": "word_spacing", "path": block.id})


def word_margins(doc, rule, _):
    p = rule["params"]
    for section in doc.metadata["sections"]:
        value = section["margins_cm"]
        unknown = [side for side in p if value.get(side) is None]
        wrong = [side for side, cm in p.items() if value.get(side) is not None and abs(value[side] - cm) > 0.03]
        if wrong or unknown:
            src = Source(section["source"]["path"], section=section["number"], part="word/document.xml")
            yield finding(rule, "fail" if wrong else "needs_review",
                          "节的页边距与规范不一致。" if wrong else "节的页边距未能确认。", src, value, p,
                          {"operation": "word_margins", "path": src.path} if wrong else None)


def heading_hierarchy(doc, rule, _):
    last = 0
    headings = [b for b in doc.blocks if b.type == "heading" and b.level and b.attrs.get("role", "body") in {"body", "content_control"}]
    if not headings:
        yield finding(rule, "needs_review", "没有识别到标题层级；请使用标题样式或可识别的章节标记。")
    for heading in headings:
        if heading.level > last + 1:
            yield finding(rule, "fail", "标题层级跳级。", heading.source, heading.level, {"max_next_level": last + 1})
        last = heading.level


def _matches_label(block, values):
    text = SECTION_PREFIX.sub("", block.text.strip())
    if len(text) > 600:
        return False
    for alias in values:
        pattern = re.escape(alias)
        if re.match(rf"^{pattern}\s*(?:[:：]|$|\n|\t|[.]{2,})", text, re.I):
            return True
        if block.type == "heading" and re.match(rf"^{pattern}(?:\s|[（(：:及与和、])", text, re.I):
            return True
    return False


def sections(doc, rule, _):
    p = rule["params"]
    candidates = [b for b in doc.blocks if b.type in {"heading", "paragraph"}
                  and b.attrs.get("role", "body") in {"body", "content_control"}]
    uncertainty = (doc.format == "pdf" and any(w["code"] == "pdf_no_text_layer" for w in doc.warnings)) or any(
        w["code"] == "unsupported_embedded" for w in doc.warnings)
    for name, terms in p["required"].items():
        matches = [b for b in candidates if _matches_label(b, terms)]
        if matches:
            yield finding(rule, "pass", f"找到“{name}”。", matches[0].source, expected=terms)
        else:
            yield finding(rule, "needs_review" if uncertainty else "fail", f"未找到可识别的“{name}”标记。", expected=terms)


def toc(doc, rule, _):
    candidates = [b for b in doc.blocks if b.type in {"heading", "paragraph"} and b.attrs.get("role", "body") in {"body", "content_control"}]
    field = next((b for b in candidates if any(TOC.search(code) for code in _fields(b))), None)
    label = next((b for b in candidates if _matches_label(b, ["目录", "目 录", "Contents", "Table of Contents"])), None)
    entries = [b for b in candidates if re.search(r"(?:\.{2,}|…{2,}|\t)\s*\d+\s*$", b.text)
               or re.fullmatch(r"TOC\s*\d+", b.attrs.get("style", "") or "", re.I)]
    if not field and (not label or not entries):
        yield finding(rule, "needs_review" if doc.format == "pdf" else "fail", "未发现目录域或可识别的目录条目。", label.source if label else None)
    elif not entries:
        yield finding(rule, "needs_review", "发现目录域，但没有可核对的目录条目；请在 Word 中更新目录后复查。", field.source)
    else:
        yield finding(rule, "pass", "检测到目录和条目；条目与正文的对应关系请复核。", (field or label).source, len(entries))


def page_count(doc, rule, context):
    p = rule["params"]
    actual = doc.metadata.get("page_count")
    origin = doc.metadata.get("page_count_source")
    if actual is None:
        actual, origin = context.get("rendered_page_count"), "caller_rendered"
    if actual is None:
        yield finding(rule, "needs_review", "无法确认真实页数；请传入排版后的页数或用 PDF 校验。", expected=p)
    elif not p.get("min", 1) <= actual <= p["max"]:
        yield finding(rule, "fail", "页数或幻灯片数量超出此 profile 的范围。", observed={"pages": actual, "origin": origin}, expected=p)
    else:
        yield finding(rule, "pass", "页数或幻灯片数量符合此 profile 阈值。", observed={"pages": actual, "origin": origin}, expected=p)


def file_submission(doc, rule, _):
    p = rule["params"]
    if doc.format not in p["formats"]:
        yield finding(rule, "fail", "文件类型不符合此 profile 的提交要求。", observed=doc.format, expected=p["formats"])
    if doc.metadata["file_size_bytes"] > p["max_bytes"]:
        yield finding(rule, "fail", "文件超过此 profile 的提交体积上限。", observed=doc.metadata["file_size_bytes"], expected=p["max_bytes"])


def _caption_kind(match):
    return "image" if match.group("kind").casefold() in {"图", "figure", "fig", "fig."} else "table"


def _container(block):
    if block.source.path.rsplit("/", 2)[-2] in {"p", "table"}:
        return block.source.path.rsplit("/", 2)[0]
    return None


def word_captions(doc, rule, _):
    by_id = {b.id: b for b in doc.blocks}
    peers = {}
    for b in doc.blocks:
        prefix = _container(b)
        if prefix and b.type in {"paragraph", "heading", "title", "table"} and (b.text.strip() or b.type == "table" or b.attrs.get("runs") is not None):
            peers.setdefault(prefix, []).append(b)
    relevant = [b for b in doc.blocks if b.type in {"image", "table"}]
    if not relevant:
        yield finding(rule, "not_applicable", "没有图片或表格。")
    used = {}
    for obj in relevant:
        anchor = by_id[obj.parent_id] if obj.type == "image" else obj
        if anchor.attrs.get("role") not in {"body", "content_control", "cell"}:
            continue
        options = peers.get(_container(anchor), [])
        if anchor not in options:
            continue
        idx = options.index(anchor)
        direction = 1 if obj.type == "image" else -1
        group = [] if obj.type == "table" else [anchor]
        j = idx + direction
        while 0 <= j < len(options):
            item = options[j]
            if item.text.strip() or item.type == "table" or any(other.parent_id == item.id for other in relevant):
                group.append(item)
                break
            j += direction
        selected = next((b for b in group if (m := CAPTION.match(b.text.strip())) and _caption_kind(m) == obj.type), None)
        if selected is None or selected.id in used:
            label = "图下方" if obj.type == "image" else "表上方"
            yield finding(rule, "fail", f"在{label}未找到独立可匹配的编号题注。", obj.source)
        else:
            used[selected.id] = obj.id


def caption_numbers(doc, rule, _):
    previous, used = {}, set()
    found = False
    for block in doc.blocks:
        if block.type not in {"paragraph", "heading"} or block.attrs.get("role", "body") not in {"body", "content_control"}:
            continue
        match = CAPTION.match(block.text.strip())
        if not match:
            continue
        found = True
        kind = _caption_kind(match)
        number = tuple(map(int, NUMBERS.findall(match.group("num"))))
        key = kind, number
        if key in used:
            yield finding(rule, "fail", "图表题注编号重复。", block.source, match.group("num"))
        elif kind in previous and number <= previous[kind]:
            yield finding(rule, "fail", "图表题注编号未按正文顺序递增。", block.source, match.group("num"))
        used.add(key)
        previous[kind] = number
    if not found:
        yield finding(rule, "not_applicable", "没有识别到编号题注。")


def word_formula(doc, rule, _):
    by_id = {b.id: b for b in doc.blocks}
    formulas = [b for b in doc.blocks if b.type == "formula" and b.attrs.get("display")]
    if not formulas:
        yield finding(rule, "not_applicable", "没有检测到可检查编号的独立 OMML 公式。")
    labels = set()
    for block in formulas:
        parent = by_id[block.parent_id]
        match = DISPLAY_NUMBER.search(parent.text)
        label = "".join(NUMBERS.findall(match.group(0))) if match else None
        if not match and not any(re.search(r"\bSEQ\s+(?:Equation|公式)\b", code, re.I) for code in _fields(parent)):
            yield finding(rule, "fail", "独立公式未找到括号编号或公式序列域。", block.source)
        elif label is not None:
            normalized = tuple(NUMBERS.findall(match.group(0)))
            if normalized in labels:
                yield finding(rule, "fail", "独立公式编号重复。", block.source, match.group(0))
            labels.add(normalized)


def references(doc, rule, _):
    in_refs = False
    header = None
    entries = []
    for block in doc.blocks:
        if block.type not in {"heading", "paragraph"} or block.attrs.get("role", "body") not in {"body", "content_control"}:
            continue
        if _matches_label(block, ["参考文献", "References", "Bibliography"]):
            header, in_refs = block, True
        elif in_refs and block.type == "heading":
            break
        elif in_refs and block.text.strip():
            entries.append(block)
    if not header:
        status = "needs_review" if any(w["code"] == "pdf_no_text_layer" for w in doc.warnings) else "fail"
        yield finding(rule, status, "未找到参考文献节。")
    elif not entries:
        yield finding(rule, "fail", "参考文献节没有条目。", header.source)
    else:
        for block in entries:
            if not NUMBERED_REF.match(block.text.strip()) and not block.attrs.get("list_numbered"):
                yield finding(rule, "fail", "未识别到参考文献条目编号。", block.source, expected="[1] 或 Word 自动编号")


def slides_metrics(doc, rule, _):
    p = rule["params"]
    for slide in (b for b in doc.blocks if b.type == "slide" and not b.attrs.get("hidden")):
        if not slide.text.strip():
            yield finding(rule, "needs_review", "未识别到标题占位符；请检查该页是否有明显标题。", slide.source)
        if slide.attrs["text_chars"] > p["max_chars"]:
            yield finding(rule, "fail", "该页文字较多，建议拆分论点或改用图表。", slide.source, slide.attrs["text_chars"], p["max_chars"])


def slides_fonts(doc, rule, _):
    p = rule["params"]
    for block in doc.blocks:
        if block.type not in {"paragraph", "heading"} or not block.text.strip():
            continue
        minimum = p["title_pt"] if block.attrs["role"] == "title" else p["body_pt"]
        values = [r["size_pt"] for r in block.attrs["runs"] if r["text"].strip()]
        small = sorted({pt for pt in values if pt is not None and pt < minimum})
        if small:
            yield finding(rule, "fail", "检测到小于建议阈值的字号。", block.source, small, minimum)
        if not values or None in values:
            yield finding(rule, "needs_review", "部分字号由版式继承，无法确认可读性。", block.source, expected=minimum)


def slides_hierarchy(doc, rule, _):
    p = rule["params"]
    for slide in (b for b in doc.blocks if b.type == "slide" and not b.attrs.get("hidden")):
        relevant = [b for b in doc.blocks if b.source.slide == slide.source.slide and b.type in {"heading", "paragraph"} and b.text.strip()]
        sizes = {"title": [], "body": []}
        unresolved = False
        for block in relevant:
            key = "title" if block.attrs.get("role") == "title" else "body"
            for run in block.attrs["runs"]:
                if not run["text"].strip():
                    continue
                if run["size_pt"] is None:
                    unresolved = True
                else:
                    sizes[key].append(run["size_pt"])
        if not sizes["title"] or not sizes["body"] or unresolved:
            yield finding(rule, "needs_review", "标题与正文缺少完整字号证据，建议人工检查视觉层级。", slide.source)
        else:
            delta = min(sizes["title"]) - median(sizes["body"])
            if delta < p["min_title_delta_pt"]:
                yield finding(rule, "fail", "标题与正文的字号差较小，建议增强层级。", slide.source, delta, p["min_title_delta_pt"])


HANDLERS = {fn.__name__: fn for fn in (
    word_fonts, word_size, word_spacing, word_margins, heading_hierarchy, sections, toc, page_count, file_submission,
    word_captions, caption_numbers, word_formula, references, slides_metrics, slides_fonts, slides_hierarchy,
)}


def run_checks(doc, profile, *, rendered_page_count=None):
    if rendered_page_count is not None and (type(rendered_page_count) is not int or rendered_page_count < 1):
        raise MaterialError("bad_page_count", "排版页数必须为正整数。")
    findings = []
    for rule in profile["format_rules"]:
        if rule["formats"] and doc.format not in rule["formats"]:
            findings.append(finding(rule, "not_applicable", f"{rule['title']}不适用于 {doc.format}。"))
            continue
        matches = list(HANDLERS[rule["handler"]](doc, rule, {"rendered_page_count": rendered_page_count}))
        if not matches:
            if rule["handler"] in {"word_fonts", "word_size", "word_spacing"} and not list(_body(doc)):
                matches = [finding(rule, "not_applicable", "没有适用的 DOCX 正文段落。")]
            else:
                matches = [finding(rule, "pass", f"{rule['title']}：未发现可判定的偏差。")]
        findings.extend(matches)
    counts = Counter(f["status"] for f in findings)
    return {"schema_version": "1.0", "profile_id": profile["id"], "format": doc.format,
            "summary": {state: counts[state] for state in ("pass", "fail", "needs_review", "not_applicable")},
            "findings": findings}
