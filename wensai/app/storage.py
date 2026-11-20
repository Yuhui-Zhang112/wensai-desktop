"""Project-scoped file operations. Database paths are relative to one project."""
from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import stat
import zipfile
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import BinaryIO
from xml.etree import ElementTree as ET
from xml.parsers import expat

from pypdf import PdfReader

from .common import ApiError
from .db import new_id


AREAS = ("raw", "working", "output")
PDF = "application/pdf"
OFFICE = {
    ".docx": ("word/document.xml", "wordprocessingml.document.main", "wordprocessingml", "document"),
    ".pptx": ("ppt/presentation.xml", "presentationml.presentation.main", "presentationml", "presentation"),
}
MIME_TYPES = {
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".pdf": PDF,
}
CONTENT_TYPES_NS = "{http://schemas.openxmlformats.org/package/2006/content-types}"
REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
OFFICE_RELS = {
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/officeDocument",
}
CHUNK = 1024 * 1024
# OPC metadata and the main XML are inspected with explicit expansion limits.
MAX_METADATA = 4 * CHUNK
MAX_MAIN_XML = 256 * CHUNK
GENERATED_NAME = re.compile(r"(?:[a-f0-9]{32}|[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12})\.(?:docx|pptx|pdf|txt|md)")


def _unsafe() -> ApiError:
    return ApiError(400, "UNSAFE_PATH", "文件路径必须位于当前项目的受管目录内。")


def _linked(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, "is_junction", lambda: False)())


def project_directory(file_root: Path, project_id: str) -> Path:
    if not re.fullmatch(r"[a-zA-Z0-9_-]{1,128}", project_id):
        raise _unsafe()
    project = file_root.resolve() / project_id
    if _linked(project) or project.resolve() != project:
        raise _unsafe()
    return project


def initialize_project(file_root: Path, project_id: str) -> None:
    project = project_directory(file_root, project_id)
    project.mkdir(mode=0o700)
    try:
        for area in AREAS:
            (project / area).mkdir(mode=0o700)
        _sync_directory(project)
        _sync_directory(project.parent)
    except OSError:
        remove_empty_project(file_root, project_id)
        raise


def remove_empty_project(file_root: Path, project_id: str) -> None:
    project = project_directory(file_root, project_id)
    for area in AREAS:
        folder = project / area
        if folder.is_dir() and not _linked(folder):
            folder.rmdir()
    project.rmdir()


def _path(file_root: Path, project_id: str, relative_path: str) -> Path:
    parts = relative_path.split("/")
    if (len(parts) != 2 or parts[0] not in AREAS or parts[1] in {"", ".", ".."}
            or any(ch in relative_path for ch in ("\\", "\0", ":"))):
        raise _unsafe()
    project = project_directory(file_root, project_id)
    path = project / parts[0] / parts[1]
    if _linked(path.parent) or _linked(path) or path.resolve() != path:
        raise _unsafe()
    return path


def resolve_file(file_root: Path, project_id: str, relative_path: str) -> Path:
    path = _path(file_root, project_id, relative_path)
    if not path.is_file():
        raise ApiError(409, "FILE_MISSING", "数据库所记录的版本文件在本地缺失。")
    return path


def safe_unlink(file_root: Path, project_id: str, relative_path: str) -> None:
    """Only regular, in-project files may be removed; callers supply a stored path."""
    path = _path(file_root, project_id, relative_path)
    if os.unlink in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
        # Pin all directories so a concurrent rename cannot redirect the deletion.
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        with ExitStack() as stack:
            descriptor = os.open(file_root.resolve(), flags)
            stack.callback(os.close, descriptor)
            for part in (project_id, path.parent.name):
                descriptor = os.open(part, flags, dir_fd=descriptor)
                stack.callback(os.close, descriptor)
            try:
                mode = os.stat(path.name, dir_fd=descriptor, follow_symlinks=False).st_mode
            except FileNotFoundError:
                return
            if not stat.S_ISREG(mode):
                raise _unsafe()
            os.unlink(path.name, dir_fd=descriptor)
    elif path.exists():
        if not path.is_file():
            raise _unsafe()
        path.unlink()


