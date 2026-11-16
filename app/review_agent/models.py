"""Task C boundary types. No model response can address a filesystem path or run a tool."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


def utcnow():
    return datetime.now(timezone.utc)


class ReviewError(Exception):
    def __init__(self, code, message, *, retriable=False, http_status=None):
        super().__init__(message)
        self.code, self.retriable, self.http_status = code, retriable, http_status


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


NonEmpty = Annotated[str, StringConstraints(min_length=1, max_length=512)]
Quote = Annotated[str, StringConstraints(min_length=1, max_length=400)]
Comment = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=700)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
ShortId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.:-]{1,100}$")]
Severity = Literal["high", "medium", "low"]
MODELS = ("deepseek-flash", "deepseek-v4-pro")


class AgentConfig(Contract):
    model: Literal["deepseek-flash", "deepseek-v4-pro"] = "deepseek-flash"
    timeout_seconds: Annotated[float, Field(gt=0, le=120)] = 25.0
    task_timeout_seconds: Annotated[float, Field(gt=0, le=3600)] = 240.0
    temperature: Annotated[float, Field(ge=0, le=2)] = 0.2
    max_output_tokens: Annotated[int, Field(ge=256, le=8192)] = 2800
    retries: Annotated[int, Field(ge=0, le=3)] = 2
    input_limit_bytes: Annotated[int, Field(ge=10000, le=96000)] = 22000
    fragment_max_chars: Annotated[int, Field(ge=180, le=4000)] = 1500
    fragment_overlap_chars: Annotated[int, Field(ge=0, le=120)] = 65
    max_chunks: Annotated[int, Field(ge=1, le=120)] = 64
    max_image_bytes: Annotated[int, Field(ge=8192, le=2000000)] = 750000
    max_response_bytes: Annotated[int, Field(ge=8192, le=1048576)] = 262144


class SourceRef(Contract):
    path: NonEmpty
    page: int | None = None
    slide: int | None = None
    section: int | None = None
    paragraph: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    bbox: list[float] | None = None
    coordinate_space: str | None = None
    part: str | None = None


class TextSlice(Contract):
    block_id: NonEmpty
    start: Annotated[int, Field(ge=0)] = 0
    end: Annotated[int, Field(ge=1)] | None = None

    @model_validator(mode="after")
    def ordered(self):
        if self.end is not None and self.end <= self.start:
            raise ValueError("选段的结束位置必须大于起始位置")
        return self


class Selection(Contract):
    text: Annotated[list[TextSlice], Field(min_length=1, max_length=512)]
    images: Annotated[list[NonEmpty], Field(max_length=4)] = Field(default_factory=list)


class Approval(Contract):
    # Created by A only after the owner confirms the displayed scope.
    text_digest: Digest
    image_digest: Digest | None = None


class TaskInput(Contract):
    task_id: ShortId
    revision_id: ShortId
    profile_id: ShortId
    document: dict
    selection: Selection
    approval: Approval | None = None


class TextPreview(Contract):
    block_id: NonEmpty
    kind: str
    source: SourceRef
    start: int
    end: int
    text: str


class ImagePreview(Contract):
    block_id: NonEmpty
    source: SourceRef
    sha256: Digest
    mime_type: Literal["image/png", "image/jpeg"]
    bytes: int
    alt: str | None = None


class ScopePreview(Contract):
    task_id: ShortId
    revision_id: ShortId
    profile_id: ShortId
    text_digest: Digest
    image_digest: Digest | None = None
    text: list[TextPreview]
    images: list[ImagePreview]


class ModelEvidence(Contract):
    ref: Annotated[str, StringConstraints(pattern=r"^[ti][0-9]+$")]
    quote: Quote | None


class ModelDimension(Contract):
    criterion: NonEmpty
    score: Annotated[int, Field(ge=0, le=10)]
    rationale: Comment
    evidence: Annotated[list[ModelEvidence], Field(min_length=1, max_length=3)]


class ModelIssue(Contract):
    criterion: NonEmpty
    standard_index: Annotated[int, Field(ge=0, le=20)]
    impact: Literal["invalidates", "weakens", "presentation"]
    evidence: ModelEvidence
    suggestion: Comment


class ChunkReview(Contract):
    dimensions: Annotated[list[ModelDimension], Field(max_length=6)]
    issues: Annotated[list[ModelIssue], Field(max_length=6)]


class Location(Contract):
    block_id: NonEmpty
    source: SourceRef
    char_start: int | None = None
    char_end: int | None = None


class Evidence(Contract):
    kind: Literal["text", "image"]
    quote: str | None
    image_sha256: Digest | None = None


class Issue(Contract):
    id: NonEmpty
    location: Location
    severity: Severity
    criterion: NonEmpty
    criterion_name: NonEmpty
    standard_index: int
    review_standard: NonEmpty
    evidence: Evidence
    suggestion: Comment


class RunMeta(Contract):
    task_id: ShortId
    revision_id: ShortId
    profile_id: ShortId
    profile_version: int | None = None
    skill_id: str | None = None
    skill_version: int | None = None
    provider: Literal["mock", "deepseek"]
    model: NonEmpty
    started_at: datetime
    finished_at: datetime | None = None
    status: Literal["running", "completed", "failed"]
    text_count: int = 0
    image_count: int = 0
    chunk_count: int = 0
    reference_ids: list[str] = Field(default_factory=list)


class Attempt(Contract):
    task_id: ShortId
    profile_id: ShortId
    profile_version: int
    skill_id: NonEmpty
    skill_version: int
    model: NonEmpty
    chunk: int
    attempt: int
    request_time: datetime
    duration_ms: int
    status: Literal["completed", "failed"]
    error_code: str | None = None
    http_status: int | None = None
    input_bytes: int
    image_count: int


class ReviewResult(Contract):
    schema_version: Literal["1.0"] = "1.0"
    meta: RunMeta
    review: dict
    issues: list[Issue]
    total_score: float | None


class Failure(Contract):
    meta: RunMeta
    code: NonEmpty
    message: NonEmpty


class SuggestionDraft(Contract):
    task_id: ShortId
    revision_id: ShortId
    issue_id: NonEmpty
    version: int
    previous: Comment
    suggestion: Comment
