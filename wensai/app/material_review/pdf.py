import re

import pymupdf

from .model import Document, MaterialError, Source


MATH_LINE = re.compile(r"^\s*[A-Za-z\u0370-\u03ff][A-Za-z0-9_{}\u0370-\u03ff ()]{0,24}\s*(?:=|≤|≥|≈)\s*\S.{0,100}$")
HEADING = re.compile(r"^(?:摘要|关键词|目录|参考文献|Abstract|Keywords|Contents|References)\s*[:：]?$", re.I)


def _bbox(values):
    return [round(float(v), 3) for v in values]


def parse_pdf(path):
    with pymupdf.open(path) as pdf:
        if pdf.needs_pass:
            raise MaterialError("encrypted_pdf", "PDF 已加密，请上传解密后的副本。")
        doc = Document("pdf", path.name, title=(pdf.metadata or {}).get("title") or None)
        doc.metadata.update(page_count=len(pdf), page_count_source="native")
        for pi, page in enumerate(pdf, 1):
            prefix = f"pdf/page/{pi}"
            page_block = doc.add("page", Source(prefix, page=pi), width_pt=page.rect.width, height_pt=page.rect.height,
                                 rotation_deg=page.rotation)
            raw = page.get_text("dict", flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)
            texts = []
            for i, block in enumerate(raw["blocks"], 1):
                if block["type"] != 0:
                    continue
                lines = [[{"text": s["text"], "font": s["font"], "size_pt": round(s["size"], 3),
                           "bbox": _bbox(s["bbox"]), "color": f"#{s['color']:06x}"} for s in line["spans"]]
                         for line in block["lines"]]
                text = "\n".join("".join(span["text"] for span in line) for line in lines)
                src = Source(f"{prefix}/text/{i}", page=pi, bbox=_bbox(block["bbox"]), coordinate_space="pdf_unrotated_pt")
                texts.append((src.bbox[1], src.bbox[0], src, text, lines, block["lines"]))
            placements = []
            for i, image in enumerate(page.get_image_info(hashes=True), 1):
                src = Source(f"{prefix}/image/{i}", page=pi, bbox=_bbox(image["bbox"]), coordinate_space="pdf_unrotated_pt")
                placements.append((src.bbox[1], src.bbox[0], src, image))
            events = sorted([(entry[0], entry[1], "text", entry[2:]) for entry in texts]
                            + [(entry[0], entry[1], "image", entry[2:]) for entry in placements], key=lambda entry: entry[:2])
            for _, _, kind, entry in events:
                if kind == "text":
                    src, text, lines, nodes = entry
                    is_heading = bool(HEADING.fullmatch(text.strip()))
                    block = doc.add("heading" if is_heading else "paragraph", src, text, level=1 if is_heading else None,
                                    parent=page_block.id, runs=[span for line in lines for span in line], role="body")
                    for li, (line, node) in enumerate(zip(lines, nodes), 1):
                        line_text = "".join(span["text"] for span in line).strip()
                        if MATH_LINE.fullmatch(line_text) or (len(line_text) <= 100 and re.search("[∑∫√∏]", line_text)):
                            fsrc = Source(f"{src.path}/formula/{li}", page=pi, bbox=_bbox(node["bbox"]), coordinate_space=src.coordinate_space)
                            doc.add("formula", fsrc, line_text, parent=block.id, notation="plain_text", inferred=True)
                else:
                    src, image = entry
                    doc.add("image", src, parent=page_block.id, width_px=image["width"], height_px=image["height"],
                            digest_md5=image["digest"].hex(), placement_number=image["number"])
            try:
                for i, table in enumerate(page.find_tables().tables, 1):
                    src = Source(f"{prefix}/table/{i}", page=pi, bbox=_bbox(table.bbox), coordinate_space="pdf_unrotated_pt")
                    rows = []
                    for ri, (row, cells) in enumerate(zip(table.extract(), table.rows), 1):
                        rows.append([{"row": ri, "column": ci, "text": cell or "", "bbox": _bbox(bbox) if bbox else None,
                                      "path": f"{src.path}/r/{ri}/c/{ci}"}
                                     for ci, (cell, bbox) in enumerate(zip(row, cells.cells), 1)])
                    doc.add("table", src, parent=page_block.id, rows=rows, inferred=True)
            except Exception:
                doc.warn("pdf_table_unavailable", "该页未能识别表格边界，仍保留页面文本。", page_block.source)
            if not any(entry[3].strip() for entry in texts):
                doc.warn("pdf_no_text_layer", "此页没有可提取文本；可能是扫描件或空白页，首版没有 OCR。", page_block.source)
        doc.warn("pdf_structure_inferred", "PDF 排序、标题、表格和公式按文本及坐标推断；无边框表格、轮廓公式和矢量图可能无法还原。")
        return doc
