from hashlib import sha256
import re

from docx import Document as WordDocument
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from lxml import etree

from .model import Document, Source

def W(name):
    return qn("w:" + name)


MATH = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
VML = "{urn:schemas-microsoft-com:vml}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
P = W("p")
TBL = W("tbl")


def _value(nodes, tag, attr="val"):
    for node in nodes:
        child = node.find(W(tag)) if node is not None else None
        if child is not None:
            value = child.get(W(attr))
            if value is not None:
                return value
    return None


def _styles(style):
    seen = set()
    while style is not None and style.style_id not in seen:
        seen.add(style.style_id)
        yield style.element
        style = style.base_style


def _get(element, name):
    return element.find(W(name)) if element is not None else None


def _props(styles, name):
    return [_get(style, name) for style in styles]


def _run_format(run, style_props, style_map, defaults, theme):
    direct = _get(run, "rPr")
    style = style_map.get(_value([direct], "rStyle"))
    props = [direct, *_props(_styles(style), "rPr"), *style_props, defaults]
    faces = {}
    origins = {}
    for axis, theme_axis in (("ascii", "asciiTheme"), ("hAnsi", "hAnsiTheme"), ("eastAsia", "eastAsiaTheme"), ("cs", "cstheme")):
        for prop in props:
            fonts = _get(prop, "rFonts")
            if fonts is None:
                continue
            theme_ref = fonts.get(W(theme_axis))
            value = fonts.get(W(axis))
            if theme_ref or value:
                faces[axis] = theme.get(theme_ref) or value
                if theme_ref:
                    origins[axis] = theme_ref
                break
    raw_size = _value(props, "sz")
    return {
        "text": _visible_text(run),
        "font": faces.get("hAnsi") or faces.get("ascii"),
        "fonts": faces,
        "font_theme": origins,
        "size_pt": int(raw_size) / 2 if raw_size is not None else None,
    }


def _alternate_branch(node):
    choices = node.findall(MC + "Choice")
    return choices[0] if choices else node.find(MC + "Fallback")


def _is_inactive(node, boundary):
    for ancestor in node.iterancestors():
        if ancestor is boundary:
            break
        if ancestor.tag in {W("del"), W("moveFrom"), W("txbxContent")}:
            return True
        if ancestor.tag in {MC + "Choice", MC + "Fallback"} and ancestor.getparent().tag == MC + "AlternateContent":
            if ancestor is not _alternate_branch(ancestor.getparent()):
                return True
    return False


def _visible_text(node):
    parts = []
    for item in node.iter():
        if item.tag not in {W("t"), W("tab"), W("br"), W("cr"), W("noBreakHyphen"), W("softHyphen")}:
            continue
        # The textbox has its own paragraph blocks; a deleted run is not final text.
        if _is_inactive(item, node):
            continue
        if item.tag == W("t"):
            parts.append(item.text or "")
        elif item.tag == W("tab"):
            parts.append("\t")
        elif item.tag == W("noBreakHyphen"):
            parts.append("\u2011")
        elif item.tag == W("softHyphen"):
            parts.append("\u00ad")
        else:
            if item.get(W("type")) not in {"page", "column"}:
                parts.append("\n")
    return "".join(parts)


def _theme_map(document):
    rel = next((r for r in document.part.rels.values() if r.reltype.endswith("/theme") and not r.is_external), None)
    if rel is None:
        return {}
    root = etree.fromstring(rel.target_part.blob, etree.XMLParser(resolve_entities=False, no_network=True))
    result = {}
    lang = document.styles.element.find(f".//{W('docDefaults')}//{W('lang')}")
    east_lang = lang.get(W("eastAsia"), "") if lang is not None else ""
    script = {"zh-TW": "Hant", "zh-HK": "Hant", "zh-CN": "Hans", "zh-SG": "Hans", "ja-JP": "Jpan", "ko-KR": "Hang"}.get(east_lang)
    for prefix in ("major", "minor"):
        family = root.find(f".//{A}{prefix}Font")
        if family is None:
            continue
        for attr, child in (("Ascii", "latin"), ("HAnsi", "latin"), ("EastAsia", "ea"), ("Bidi", "cs")):
            value = family.find(f"{A}{child}")
            face = value.get("typeface") if value is not None else None
            if attr == "EastAsia" and not face and script:
                face = next((font.get("typeface") for font in family.findall(f"{A}font") if font.get("script") == script), None)
            if face:
                result[prefix + attr] = face
    return result