def check_name(filename: str | None) -> tuple[str, str]:
    if not filename or len(filename) > 255:
        raise ApiError(400, "INVALID_FILENAME", "文件名须为 1 至 255 个字符。")
    if (PureWindowsPath(filename).name != filename or ":" in filename
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in filename)):
        raise _unsafe()
    extension = Path(filename).suffix.lower()
    if extension not in MIME_TYPES:
        raise ApiError(415, "UNSUPPORTED_FILE_TYPE", "支持 DOCX、PPTX、PDF、TXT 和 Markdown。")
    return filename, extension


class _NoDtdTreeBuilder(ET.TreeBuilder):
    def doctype(self, name, pubid, system):
        raise ValueError("DTD is not permitted in office parts")


def _metadata(archive: zipfile.ZipFile, name: str) -> ET.Element:
    if archive.getinfo(name).file_size > MAX_METADATA:
        raise ValueError("OPC manifest exceeds limits")
    data = archive.read(name)
    return ET.fromstring(data, parser=ET.XMLParser(target=_NoDtdTreeBuilder()))


def _main_xml(archive: zipfile.ZipFile, member: str, expected_roots: set[str]) -> None:
    if archive.getinfo(member).file_size > MAX_MAIN_XML:
        raise ValueError("main XML exceeds limits")
    parser = expat.ParserCreate(namespace_separator=" ")
    first = True

    def start(name: str, _attrs: dict) -> None:
        nonlocal first
        if first and name not in expected_roots:
            raise ValueError("wrong document root")
        first = False

    def reject_dtd(*_args: object) -> None:
        raise ValueError("unexpected DTD")

    parser.StartElementHandler = start
    parser.StartDoctypeDeclHandler = reject_dtd
    with archive.open(member) as stream:
        while chunk := stream.read(CHUNK):
            parser.Parse(chunk, False)
        parser.Parse(b"", True)


def _validate_office(stream: BinaryIO, extension: str) -> None:
    member, content_type, namespace, element = OFFICE[extension]
    with zipfile.ZipFile(stream) as archive:
        names = archive.namelist()
        if len(set(names)) != len(names):
            raise ValueError("duplicate package entry")
        manifest = _metadata(archive, "[Content_Types].xml")
        rels = _metadata(archive, "_rels/.rels")
        expected_type = "application/vnd.openxmlformats-officedocument." + content_type + "+xml"
        if manifest.tag != CONTENT_TYPES_NS + "Types" or not any(
            node.get("PartName") == "/" + member and node.get("ContentType") == expected_type
            for node in manifest.findall(CONTENT_TYPES_NS + "Override")
        ):
            raise ValueError("document content type mismatch")
        if rels.tag != REL_NS + "Relationships" or not any(
            node.get("Type") in OFFICE_RELS and node.get("Target") in {member, "/" + member}
            and node.get("TargetMode", "Internal") == "Internal"
            for node in rels.findall(REL_NS + "Relationship")
        ):
            raise ValueError("missing office document relationship")
        _main_xml(archive, member, {
            f"http://schemas.openxmlformats.org/{namespace}/2006/main {element}",
            f"http://purl.oclc.org/ooxml/{namespace}/main {element}",
        })


