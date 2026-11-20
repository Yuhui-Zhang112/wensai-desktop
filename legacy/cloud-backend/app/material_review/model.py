"""JSON contract shared by all parsers."""
from dataclasses import asdict, dataclass, field
from typing import Any


class MaterialError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass
class Source:
    path: str
    page: int | None = None
    slide: int | None = None
    section: int | None = None
    paragraph: int | None = None
    line_start: int | None = None
    line_end: int | None = None
    bbox: list[float] | None = None
    coordinate_space: str | None = None
    part: str | None = None


@dataclass
class Block:
    id: str
    type: str
    source: Source
    text: str = ""
    level: int | None = None
    parent_id: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Document:
    format: str
    filename: str
    title: str | None = None
    blocks: list[Block] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    raw_text: str | None = None
    schema_version: str = "1.0"

    def add(self, kind: str, source: Source, text="", *, level=None, parent=None, **attrs) -> Block:
        block = Block(source.path, kind, source, text, level, parent, attrs)
        self.blocks.append(block)
        if self.title is None and (kind == "title" or kind == "heading"):
            self.title = text or None
        return block

    def warn(self, code: str, message: str, source: Source | None = None):
        self.warnings.append({"code": code, "message": message, "source": asdict(source) if source else None})

    def to_dict(self):
        return asdict(self)
