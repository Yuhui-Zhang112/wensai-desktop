from hashlib import sha256
import re

from lxml import etree
from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE
from pptx.oxml.ns import qn

from .model import Document, Source
from .word import MATH


def _font_info(run, paragraph):
    font = run.font
    fallback = paragraph.font
    size = font.size if font.size is not None else fallback.size
    face = font.name or fallback.name
    bold = font.bold if font.bold is not None else fallback.bold
    runs = [run._r.find(qn("a:rPr")), paragraph._p.find(f"{qn('a:pPr')}/{qn('a:defRPr')}")]
    east = None
    for props in runs:
        if props is not None:
            element = props.find(qn("a:ea"))
            if element is not None and element.get("typeface"):
                east = element.get("typeface")
                break
    color = font.color
    if color.type is None:
        color = fallback.color
    clr = None
    if color.type is not None:
        if color.type.name == "RGB":
            clr = {"rgb": str(color.rgb)}
        elif color.type.name == "SCHEME":
            clr = {"theme": color.theme_color.name}
    return {"text": run.text, "font": face, "font_east_asia": east, "size_pt": size.pt if size is not None else None,
            "bold": bold, "color": clr, "size_origin": ("run" if font.size is not None else "paragraph") if size is not None else "unresolved"}


def _coordinates(shape):
    dims = [shape.left, shape.top, shape.width, shape.height]
    if any(x is None for x in dims):
        return None
    x, y, w, h = (round(value / 12700, 3) for value in dims)
    return [x, y, round(x + w, 3), round(y + h, 3)]


