"""Local contract for B/C integration. All scores on this boundary use a 0–100 scale."""
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic, sleep
from typing import Annotated, Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

Score = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


@dataclass(frozen=True)
class ReviewRequest:
    task_id: str
    attempt: int
    version_id: str
    project_id: str
    file_path: Path
    original_name: str
    mime_type: str
    sha256: str
    profile_id: str
    profile: dict[str, Any]
    parsed_content: dict[str, Any] | None = None


class OutputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, revalidate_instances="always")


class Dimension(OutputModel):
    name: Text
    score: Score


class Finding(OutputModel):
    category: Text
    severity: Literal["low", "medium", "high"]
    location: Text
    description: Text
    suggestions: list[Text]


class ReviewOutput(OutputModel):
    overall_score: Score
    summary: Text
    dimensions: list[Dimension]
    findings: list[Finding]


class DocumentParser(Protocol):
    # Include all rule, model and schema revisions that can affect the parsed document.
    parser_key: str

    def parse(self, request: ReviewRequest, checkpoint: Callable[[], None]) -> dict[str, Any]:
        """Return a JSON object representing this file, independent of the review profile."""
        ...


class ReviewAgent(Protocol):
    def review(self, request: ReviewRequest, checkpoint: Callable[[], None]) -> ReviewOutput:
        """Run C review using parsed_content when B is configured. Check cancellation between I/O calls."""
        ...


class MockAgent:
    """Produces a fixed, clearly marked fixture for offline integration."""
    def __init__(self, step_seconds: float = 0.2):
        self.step_seconds = step_seconds

    def review(self, request: ReviewRequest, checkpoint: Callable[[], None]) -> ReviewOutput:
        finish_at = monotonic() + 4 * self.step_seconds
        while True:
            checkpoint()
            remaining = finish_at - monotonic()
            if remaining <= 0:
                break
            sleep(min(remaining, 0.15))
        return ReviewOutput(
            overall_score=75,
            summary="Mock Agent 联调示例。分数和问题均为固定样例，未经实际文档评审。",
            dimensions=[
                Dimension(name="论证完整性（模拟）", score=70),
                Dimension(name="表达清晰度（模拟）", score=80),
            ],
            findings=[Finding(
                category="证据支持（模拟）",
                severity="medium",
                location="示例位置：方案验证章节",
                description="示例问题：方案的验证依据需要补充。",
                suggestions=["示例建议：补充试验条件、样本规模和对照结果。"],
            )],
        )
