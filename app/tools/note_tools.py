from __future__ import annotations

import importlib.util
import re
import zlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from app.tools.base import Tool
from app.tools.registry import ToolRegistry


SUPPORTED_NOTE_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".pdf",
    ".docx",
}
DEFAULT_READ_LIMIT = 30_000
PDF_STDLIB_MAX_BYTES = 20_000_000
SEARCH_MAX_FILE_BYTES = 20_000_000
SEARCH_SNIPPET_LIMIT = 240


def register_note_tools(registry: ToolRegistry, notes_dir: Path) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)

    def resolve_note_path(relative_path: str) -> Path:
        # 工具只允许访问 notes/ 内部的受支持学习资料，防止模型通过 ../ 读取项目外文件。
        target = (notes_dir / relative_path).resolve()
        root = notes_dir.resolve()
        if target != root and root not in target.parents:
            raise ValueError("Note path must stay inside the notes directory.")
        if target.suffix.lower() not in SUPPORTED_NOTE_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_NOTE_SUFFIXES))
            raise ValueError(f"Unsupported note file type. Supported types: {supported}")
        return target

    def list_notes(_: dict[str, Any]) -> str:
        files = [
            path.relative_to(notes_dir).as_posix()
            for path in iter_note_paths(notes_dir)
            if path.is_file() and path.suffix.lower() in SUPPORTED_NOTE_SUFFIXES
        ]
        if not files:
            return "notes/ 目录下还没有可读取的学习资料。"
        return "\n".join(files)

    def read_note(arguments: dict[str, Any]) -> str:
        path = resolve_note_path(str(arguments.get("path", "")).strip())
        if not path.exists():
            return f"未找到学习资料：{path.relative_to(notes_dir).as_posix()}"

        raw_limit = arguments.get("max_chars", DEFAULT_READ_LIMIT)
        try:
            max_chars = int(raw_limit)
        except (TypeError, ValueError):
            max_chars = DEFAULT_READ_LIMIT

        text = extract_note_text(path, max_chars=max_chars)
        return limit_text(text, max_chars=max_chars)

    def search_notes(arguments: dict[str, Any]) -> str:
        # 当前是最小关键词搜索，不是 RAG。
        # 后续可以把 extract_note_text 的输出替换成 Markdown/PDF/DOCX 切块 + embedding + 向量检索。
        query = str(arguments.get("query", "")).strip()
        if not query:
            return "请提供搜索关键词。"
        include_large_files = bool(arguments.get("include_large_files", False))

        matches: list[str] = []
        errors: list[str] = []
        query_lower = query.lower()
        for path in iter_note_paths(notes_dir):
            rel = path.relative_to(notes_dir).as_posix()
            if not include_large_files and path.stat().st_size > SEARCH_MAX_FILE_BYTES:
                errors.append(
                    f"{rel}: 文件较大，默认跳过。需要时请直接读取该文件，"
                    "或将 include_large_files 设为 true。"
                )
                continue
            try:
                text = extract_note_text(path)
            except ValueError as exc:
                errors.append(f"{rel}: 读取失败：{exc}")
                continue

            for line_number, line in enumerate(text.splitlines() or [text], start=1):
                if query_lower in line.lower():
                    snippet = limit_line(line.strip(), SEARCH_SNIPPET_LIMIT)
                    matches.append(f"{rel}:{line_number}: {snippet}")
                    break

        if not matches:
            if errors:
                return f"没有在 notes/ 中找到：{query}\n\n部分文件未能搜索：\n" + "\n".join(errors)
            return f"没有在 notes/ 中找到：{query}"
        return "\n".join(matches)

    registry.register(
        Tool(
            name="list_notes",
            description="列出 notes 目录下可读取的学习资料，支持 Markdown、TXT、PDF 和 DOCX。",
            parameters={"type": "object", "properties": {}, "additionalProperties": False},
            handler=list_notes,
        )
    )
    registry.register(
        Tool(
            name="read_note",
            description="读取 notes 目录下的一份学习资料，支持 Markdown、TXT、PDF 和 DOCX。",
            parameters={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "相对于 notes 目录的资料路径，例如 agent.md 或 paper.pdf。",
                    },
                    "max_chars": {
                        "type": "integer",
                        "description": "最多返回多少字符，避免把大文件完整塞进模型上下文。",
                        "minimum": 1,
                        "maximum": 100000,
                    },
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            handler=read_note,
        )
    )
    registry.register(
        Tool(
            name="search_notes",
            description="按关键词搜索 notes 目录下的 Markdown、TXT、PDF 和 DOCX 学习资料。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "要搜索的关键词。",
                    },
                    "include_large_files": {
                        "type": "boolean",
                        "description": "是否搜索超过默认大小上限的大文件；可能明显变慢。",
                    }
                },
                "required": ["query"],
                "additionalProperties": False,
            },
            handler=search_notes,
        )
    )


def extract_note_text(path: Path, max_chars: int | None = None) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return read_text_file(path)
    if suffix == ".docx":
        return read_docx_file(path)
    if suffix == ".pdf":
        return read_pdf_file(path, max_chars=max_chars)
    raise ValueError(f"Unsupported note file type: {suffix}")


def iter_note_paths(notes_dir: Path) -> list[Path]:
    priority = {
        ".md": 0,
        ".markdown": 0,
        ".txt": 1,
        ".docx": 2,
        ".pdf": 3,
    }
    return sorted(
        (
            path
            for path in notes_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in SUPPORTED_NOTE_SUFFIXES
        ),
        key=lambda path: (priority[path.suffix.lower()], path.relative_to(notes_dir).as_posix()),
    )