def parse_slides(path):
    deck = Presentation(path)
    slides = Document("pptx", path.name, title=deck.core_properties.title or None)
    slides.metadata.update(page_count=len(deck.slides), page_count_source="native", width_pt=deck.slide_width.pt, height_pt=deck.slide_height.pt)
    for index, slide in enumerate(deck.slides, 1):
        first_block = len(slides.blocks)
        prefix = f"pptx/slide/{index}"
        part = str(slide.part.partname).lstrip("/")
        title = slide.shapes.title
        if index == 1 and title is not None and not slides.title:
            slides.title = title.text.strip() or None
        slide_block = slides.add("slide", Source(prefix, slide=index, part=part), title.text if title is not None else "",
                                 notes=slide.notes_slide.notes_text_frame.text if slide.has_notes_slide and slide.notes_slide.notes_text_frame is not None else None,
                                 hidden=slide._element.get("show") == "0")

        def add_paragraphs(frame, shape_source, parent, is_title=False, role="body"):
            for pi, paragraph in enumerate(frame.paragraphs, 1):
                src = Source(f"{parent}/p/{pi}", slide=index, paragraph=pi, bbox=shape_source.bbox,
                             coordinate_space=shape_source.coordinate_space, part=part)
                slides.add("heading" if is_title and pi == 1 else "paragraph", src, paragraph.text, level=1 if is_title and pi == 1 else None,
                           parent=parent, role=role, runs=[_font_info(run, paragraph) for run in paragraph.runs],
                           list_level=paragraph.level, alignment=paragraph.alignment.name if paragraph.alignment is not None else None)

        def shapes_in(collection, parent, space):
            for z, shape in enumerate(collection, 1):
                point = Source(f"{parent}/shape/{shape.shape_id}", slide=index, bbox=_coordinates(shape), coordinate_space=space, part=part)
                is_title = title is not None and shape.shape_id == title.shape_id
                shape_type = shape.shape_type
                attrs = {"name": shape.name, "shape_id": shape.shape_id, "z_order": z, "rotation_deg": shape.rotation,
                         "shape_type": shape_type.name if shape_type is not None else None, "role": "title" if is_title else "body"}
                if shape_type == MSO_SHAPE_TYPE.GROUP:
                    xfrm = shape._element.find(f"{qn('p:grpSpPr')}/{qn('a:xfrm')}")
                    if xfrm is not None:
                        attrs["group_transform_emu"] = {etree.QName(node).localname: dict(node.attrib) for node in xfrm}
                    block = slides.add("shape", point, parent=parent, **attrs)
                    shapes_in(shape.shapes, block.id, f"group_pt:{block.id}")
                    continue
                if shape.has_table:
                    block = slides.add("table", point, parent=parent, rows=[], **attrs)
                    for ri, row in enumerate(shape.table.rows, 1):
                        cells = []
                        for ci, cell in enumerate(row.cells, 1):
                            if cell.is_spanned:
                                continue
                            cell_path = f"{block.id}/r/{ri}/c/{ci}"
                            cp = Source(cell_path, slide=index, part=part)
                            cell_block = slides.add("cell", cp, cell.text, parent=block.id, row=ri, column=ci,
                                                    rowspan=cell.span_height, colspan=cell.span_width)
                            cells.append({"row": ri, "column": ci, "rowspan": cell.span_height, "colspan": cell.span_width,
                                          "text": cell.text, "path": cell_path})
                            add_paragraphs(cell.text_frame, point, cell_block.id, role="cell")
                        block.attrs["rows"].append(cells)
                elif shape_type in {MSO_SHAPE_TYPE.PICTURE, MSO_SHAPE_TYPE.LINKED_PICTURE} or (shape.is_placeholder and shape._element.tag == qn("p:pic")):
                    try:
                        image = shape.image
                        attrs.update(available=True, width_px=image.size[0], height_px=image.size[1], mime_type=image.content_type,
                                     bytes=len(image.blob), sha256=sha256(image.blob).hexdigest())
                    except (AttributeError, KeyError, ValueError):
                        attrs["available"] = False
                        slides.warn("image_unavailable", "图片为外部链接或引用缺失，已记录位置。", point)
                    props = next(shape._element.iter(qn("p:cNvPr")), None)
                    block = slides.add("image", point, parent=parent, alt=props.get("descr") if props is not None else None, **attrs)
                else:
                    block = slides.add("textbox" if shape.has_text_frame else "shape", point, parent=parent, **attrs)
                    if shape.has_text_frame:
                        add_paragraphs(shape.text_frame, point, block.id, is_title, role="title" if is_title else "body")
                    if not shape.has_text_frame and shape_type not in {MSO_SHAPE_TYPE.LINE, MSO_SHAPE_TYPE.FREEFORM}:
                        slides.warn("pptx_opaque_shape", f"保留 {shape.name} 的位置；首版未展开该对象内部内容。", point)
                for mi, math in enumerate(shape._element.iter(MATH + "oMath"), 1):
                    fsrc = Source(f"{block.id}/formula/{mi}", slide=index, part=part, bbox=point.bbox, coordinate_space=space)
                    slides.add("formula", fsrc, "".join(t.text or "" for t in math.iter(MATH + "t")), parent=block.id,
                               notation="omml", omml=etree.tostring(math, encoding="unicode", with_tail=False))

        shapes_in(slide.shapes, slide_block.id, "slide_pt")
        texts = [b for b in slides.blocks[first_block:] if b.type in {"heading", "paragraph"} and b.text.strip()]
        rendered_chars = sum(len(re.sub(r"\s+", "", b.text)) for b in texts)
        measured = [r["size_pt"] for b in texts for r in b.attrs["runs"] if r["text"].strip() and r["size_pt"] is not None]
        unresolved = sum(1 for b in texts for r in b.attrs["runs"] if r["text"].strip() and r["size_pt"] is None)
        slide_block.attrs.update(text_chars=rendered_chars, text_paragraphs=len(texts), measured_min_font_pt=min(measured, default=None),
                                 unresolved_font_runs=unresolved)
        if unresolved:
            slides.warn("pptx_inherited_fonts", "部分字号由版式或母版继承，首版未确认其实际值。", slide_block.source)
    return slides
