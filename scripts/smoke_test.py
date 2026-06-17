from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.main import build_agent  # noqa: E402
from app.tools.note_tools import register_note_tools  # noqa: E402
from app.tools.registry import ToolRegistry  # noqa: E402


def assert_contains(text: str, expected: str) -> None:
    if expected not in text:
        raise AssertionError(f"Expected {expected!r} in output:\n{text}")


def write_docx(path: Path, text: str) -> None:
    document_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", document_xml)


def write_pdf(path: Path, text: str) -> None:
    escaped_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 12 Tf 72 720 Td ({escaped_text}) Tj ET".encode("utf-8")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>"
        ),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        (
            b"<< /Length "
            + str(len(stream)).encode("ascii")
            + b" >>\nstream\n"
            + stream
            + b"\nendstream"
        ),
    ]

    body = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(body))
        body.extend(f"{index} 0 obj\n".encode("ascii"))
        body.extend(obj)
        body.extend(b"\nendobj\n")

    xref_offset = len(body)
    body.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    body.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        body.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    body.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    path.write_bytes(bytes(body))


def test_note_file_types() -> None:
    with TemporaryDirectory() as temp_dir:
        notes_dir = Path(temp_dir) / "notes"
        notes_dir.mkdir()
        (notes_dir / "sample.txt").write_text(
            "TXT learning note about Agent tools.",
            encoding="utf-8",
        )
        write_docx(notes_dir / "sample.docx", "DOCX learning note about memory.")
        write_pdf(notes_dir / "sample.pdf", "PDF learning note about RAG.")

        registry = ToolRegistry()
        register_note_tools(registry, notes_dir)

        assert_contains(registry.call("list_notes"), "sample.txt")
        assert_contains(registry.call("list_notes"), "sample.docx")
        assert_contains(registry.call("list_notes"), "sample.pdf")
        assert_contains(
            registry.call("read_note", {"path": "sample.txt"}),
            "TXT learning note",
        )
        assert_contains(
            registry.call("read_note", {"path": "sample.docx"}),
            "DOCX learning note",
        )
        assert_contains(
            registry.call("read_note", {"path": "sample.pdf"}),
            "PDF learning note",
        )
        assert_contains(
            registry.call("search_notes", {"query": "memory"}),
            "sample.docx",
        )


def main() -> None:
    with TemporaryDirectory() as temp_dir:
        agent = build_agent(memory_file=Path(temp_dir) / "memory.json")

        assert_contains(agent.run("/help"), "/notes")
        assert_contains(agent.run("/notes"), "agent.md")
        assert_contains(agent.run("/read agent.md"), "最小 Agent 主循环")
        assert_contains(agent.run("/search Agent 主循环"), "agent.md")
        assert_contains(agent.run("/remember smoke test memory"), "smoke test memory")
        assert_contains(agent.run("/memory"), "smoke test memory")

    test_note_file_types()

    print("Smoke test passed.")


if __name__ == "__main__":
    main()