def read_text_file(path: Path) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError:
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def read_docx_file(path: Path) -> str:
    try:
        with ZipFile(path) as archive:
            xml_text = archive.read("word/document.xml")
    except KeyError as exc:
        raise ValueError("DOCX file does not contain word/document.xml.") from exc
    except BadZipFile as exc:
        raise ValueError("DOCX file is not a valid ZIP package.") from exc

    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ValueError("DOCX document XML is invalid.") from exc

    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        parts = [
            text_node.text
            for text_node in paragraph.findall(".//w:t", namespace)
            if text_node.text
        ]
        if parts:
            paragraphs.append("".join(parts))
    return "\n".join(paragraphs)


def read_pdf_file(path: Path, max_chars: int | None = None) -> str:
    if importlib.util.find_spec("pypdf"):
        return read_pdf_with_pypdf(path, max_chars=max_chars)
    if importlib.util.find_spec("PyPDF2"):
        return read_pdf_with_pypdf2(path, max_chars=max_chars)
    if path.stat().st_size > PDF_STDLIB_MAX_BYTES:
        raise ValueError(
            "PDF is too large for the built-in lightweight parser. "
            "Install pypdf later for large PDF support."
        )

    text = read_pdf_with_stdlib(path)
    if text.strip():
        return text
    raise ValueError(
        "PDF text extraction failed. Install pypdf later for more reliable PDF support."
    )


def read_pdf_with_pypdf(path: Path, max_chars: int | None = None) -> str:
    from pypdf import PdfReader  # type: ignore[import-not-found]

    reader = PdfReader(str(path))
    return extract_pdf_pages(reader.pages, max_chars=max_chars)


def read_pdf_with_pypdf2(path: Path, max_chars: int | None = None) -> str:
    from PyPDF2 import PdfReader  # type: ignore[import-not-found]

    reader = PdfReader(str(path))
    return extract_pdf_pages(reader.pages, max_chars=max_chars)


def extract_pdf_pages(pages: Any, max_chars: int | None = None) -> str:
    chunks: list[str] = []
    total = 0
    limit = max_chars if max_chars and max_chars > 0 else None

    for page in pages:
        text = page.extract_text() or ""
        chunks.append(text)
        total += len(text)
        if limit is not None and total >= limit:
            break
    return "\n".join(chunks)


def read_pdf_with_stdlib(path: Path) -> str:
    # 轻量 PDF 文本提取器：优先覆盖常见 FlateDecode 文本流。
    # 这不是完整 PDF 解释器，复杂扫描版式或图片型 PDF 需要后续接入 pypdf/OCR。
    data = path.read_bytes()
    chunks: list[str] = []

    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", data, re.DOTALL):
        stream = match.group(1)
        header = data[max(0, match.start() - 400) : match.start()]
        if b"FlateDecode" in header:
            try:
                stream = zlib.decompress(stream)
            except zlib.error:
                continue
        chunks.extend(extract_pdf_strings(stream))

    return "\n".join(chunk for chunk in chunks if chunk.strip())


def extract_pdf_strings(stream: bytes) -> list[str]:
    strings: list[str] = []
    index = 0
    while index < len(stream):
        current = stream[index : index + 1]
        if current == b"(":
            value, index = read_pdf_literal_string(stream, index)
            strings.append(decode_pdf_string(value))
            continue
        if current == b"<" and stream[index : index + 2] != b"<<":
            value, index = read_pdf_hex_string(stream, index)
            if value:
                strings.append(decode_pdf_string(value))
            continue
        index += 1
    return strings


def read_pdf_literal_string(stream: bytes, start: int) -> tuple[bytes, int]:
    value = bytearray()
    depth = 1
    index = start + 1

    while index < len(stream) and depth > 0:
        char = stream[index]
        if char == 92 and index + 1 < len(stream):
            escaped = stream[index + 1]
            value.extend(decode_pdf_escape(escaped))
            index += 2
            continue
        if char == 40:
            depth += 1
        elif char == 41:
            depth -= 1
            if depth == 0:
                index += 1
                break
        value.append(char)
        index += 1

    return bytes(value), index


def read_pdf_hex_string(stream: bytes, start: int) -> tuple[bytes, int]:
    end = stream.find(b">", start + 1)
    if end == -1:
        return b"", len(stream)

    raw = re.sub(rb"\s+", b"", stream[start + 1 : end])
    if len(raw) % 2 == 1:
        raw += b"0"
    try:
        return bytes.fromhex(raw.decode("ascii")), end + 1
    except ValueError:
        return b"", end + 1


def decode_pdf_escape(value: int) -> bytes:
    escapes = {
        ord("n"): b"\n",
        ord("r"): b"\r",
        ord("t"): b"\t",
        ord("b"): b"\b",
        ord("f"): b"\f",
        ord("("): b"(",
        ord(")"): b")",
        ord("\\"): b"\\",
    }
    return escapes.get(value, bytes([value]))


def decode_pdf_string(value: bytes) -> str:
    if value.startswith(b"\xfe\xff"):
        return value[2:].decode("utf-16-be", errors="replace")
    if len(value) > 2 and value[0] == 0:
        return value.decode("utf-16-be", errors="replace")
    for encoding in ("utf-8", "gb18030", "latin-1"):
        try:
            return value.decode(encoding)
        except UnicodeDecodeError:
            continue
    return value.decode("utf-8", errors="replace")


def limit_text(text: str, max_chars: int) -> str:
    max_chars = max(1, min(max_chars, 100_000))
    if len(text) <= max_chars:
        return text
    omitted = len(text) - max_chars
    return f"{text[:max_chars]}\n\n[内容已截断，剩余 {omitted} 个字符未显示。]"


def limit_line(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."
