"""Opt-in formatting changes for Word; keep all unrelated package parts verbatim."""
from pathlib import Path
import re
from zipfile import ZipFile

from docx import Document as WordDocument
from docx.shared import Cm, Pt
from docx.text.paragraph import Paragraph
from docx.text.run import Run

from .model import MaterialError
from .parse import parse_document
from .rules import run_checks
from .word import P, W, _is_inactive, _visible_text


def fix_docx(path, destination, profile, *, selected_rule_ids=None):
    src, dst = Path(path), Path(destination)
    if src.suffix.lower() != ".docx" or dst.suffix.lower() != ".docx":
        raise MaterialError("unsupported_fix", "自动调整仅支持 DOCX 输入和 DOCX 新副本。")
    if src.resolve() == dst.resolve() or dst.exists():
        raise MaterialError("destination_exists", "输出必须是新的 DOCX 路径，不能覆盖原件或现有文件。")
    doc = parse_document(src)
    if doc.metadata.get("track_revisions_enabled") or any(w["code"] in {"tracked_deletions", "tracked_changes"} for w in doc.warnings):
        raise MaterialError("tracked_document", "文档启用了修订或包含未处理的修订，请先处理修订再调整格式。")
    rules = {r["id"]: r for r in profile["format_rules"]}
    supported = {k for k, spec in rules.items() if spec["handler"] in {"word_fonts", "word_size", "word_spacing", "word_margins"}}
    if not supported:
        raise MaterialError("unsupported_fix", "此 profile 不提供 DOCX 自动调整。")
    if selected_rule_ids is not None and (set(selected_rule_ids) - supported):
        raise MaterialError("unsupported_fix", "可自动调整的规则只有：" + "、".join(sorted(supported)))
    apply_ids = set(selected_rule_ids) if selected_rule_ids is not None else supported
    before = run_checks(doc, profile)
    word = WordDocument(src)
    paragraphs = [element for element in word.element.body if element.tag == P]
    changes = []
    for entry in before["findings"]:
        fix = entry.get("fix")
        if not fix or entry["rule_id"] not in apply_ids:
            continue
        spec = rules[entry["rule_id"]]
        p = spec["params"]
        section = re.fullmatch(r"docx/section/(\d+)", fix["path"])
        target = re.fullmatch(r"docx/body/p/(\d+)", fix["path"])
        if fix["operation"] == "word_margins" and section:
            for side, cm in p.items():
                setattr(word.sections[int(section[1]) - 1], f"{side}_margin", Cm(cm))
        elif target:
            paragraph = Paragraph(paragraphs[int(target[1]) - 1], word)
            if fix["operation"] == "word_spacing":
                spacing = paragraph._p.get_or_add_pPr().get_or_add_spacing()
                spacing.set(W("lineRule"), p["kind"])
                spacing.set(W("line"), str(round(p["value"] * (240 if p["kind"] == "auto" else 20))))
            elif fix["operation"] in {"word_fonts", "word_size"}:
                for element in paragraph._p.iter(W("r")):
                    if _is_inactive(element, paragraph._p) or not _visible_text(element).strip():
                        continue
                    run = Run(element, paragraph)
                    if fix["operation"] == "word_fonts":
                        fonts = element.get_or_add_rPr().get_or_add_rFonts()
                        for axis, face in (("ascii", p["latin"]), ("hAnsi", p["latin"]), ("eastAsia", p["eastAsia"])):
                            fonts.set(W(axis), face)
                            theme_axis = W(axis + "Theme")
                            if theme_axis in fonts.attrib:
                                del fonts.attrib[theme_axis]
                    else:
                        run.font.size = Pt(p["pt"])
        else:
            raise MaterialError("bad_fix_target", f"无法定位自动调整目标：{fix['path']}")
        changes.append({"rule_id": entry["rule_id"], "source": entry["source"], "operation": fix["operation"],
                        "before": entry["observed"], "target": p})
    wrote = False
    try:
        with ZipFile(src) as archive:
            if any(name.lower().startswith("_xmlsignatures/") for name in archive.namelist()):
                raise MaterialError("signed_document", "此文件有数字签名，请使用无签名副本。")
            with dst.open("xb") as output:
                wrote = True
                if not changes:
                    with src.open("rb") as original:
                        from shutil import copyfileobj
                        copyfileobj(original, output)
                else:
                    partname = str(word.part.partname).lstrip("/")
                    with ZipFile(output, "w") as updated:
                        for member in archive.infolist():
                            data = word.part.blob if member.filename == partname else archive.read(member)
                            updated.writestr(member, data)
        after = run_checks(parse_document(dst), profile)
    except FileExistsError as exc:
        raise MaterialError("destination_exists", "自动调整不能覆盖已有文件。") from exc
    except Exception:
        if wrote:
            dst.unlink(missing_ok=True)
        raise
    return {"schema_version": "1.0", "profile_id": profile["id"], "filename": dst.name,
            "changes": changes, "before": before["summary"], "after": after}