def validate_type(stream: BinaryIO, extension: str) -> None:
    try:
        stream.seek(0)
        if extension in {".txt", ".md"}:
            import codecs
            decoder = codecs.getincrementaldecoder("utf-8-sig")()
            size = 0
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if '\0' in decoder.decode(chunk):
                    raise ValueError("binary content in text material")
            decoder.decode(b'', final=True)
            if size == 0:
                raise ValueError("empty file")
        elif extension == ".pdf":
            # Inspect the catalog and page-tree type without extracting page content.
            reader = PdfReader(stream, strict=True)
            if reader.is_encrypted:
                raise ApiError(415, "ENCRYPTED_DOCUMENT", "请先导出未加密的 PDF。")
            catalog = reader.trailer["/Root"]
            if catalog.get("/Type") != "/Catalog" or catalog["/Pages"].get("/Type") != "/Pages":
                raise ValueError("invalid PDF catalog")
        else:
            if stream.read(4) != b"PK\x03\x04":
                raise ValueError("invalid ZIP signature")
            stream.seek(0)
            _validate_office(stream, extension)
    except ApiError:
        raise
    except Exception as exc:
        # Parsing libraries can raise several exception types for malformed containers.
        raise ApiError(415, "INVALID_FILE_CONTENT", "文件结构无效、受保护或与扩展名不一致。") from exc


@dataclass(frozen=True)
class StoredUpload:
    id: str
    original_name: str
    relative_path: str
    size_bytes: int
    mime_type: str
    sha256: str


def _sync_directory(directory: Path) -> None:
    # NTFS does not expose directory handles through os.open on Windows.
    if os.name == "posix":
        fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def store_upload(file_root: Path, project_id: str, area: str, filename: str | None,
                 stream: BinaryIO, max_bytes: int) -> StoredUpload:
    name, extension = check_name(filename)
    file_id = new_id()
    relative = f"{area}/{file_id}{extension}"
    path = _path(file_root, project_id, relative)
    digest = hashlib.sha256()
    size = 0
    # Exclusive creation makes every accepted version immutable, even on an ID collision.
    handle = path.open("x+b")
    try:
        with handle:
            while chunk := stream.read(CHUNK):
                size += len(chunk)
                if size > max_bytes:
                    raise ApiError(413, "FILE_TOO_LARGE", "文件大小超过单文件限制。")
                digest.update(chunk)
                handle.write(chunk)
            handle.flush()
            validate_type(handle, extension)
            os.fsync(handle.fileno())
        _sync_directory(path.parent)
    except BaseException:
        safe_unlink(file_root, project_id, relative)
        raise
    return StoredUpload(file_id, name, relative, size, MIME_TYPES[extension], digest.hexdigest())


def copy_export(file_root: Path, project_id: str, relative_path: str, filename: str,
                expected_digest: str) -> tuple[Path, str]:
    source = resolve_file(file_root, project_id, relative_path)
    _, extension = check_name(filename)
    relative = f"output/{new_id()}{extension}"
    target = _path(file_root, project_id, relative)
    digest = hashlib.sha256()
    handle = target.open("xb")
    try:
        with handle, source.open("rb") as original:
            while chunk := original.read(CHUNK):
                digest.update(chunk)
                handle.write(chunk)
        if digest.hexdigest() != expected_digest:
            raise ApiError(409, "FILE_CHANGED", "版本文件的 SHA-256 与入库记录不符。")
    except BaseException:
        safe_unlink(file_root, project_id, relative)
        raise
    return target, relative


def recover_storage(conn: sqlite3.Connection, file_root: Path) -> None:
    """Startup only, under the service lock. Never follow links or touch unrelated names."""
    referenced = {(row[0], row[1]) for row in conn.execute("SELECT project_id,relative_path FROM files")}
    for row in conn.execute("SELECT id FROM projects"):
        project_id = row[0]
        try:
            project = project_directory(file_root, project_id)
        except (ApiError, OSError, RuntimeError):
            continue
        for area in AREAS:
            folder = project / area
            if _linked(folder) or not folder.is_dir():
                continue
            for entry in folder.iterdir():
                relative = f"{area}/{entry.name}"
                if ((project_id, relative) not in referenced and GENERATED_NAME.fullmatch(entry.name)
                        and not _linked(entry) and entry.is_file()):
                    safe_unlink(file_root, project_id, relative)
