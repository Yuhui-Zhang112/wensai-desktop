"""Local readers. File content never goes to an external service."""
from pathlib import Path
from zipfile import ZipFile

from .model import MaterialError

SUPPORTED = {".docx", ".pptx", ".pdf", ".txt", ".md", ".markdown"}
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_EXPANDED_BYTES = 256 * 1024 * 1024


def parse_document(path, *, encoding: str | None = None):
    """Return Document or a readable MaterialError; never return a fake empty result."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED:
        raise MaterialError("unsupported_format", f"暂不支持 {ext or '无扩展名'}，请转换为 DOCX、PPTX、PDF、TXT 或 Markdown。")
    try:
        size = path.stat().st_size
        if size > MAX_UPLOAD_BYTES:
            raise MaterialError("file_too_large", "首版仅处理不超过 64 MiB 的材料。")
        if ext in {".docx", ".pptx"}:
            with ZipFile(path) as archive:
                if sum(entry.file_size for entry in archive.infolist()) > MAX_EXPANDED_BYTES:
                    raise MaterialError("package_too_large", "Office 文件解压后超过 256 MiB。")
        if ext == ".docx":
            from .word import parse_word
            result = parse_word(path)
        elif ext == ".pptx":
            from .slides import parse_slides
            result = parse_slides(path)
        elif ext == ".pdf":
            from .pdf import parse_pdf
            result = parse_pdf(path)
        else:
            from .text import parse_text
            result = parse_text(path, markdown=ext != ".txt", encoding=encoding)
        result.metadata["file_size_bytes"] = size
        return result
    except MaterialError:
        raise
    except FileNotFoundError as exc:
        raise MaterialError("not_found", f"找不到材料：{path.name}") from exc
    except UnicodeError as exc:
        raise MaterialError("invalid_encoding", "文本编码无法识别；请用 UTF-8 保存或显式指定编码。") from exc
    except LookupError as exc:
        if ext in {".txt", ".md", ".markdown"} and encoding is not None:
            raise MaterialError("invalid_encoding", f"不认识指定的文本编码：{encoding}") from exc
        raise MaterialError("parse_failed", f"无法解析 {path.name}：{exc}") from exc
    except Exception as exc:
        raise MaterialError("parse_failed", f"无法解析 {path.name}：{exc}") from exc