def parse_word(path):
    word = WordDocument(path)
    doc = Document("docx", path.name, title=word.core_properties.title or None)
    default_p = word.styles.element.find(f".//{W('docDefaults')}/{W('pPrDefault')}/{W('pPr')}")
    default_r = word.styles.element.find(f".//{W('docDefaults')}/{W('rPrDefault')}/{W('rPr')}")
    style_map = {style.style_id: style for style in word.styles}
    theme = _theme_map(word)
    sections = []
    for i, sec in enumerate(word.sections, 1):
        margins = {side: round(getattr(sec, f"{side}_margin").cm, 4) if getattr(sec, f"{side}_margin") is not None else None
                   for side in ("top", "bottom", "left", "right")}
        sections.append({"number": i, "margins_cm": margins, "source": {"path": f"docx/section/{i}", "section": i}})
    doc.metadata.update(sections=sections, page_count=None)
    body = word.element.body
    doc.warn("word_no_pagination", "DOCX 的真实页码由排版决定；定位使用部件、段落和表格路径。")
    if any(item.tag in {W("del"), W("moveFrom")} for item in body.iter()):
        doc.warn("tracked_deletions", "文档含修订删除；统一结构显示接受删除后的可见内容。")
    if any(item.tag in {W("ins"), W("moveTo"), W("pPrChange"), W("rPrChange"), W("sectPrChange")} for item in body.iter()):
        doc.warn("tracked_changes", "文档含插入或格式修订；提取当前可见内容，自动调整需先处理修订。")
    tracking = word.settings.element.find(W("trackRevisions"))
    if tracking is not None and tracking.get(W("val"), "true") not in {"0", "false", "off"}:
        doc.metadata["track_revisions_enabled"] = True

    def paragraph(node, prefix, part, section, parent, idx, role):
        src = Source(prefix, section=section, paragraph=idx, part=str(part.partname).lstrip("/"))
        para = Paragraph(node, word)
        style = para.style
        style_nodes = list(_styles(style))
        direct = _get(node, "pPr")
        pprops = [direct, *_props(style_nodes, "pPr"), default_p]
        outline = _value(pprops, "outlineLvl")
        level = int(outline) + 1 if outline and int(outline) < 9 else None
        heading = re.fullmatch(r"(?:Heading|标题)\s*(\d+)", style.name if style else "", re.I)
        if level is None and heading:
            level = int(heading.group(1))
        role_name = "title" if style is not None and style.style_id == "Title" else "heading" if level else "paragraph"
        if role != "body" and role_name == "title":
            role_name = "heading"
        spacing_value = _value(pprops, "spacing", "line")
        line_rule = None
        if spacing_value is not None:
            first = next(prop for prop in pprops if prop is not None and _get(prop, "spacing") is not None and _get(prop, "spacing").get(W("line")) is not None)
            line_rule = _get(first, "spacing").get(W("lineRule"), "auto")
        runs = [_run_format(run, _props(style_nodes, "rPr"), style_map, default_r, theme)
                for run in node.iter(W("r")) if not _is_inactive(run, node)]
        text = _visible_text(node)
        num = next((_get(prop, "numPr") for prop in pprops if _get(prop, "numPr") is not None), None)
        field_codes = [item.text or "" for item in node.iter(W("instrText"))]
        field_codes += [item.get(W("instr"), "") for item in node.iter(W("fldSimple"))]
        block = doc.add(role_name, src, text, level=level, parent=parent, role=role,
                        style=style.name if style else None, style_id=style.style_id if style else None,
                        runs=runs, list_numbered=num is not None, field_codes=field_codes,
                        line_spacing={"kind": line_rule, "value": int(spacing_value) / (240 if line_rule == "auto" else 20)}
                        if spacing_value is not None else None)
        counters = {"image": 0, "formula": 0, "textbox": 0}

        def sub(kind):
            counters[kind] += 1
            return Source(f"{prefix}/{kind}/{counters[kind]}", section=section, paragraph=idx, part=src.part)

        for item in node.iter():
            if _is_inactive(item, node):
                continue
            if item.tag in {A + "blip", VML + "imagedata"}:
                image_src = sub("image")
                rid = item.get(REL + "embed") or item.get(REL + "id") or item.get(REL + "link")
                rel = part.rels.get(rid)
                drawing = next(item.iterancestors(W("drawing")), None)
                docpr = drawing.find(f".//{qn('wp:docPr')}") if drawing is not None else None
                attrs = {"relationship_id": rid, "alt": docpr.get("descr") if docpr is not None else None}
                extent = drawing.find(f".//{qn('wp:extent')}") if drawing is not None else None
                if extent is not None:
                    attrs["display_extent_emu"] = {axis: int(extent.get(axis)) for axis in ("cx", "cy") if extent.get(axis)}
                if rel is None or rel.is_external or not rel.reltype.endswith("/image"):
                    doc.warn("image_unavailable", "图片为外部链接或引用缺失，已记录位置，未读取外部资源。", image_src)
                    attrs["available"] = False
                else:
                    img = rel.target_part
                    attrs.update(available=True, mime_type=img.content_type, bytes=len(img.blob), sha256=sha256(img.blob).hexdigest())
                doc.add("image", image_src, parent=block.id, **attrs)
            elif item.tag == MATH + "oMath":
                formula_src = sub("formula")
                formula_text = "".join(t.text or "" for t in item.iter(MATH + "t"))
                doc.add("formula", formula_src, formula_text, parent=block.id, notation="omml",
                        omml=etree.tostring(item, encoding="unicode", with_tail=False),
                        display=item.getparent().tag == MATH + "oMathPara")
            elif item.tag == W("txbxContent"):
                extra = sub("textbox")
                walk(item, extra.path, part, section, block.id, "textbox")
            elif item.tag in {W("altChunk"), W("object"), W("subDoc")}:
                doc.warn("unsupported_embedded", "发现嵌入对象或外部内容，首版无法展开。", src)
            elif item.tag == MC + "AlternateContent":
                doc.warn("office_alternate_content", "兼容性对象采用首个主表示，不重复读取后备表示。", src)
        return block

    def walk(container, prefix, part, section=None, parent=None, role="body"):
        paragraph_count = table_count = wrapper_count = 0
        text_parts = []
        for item in container:
            if item.tag == P:
                paragraph_count += 1
                block = paragraph(item, f"{prefix}/p/{paragraph_count}", part, section, parent, paragraph_count, role)
                text_parts.append(block.text)
                if role in {"body", "content_control"} and section is not None and _get(_get(item, "pPr"), "sectPr") is not None:
                    section += 1
            elif item.tag == TBL:
                table_count += 1
                table_path = f"{prefix}/table/{table_count}"
                src = Source(table_path, section=section, part=str(part.partname).lstrip("/"))
                table = doc.add("table", src, parent=parent, role=role, rows=[])
                for ri, row in enumerate(item.findall(W("tr")), 1):
                    raw_offset = _value([_get(row, "trPr")], "gridBefore")
                    ci = int(raw_offset) + 1 if raw_offset else 1
                    cells = []
                    for cell in row.findall(W("tc")):
                        props = _get(cell, "tcPr")
                        span = int(_value([props], "gridSpan") or 1)
                        merge = _get(props, "vMerge")
                        cpath = f"{table_path}/r/{ri}/c/{ci}"
                        pieces, _ = walk(cell, cpath, part, section, table.id, "cell")
                        cell_text = "\n".join(pieces)
                        cells.append({"row": ri, "column": ci, "colspan": span, "text": cell_text, "path": cpath,
                                      "vertical_merge": merge.get(W("val"), "continue") if merge is not None else None})
                        ci += span
                    table.attrs["rows"].append(cells)
                    text_parts.extend(c["text"] for c in cells)
            elif item.tag in {W("sdt"), W("customXml"), W("ins"), W("moveTo"), MC + "AlternateContent"}:
                wrapper_count += 1
                if item.tag == MC + "AlternateContent":
                    content = _alternate_branch(item)
                    doc.warn("office_alternate_content", "兼容性内容采用首个主表示，不重复读取后备表示。", Source(prefix, section=section))
                else:
                    content = _get(item, "sdtContent") if item.tag == W("sdt") else item
                if content is not None:
                    wrapper_role = "content_control" if role == "body" else role
                    parts, section = walk(content, f"{prefix}/wrap/{wrapper_count}", part, section, parent, wrapper_role)
                    text_parts.extend(parts)
            elif item.tag in {W("altChunk"), W("object"), W("subDoc")}:
                doc.warn("unsupported_embedded", "发现嵌入对象或外部内容，首版无法展开。", Source(prefix, section=section))
        return text_parts, section

    walk(body, "docx/body", word.part, 1)
    # Header/footer parts are unique even when sections share a relationship.
    for rel in word.part.rels.values():
        if not rel.is_external and rel.reltype.rsplit("/", 1)[-1] in {"header", "footer", "footnotes", "endnotes"}:
            role = rel.reltype.rsplit("/", 1)[-1]
            part = rel.target_part
            element = getattr(part, "element", None)
            if element is None:
                element = etree.fromstring(part.blob, etree.XMLParser(resolve_entities=False, no_network=True))
            root = f"docx/parts/{str(part.partname).rsplit('/', 1)[-1]}"
            if role in {"footnotes", "endnotes"}:
                for note in element:
                    if note.get(W("type")) is None:
                        walk(note, f"{root}/note/{note.get(W('id'))}", part, role=role)
            else:
                walk(element, root, part, role=role)
    return doc
