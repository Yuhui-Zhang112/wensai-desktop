import codecs
import re

from .model import Document, Source


ATX = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
SECTION = re.compile(r"^(?:第[一二三四五六七八九十0-9]+[章节](?:[：:\s].*|\S.{0,55})?|(\d+(?:\.\d+){0,5})[、. \t]\s*\S.{0,60})$")
LABEL = re.compile(r"^(?:摘\s*要|关键词|目录|参考文献|Abstract|Keywords|Contents|References)\s*[:：]?$", re.I)


def _decode(path, encoding):
    data = path.read_bytes()
    if encoding is None:
        encoding = "utf-8-sig" if data.startswith(codecs.BOM_UTF8) else "utf-16" if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)) else "utf-8"
    return data.decode(encoding), encoding


def parse_text(path, *, markdown, encoding):
    raw, used = _decode(path, encoding)
    doc = Document("markdown" if markdown else "txt", path.name, raw_text=raw, metadata={"encoding": used, "page_count": None})
    if markdown:
        _markdown(doc)
    else:
        _plain(doc)
    return doc


def _source(doc, start, end, suffix=""):
    return Source(f"{doc.format}/lines/{start}/{end}{suffix}", line_start=start, line_end=end)


def _plain(doc):
    lines = doc.raw_text.splitlines()
    idx = 0
    while idx < len(lines):
        line = lines[idx].strip()
        if not line:
            idx += 1
            continue
        atx = ATX.fullmatch(line)
        sect = SECTION.fullmatch(line)
        if atx or sect or LABEL.fullmatch(line):
            label = atx.group(2) if atx else line
            level = len(atx.group(1)) if atx else len(sect.group(1).split(".")) if sect and sect.group(1) else 1
            doc.add("heading", _source(doc, idx + 1, idx + 1), label, level=level)
        else:
            doc.add("paragraph", _source(doc, idx + 1, idx + 1), lines[idx], role="body")
        idx += 1


def _display_text(tokens):
    return "".join("\n" if tok.type in {"softbreak", "hardbreak"} else tok.content
                   for tok in tokens if tok.type in {"text", "code_inline", "math_inline", "math_inline_double", "image", "softbreak", "hardbreak", "html_inline"})


def _markdown(doc):
    from markdown_it import MarkdownIt
    from mdit_py_plugins.dollarmath import dollarmath_plugin

    tokens = MarkdownIt("commonmark", {"html": True}).enable("table").use(dollarmath_plugin).parse(doc.raw_text)
    counts = {}

    def source(bounds):
        start, end = bounds[0] + 1, bounds[1]
        pair = start, end
        counts[pair] = counts.get(pair, 0) + 1
        return _source(doc, start, end, "" if counts[pair] == 1 else f"/block/{counts[pair]}")

    def inline(token, block, bounds):
        for i, child in enumerate(token.children or [], 1):
            if child.type in {"math_inline", "math_inline_double"}:
                doc.add("formula", Source(f"{block.id}/formula/{i}", line_start=bounds[0] + 1, line_end=bounds[1]),
                        child.content, parent=block.id, notation="latex", display=child.type.endswith("double"))
            if child.type == "image":
                src = Source(f"{block.id}/image/{i}", line_start=bounds[0] + 1, line_end=bounds[1])
                doc.add("image", src, parent=block.id, alt=child.content, reference=child.attrGet("src"), fetched=False)
            if child.type == "html_inline" and re.match(r"<\s*(?:img|table|math)(?:\s|>)", child.content, re.I):
                doc.warn("markdown_raw_html", "已保留内嵌 HTML 原文；未将其展开为图表或公式。", block.source)

    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token.type == "table_open":
            tbody = doc.add("table", source(token.map), rows=[])
            i, row, row_bounds = idx + 1, None, token.map
            while tokens[i].type != "table_close":
                item = tokens[i]
                if item.type == "tr_open":
                    row, row_bounds = [], item.map or token.map
                    tbody.attrs["rows"].append(row)
                elif item.type == "inline":
                    ri, ci = len(tbody.attrs["rows"]), len(row) + 1
                    cell_path = f"{tbody.id}/r/{ri}/c/{ci}"
                    text = _display_text(item.children or [])
                    cell = doc.add("cell", Source(cell_path, line_start=row_bounds[0] + 1, line_end=row_bounds[1]),
                                   text, parent=tbody.id, row=ri, column=ci)
                    inline(item, cell, row_bounds)
                    row.append({"row": ri, "column": ci, "text": text, "path": cell_path})
                i += 1
            idx = i
        elif token.type in {"heading_open", "paragraph_open"} and tokens[idx + 1].type == "inline":
            item = tokens[idx + 1]
            bounds = item.map or token.map
            is_heading = token.type == "heading_open"
            block = doc.add("heading" if is_heading else "paragraph", source(bounds), _display_text(item.children or []),
                            level=int(token.tag[1:]) if is_heading else None, role="body")
            inline(item, block, bounds)
            idx += 1
        elif token.type in {"math_block", "math_block_label"}:
            doc.add("formula", source(token.map), token.content, notation="latex", display=True, label=token.info or None)
        elif token.type in {"fence", "code_block", "html_block"}:
            block = doc.add("paragraph", source(token.map), token.content, role=token.type)
            if token.type == "html_block":
                doc.warn("markdown_raw_html", "已保留 HTML 原文；首版不展开或执行 HTML。", block.source)
        idx += 1
