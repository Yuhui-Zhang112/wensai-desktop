"""Generate original fixtures and the independent expectations used by Task B."""
import json
from pathlib import Path
from struct import pack
from zlib import compress, crc32

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt
from io import BytesIO
import pymupdf
from pptx import Presentation
from pptx.util import Inches, Pt as SlidePt

def _fixture_png():
    def chunk(kind, payload):
        return pack(">I", len(payload)) + kind + payload + pack(">I", crc32(kind + payload))
    width, height = 96, 64
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            distance = (x - 48) ** 2 + (y - 30) ** 2
            rows.extend((40, 108, 166) if distance < 22 ** 2 else (224, 237, 247))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)) + chunk(b"IDAT", compress(rows)) + chunk(b"IEND", b"")


IMAGE = _fixture_png()


def write_word(target, *, proposal, good):
    doc = Document()
    doc.core_properties.title = "雨水采集教学原型" if proposal else "雨水采集传感器校准实验"
    for section in doc.sections:
        section.top_margin = section.bottom_margin = section.left_margin = section.right_margin = Cm(2.54)
        if not good:
            section.left_margin = Cm(1.4)
    doc.sections[0].header.paragraphs[0].text = "任务 B 教学验收样例"
    doc.add_heading(doc.core_properties.title, 0)

    def body(text, error=False):
        para = doc.add_paragraph()
        para.paragraph_format.line_spacing = 1 if not good and error else 1.5
        run = para.add_run(text)
        run.font.name = "Arial" if not good and error else "Times New Roman"
        run.font.size = Pt(9 if not good and error else 12)
        run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "黑体" if not good and error else "宋体")
        return para

    if proposal:
        if good:
            doc.add_heading("目录", 1)
            body("项目目标……1")
            body("技术方案……1")
        sections = [("项目目标", "在十次模拟降雨中测量水量，平均测量偏差不超过 5%。"),
                    ("技术方案", "使用量筒作为基线，比较传感器与量筒的雨量读数。"),
                    ("进度安排", "第 1 月搭建原型；第 2 月采样；第 3 月验收。"),
                    ("经费预算", "传感器 2 件，每件 100 元；量筒 1 件，50 元；共计 250 元。"),
                    ("团队与资源", "搭建、采样与分析各一人，实验台和量筒已登记。"),
                    ("风险与应对", "若漂移超过 5%，重新校准并补测两组。")]
        for idx, (name, text) in enumerate(sections):
            if not good and name in {"经费预算", "风险与应对"}:
                continue
            doc.add_heading(name, 3 if not good and idx == 1 else 1)
            body(text, error=idx == 0)
    else:
        doc.add_heading("摘要", 1)
        body("用参考量筒比较十组传感器读数，验证采集原型。", error=True)
        if good:
            body("关键词：雨水；测量；校准")
        doc.add_heading("实验方法", 1 if good else 3)
        body("全程保持光照条件一致，并复核 Sample A 的校准曲线。")

    pic = doc.add_picture(BytesIO(IMAGE), width=Cm(2))
    pic._inline.docPr.set("descr", "教学样例中的传感器示意图")
    if good:
        doc.add_paragraph("图1 传感器示意图", style="Caption")
    else:
        doc.add_paragraph("表1 错放且重复的题注", style="Caption")
    doc.add_paragraph("表1 样例数据", style="Caption")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "测量条件", "读数"
    t.cell(1, 0).text, t.cell(1, 1).text = "模拟小雨", "8 mL"
    if not proposal:
        p = doc.add_paragraph()
        omml_block = OxmlElement("m:oMathPara")
        formula, run, text = (OxmlElement(name) for name in ("m:oMath", "m:r", "m:t"))
        text.text = "y=2x"
        run.append(text)
        formula.append(run)
        omml_block.append(formula)
        p._p.append(omml_block)
        if good:
            p.add_run("（1）")
        if good:
            doc.add_heading("参考文献", 1)
            doc.add_paragraph("[1] 自编教学参考资料。")
    doc.save(target)


