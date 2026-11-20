"""Original teaching fixtures. This module never contacts a provider."""
from io import BytesIO
import json
from pathlib import Path

from docx import Document
import pymupdf
from pptx import Presentation
from pptx.util import Inches

from app.material_review import parse_document
from app.review_agent import Approval, Selection, TaskInput, TextSlice, preview_scope
from app.review_agent.provider import MOCK_MATCHES
import base64

IMAGE = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQImWP4z8DwHwAFgAI/ScLbtAAAAABJRU5ErkJggg==")

OFF_SCOPE = "未授权片段-LOCAL-ONLY-4279"
PROFILES = {
    "paper.docx": "academic-paper-v1",
    "proposal.pdf": "competition-proposal-v1",
    "defense.pptx": "ppt-defense-v1",
}
SKILLS = {
    "paper.docx": "academic-paper-review",
    "proposal.pdf": "competition-proposal-review",
    "defense.pptx": "ppt-defense-review",
}


def make_samples(dest):
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    doc = Document()
    doc.add_heading("采样方法教学样例", 0)
    doc.add_paragraph(OFF_SCOPE)
    doc.add_heading("研究方法", 1)
    doc.add_paragraph("校准后记录到一个读数。所有实验只测量一次，据此宣称结果稳定。")
    doc.save(dest / "paper.docx")
    with pymupdf.open() as pdf:
        pdf.new_page().insert_text((45, 95), OFF_SCOPE, fontname="china-s")
        page = pdf.new_page()
        page.insert_text((45, 95), "经费预算：预算总额为3000元，未列分项，未说明采购数量和依据。", fontname="china-s")
        pdf.save(dest / "proposal.pdf")
    ppt = Presentation()
    first = ppt.slides.add_slide(ppt.slide_layouts[5])
    first.shapes.title.text = OFF_SCOPE
    second = ppt.slides.add_slide(ppt.slide_layouts[5])
    second.shapes.title.text = "答辩安排"
    frame = second.shapes.add_textbox(Inches(1), Inches(2), Inches(8), Inches(1)).text_frame
    frame.text = "答辩限时5分钟，本页计划讲6分钟。其余页没有时间安排。"
    second.shapes.add_picture(BytesIO(IMAGE), Inches(1), Inches(3), Inches(2))
    ppt.save(dest / "defense.pptx")
    for name in PROFILES:
        profile = PROFILES[name]
        task = make_task(dest / name)
        (dest / f"{Path(name).stem}-selection.json").write_text(task.selection.model_dump_json(indent=2) + "\n", encoding="utf-8")
        if name == "paper.docx":
            # Plain synthetic verification material makes the network approval preview easy to review.
            (dest / "live-check.md").write_text("# 教学案例\n\n所有实验只测量一次。只得到一个读数，却声称结论稳定。\n", encoding="utf-8")
            demo = make_task(dest / "live-check.md", profile=profile, skill_id=SKILLS[name])
            (dest / "live-check-selection.json").write_text(demo.selection.model_dump_json(indent=2) + "\n", encoding="utf-8")
    (dest / "test-config.json").write_text(json.dumps({"retries": 1, "timeout_seconds": 20, "task_timeout_seconds": 75}, indent=2) + "\n", encoding="utf-8")


def make_task(path, *, approval=True, image=False, profile=None, skill_id=None):
    doc = parse_document(path).to_dict()
    phrase = MOCK_MATCHES[skill_id or SKILLS[path.name]][0]
    block = next(b for b in doc["blocks"] if b["type"] == "paragraph" and (phrase in b["text"] or phrase.replace("3000", "3 0 0 0") in b["text"]))
    position = block["text"].index(phrase) if phrase in block["text"] else 0
    selected = TextSlice(block_id=block["id"], start=position, end=len(block["text"]))
    images = [b["id"] for b in doc["blocks"] if b["type"] == "image"] if image else []
    task = TaskInput(task_id=path.stem, revision_id="synthetic-r1", profile_id=profile or PROFILES[path.name], document=doc,
                     selection=Selection(text=[selected], images=images))
    if approval:
        scope = preview_scope(task)
        task = task.model_copy(update={"approval": Approval(text_digest=scope.text_digest, image_digest=scope.image_digest)})
    return task


if __name__ == "__main__":
    import sys
    make_samples(sys.argv[1])
