"""Three built-in, versioned review skills. B remains the authority for scoring criteria."""
from collections import Counter
from dataclasses import dataclass
import re

from .models import ChunkReview, ReviewError


@dataclass(frozen=True)
class Skill:
    id: str
    version: int
    material_type: str
    allowed_formats: tuple[str, ...]
    steps: tuple[str, ...]
    dimension_ids: tuple[str, ...]


WRITTEN = ("docx", "pdf", "txt", "markdown")
SKILLS = {
    "academic_paper": Skill("academic-paper-review", 1, "academic_paper", WRITTEN, (
        "找出研究问题，与既有方案比较并判断新增贡献。",
        "核对方法、样本、对照、采样范围及可复现信息。",
        "把数据和结论一一对应；检查引用和表达规范，不推断实际字体或页边距。",
    ), ("innovation", "methodology", "evidence", "writing_norms")),
    "competition_proposal": Skill("competition-proposal-review", 1, "competition_proposal", WRITTEN, (
        "核对目标面向谁、如何验证、与现有方案有什么差异。",
        "对照方案、进度、责任人、交付物与验收节点。",
        "核对预算分项、资源缺口与风险应对；只把对应届次规则作为参考。",
    ), ("objective", "solution", "schedule", "budget", "resources", "risk")),
    "ppt_defense": Skill("ppt-defense-review", 1, "ppt_defense", ("pptx",), (
        "按幻灯片顺序看问题、方案和数据能否串成清晰讲述。",
        "观察文字密度和视觉优先级。只有确实收到图片时才评价对应图像的可见表现。",
        "从明确的限时或讲述线索判断节奏；没有证据时不猜演讲时长、字号或版式。",
    ), ("logic", "density", "hierarchy", "readability", "pacing")),
}
RATING = "0–2：证据显示严重缺陷；3–5：主要环节缺失；6–8：基本成立且有明确改进处；9–10：证据充分。没有直接证据时省略该维度。"


def select_skill(profile, file_format):
    item = SKILLS.get(profile["material_type"])
    if not item or tuple(d["id"] for d in profile["dimensions"]) != item.dimension_ids:
        raise ReviewError("profile_incompatible", "该 profile 的维度与当前 Skill 不兼容。")
    if file_format not in item.allowed_formats:
        raise ReviewError("material_mismatch", "文件类型与所选评审 Skill 不匹配。")
    return item


def describe_skill(skill, profile):
    return {"id": skill.id, "version": skill.version, "material_type": skill.material_type,
            "inputs": ["approved_text", "separately_approved_PPT_images", "profile.dimensions", "retrieved_reference_notes"],
            "steps": list(skill.steps), "scoring": RATING, "criterion_ids": list(skill.dimension_ids),
            "citations": "只引用本段 ref；文字引用连续原句，图片引用对象并把 quote 填 null。",
            "standards": profile["dimensions"], "chunk_output_schema": ChunkReview.model_json_schema(),
            "merged_review_schema": profile["output_schema"]}


def _terms(value):
    value = value.casefold()
    words = re.findall(r"[a-z0-9]{2,}", value)
    for token in re.findall(r"[\u3400-\u9fff]+", value):
        words.extend(token[i:i+2] for i in range(len(token) - 1))
    return Counter(words)


def retrieve(items, profile, approved_text, *, max_items=3):
    """Rank only from approved text and dimension definitions; never transmit private expert cases."""
    query = _terms(approved_text)
    priorities = {d["id"]: d["weight"] for d in profile["dimensions"]}
    result = []
    for item in items:
        if profile["material_type"] not in item["material_types"] or item["kind"] not in {"official_reference", "instructional_case"}:
            continue
        matching = sorted(set(item["dimensions"]) & priorities.keys())
        if not matching:
            continue
        if item["kind"] == "official_reference":
            note = item["note"]
            title = item["source"]["title"]
        else:
            note = item["case"]["assessment_standard"] + " 教学改法：" + item["case"]["revision_suggestion"]
            title = "自编教学案例（模拟评阅）"
        terms = _terms(title + " " + item["competition"] + " " + note)
        relevance = sum(min(3, freq) * min(2, terms.get(term, 0)) for term, freq in query.items())
        if relevance == 0:
            continue
        score = 5 * relevance + sum(priorities[k] for k in matching) / 100
        result.append((score, item["id"], {"id": item["id"], "competition": item["competition"], "year": item["year"],
                                           "kind": item["kind"], "dimensions": matching, "note": note[:400]}))
    return [item for _, _, item in sorted(result, key=lambda row: (-row[0], row[1]))[:max_items]]