def write_ppt(target, *, good):
    ppt = Presentation()
    ppt.core_properties.title = "雨水采集项目答辩"
    for i, title in enumerate(("研究目标", "校准结果", "进度及风险"), 1):
        slide = ppt.slides.add_slide(ppt.slide_layouts[5])
        slide.shapes.title.text = title
        slide.shapes.title.text_frame.paragraphs[0].runs[0].font.size = SlidePt(32 if good else 14)
        text = slide.shapes.add_textbox(Inches(1), Inches(2), Inches(7), Inches(1))
        first = text.text_frame.paragraphs[0].add_run()
        first.text = "以十组采样验证偏差。" if good else "没有数据，只有重复的结论。" * 15
        first.font.size = SlidePt(20 if good else 11)
        if i == 2:
            slide.shapes.add_picture(BytesIO(IMAGE), Inches(1), Inches(3), Inches(1))
            table = slide.shapes.add_table(2, 2, Inches(2.5), Inches(3), Inches(4), Inches(1)).table
            for x, y, word in ((0, 0, "项目"), (0, 1, "数量"), (1, 0, "采样"), (1, 1, "十组")):
                table.cell(x, y).text = word
                table.cell(x, y).text_frame.paragraphs[0].runs[0].font.size = SlidePt(20)
        if i == 1:
            slide.notes_slide.notes_text_frame.text = "先说明目标，建议 40 秒。"
    ppt.save(target)


def write_pdf(target, *, scan=False):
    with pymupdf.open() as doc:
        doc.set_metadata({"title": "Sensor Calibrations"})
        page = doc.new_page()
        if not scan:
            page.insert_text((45, 55), "Abstract", fontsize=18)
            page.insert_text((45, 85), "Sample A: Sensor calibration, ten observations.", fontsize=12)
            page.insert_text((45, 110), "y = 2x", fontsize=12)
            for x in (40, 120, 200):
                page.draw_line((x, 240), (x, 300), color=(0, 0, 0))
            for y in (240, 270, 300):
                page.draw_line((40, y), (200, y), color=(0, 0, 0))
            for x, y, value in ((47, 258, "Case"), (127, 258, "Reading"), (47, 288, "Baseline"), (127, 288, "8 mL")):
                page.insert_text((x, y), value, fontsize=10)
        with pymupdf.open(stream=IMAGE, filetype="png") as img:
            page.insert_image(pymupdf.Rect(50, 130, 100, 180), pixmap=img[0].get_pixmap())
        doc.new_page().insert_text((45, 55), "Second page offset check.")
        doc.save(target)


def make_samples(directory):
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    for prefix, proposal in (("academic", False), ("proposal", True)):
        for good in (True, False):
            write_word(out / f"{prefix}_{'ok' if good else 'errors'}.docx", proposal=proposal, good=good)
    write_ppt(out / "defense_ok.pptx", good=True)
    write_ppt(out / "defense_errors.pptx", good=False)
    write_pdf(out / "material.pdf")
    write_pdf(out / "scan_like.pdf", scan=True)
    (out / "material.txt").write_bytes("# 采样记录\r\n\r\n1.1 技术方案\r\n保留 Windows 换行和原始文字。\r\n".encode())
    (out / "material.md").write_text(
        "# 校准速记\n\n一项测试 ![原型照片](images/prototype.png) 与公式 $y=2x$。\n\n"
        "## 数据\n\n| 条件 | 读数 |\n| --- | --- |\n| 对照 | $x=1$ |\n\n$$\ny=2x\n$$\n",
        encoding="utf-8", newline="\n")
    (out / "images").mkdir(exist_ok=True)
    (out / "images" / "prototype.png").write_bytes(IMAGE)
    (out / "corrupt.docx").write_bytes(b"This is not an Office package.\n")
    expected = {
        "academic_ok.docx": {"profile": "academic-paper-v1", "fail": []},
        "academic_errors.docx": {"profile": "academic-paper-v1",
            "fail": ["word-fonts", "word-size", "word-spacing", "word-margins", "headings", "captions", "caption-numbers", "paper-sections", "formula-labels", "references"]},
        "proposal_ok.docx": {"profile": "competition-proposal-v1", "rendered_page_count": 2, "fail": []},
        "proposal_errors.docx": {"profile": "competition-proposal-v1", "rendered_page_count": 35,
            "fail": ["word-fonts", "word-size", "word-spacing", "word-margins", "headings", "captions", "caption-numbers", "proposal-toc", "proposal-sections", "proposal-pages"]},
        "defense_ok.pptx": {"profile": "ppt-defense-v1", "fail": []},
        "defense_errors.pptx": {"profile": "ppt-defense-v1", "fail": ["slide-density", "slide-fonts", "slide-hierarchy"]}
    }
    (out / "expected_format_findings.json").write_text(json.dumps(expected, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    import sys
    make_samples(sys.argv[1])
