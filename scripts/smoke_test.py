from __future__ import annotations

import json
import sqlite3
import sys
import gc
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.main import build_agent  # noqa: E402
from app.tools.experiment_tools import register_experiment_tools  # noqa: E402
from app.tools.note_tools import register_note_tools  # noqa: E402
from app.tools.memory_tools import register_memory_tools  # noqa: E402
from app.tools.registry import ToolPolicyError, ToolRegistry  # noqa: E402
from app.storage.sqlite_store import SQLiteAppStore, SQLiteMemoryStore  # noqa: E402
from app.workflows.state_machine import StateMachine, StateMachineError  # noqa: E402


def assert_contains(text: str, expected: str) -> None:
    if expected not in text:
        raise AssertionError(f"Expected {expected!r} in output:\n{text}")


def assert_table_count_at_least(database_file: Path, table: str, minimum: int) -> None:
    with sqlite3.connect(database_file) as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    count = int(row[0])
    if count < minimum:
        raise AssertionError(f"Expected {table} to contain at least {minimum} rows, got {count}.")


def table_count(database_file: Path, table: str) -> int:
    with sqlite3.connect(database_file) as conn:
        row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0])


def assert_event_exists(database_file: Path, event_type: str) -> None:
    with sqlite3.connect(database_file) as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM proposal_events WHERE event_type = ?",
            (event_type,),
        ).fetchone()
    if int(row[0]) < 1:
        raise AssertionError(f"Expected proposal event {event_type!r} to exist.")


def assert_event_transition(database_file: Path, event_type: str, from_state: str, to_state: str) -> None:
    with sqlite3.connect(database_file) as conn:
        rows = conn.execute(
            "SELECT event_json FROM proposal_events WHERE event_type = ?",
            (event_type,),
        ).fetchall()
    for (raw_event,) in rows:
        event = json.loads(raw_event)
        if event.get("from_state") == from_state and event.get("to_state") == to_state:
            return
    raise AssertionError(
        f"Expected proposal event {event_type!r} transition {from_state!r}->{to_state!r}."
    )


def assert_tool_call_audit(database_file: Path, tool_name: str, expected: str) -> None:
    with sqlite3.connect(database_file) as conn:
        rows = conn.execute(
            "SELECT arguments_json FROM tool_calls WHERE tool_name = ? ORDER BY rowid DESC",
            (tool_name,),
        ).fetchall()
    for (raw_arguments,) in rows:
        if expected in raw_arguments:
            return
    raise AssertionError(f"Expected audit marker {expected!r} for tool {tool_name!r}.")


def assert_raises_contains(action: callable, expected: str) -> None:
    try:
        action()
    except Exception as exc:
        if expected not in str(exc):
            raise AssertionError(f"Expected error containing {expected!r}, got {exc!r}.") from exc
        return
    raise AssertionError(f"Expected error containing {expected!r}.")


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
        temp_path = Path(temp_dir)
        database_file = temp_path / "learning_agent.db"
        proposal_file = temp_path / "proposals.json"
        agent = build_agent(
            database_file=database_file,
            proposal_file=proposal_file,
            session_id="smoke-test",
        )

        assert_contains(agent.run("/help"), "/notes")
        tool_list = agent.run("/tools")
        assert_contains(tool_list, "当前本项目注册了 6 个工具")
        assert_contains(tool_list, "plan_experiment_workflow")
        assert_contains(tool_list, "权限边界")
        assert_contains(tool_list, "confirmation=yes")
        if "multi_tool_use.parallel" in tool_list:
            raise AssertionError(f"Unexpected outer tool in local inventory:\n{tool_list}")
        natural_tool_list = agent.run("当前有几个工具可以调用？")
        assert_contains(natural_tool_list, "当前本项目注册了 6 个工具")
        assert_contains(agent.run("/notes"), "agent.md")
        assert_contains(agent.run("/read agent.md"), "最小 Agent 主循环")
        assert_contains(agent.run("/session"), "上一轮用户输入：/read agent.md")
        assert_contains(agent.run("/save-last"), "已保存上一轮回答到长期记忆")
        assert_contains(agent.run("/memory"), "最小 Agent 主循环")
        restarted_agent = build_agent(
            database_file=database_file,
            proposal_file=proposal_file,
            session_id="smoke-test",
        )
        assert_contains(restarted_agent.run("/session"), "/read agent.md")
        assert_contains(restarted_agent.run("/memory"), "最小 Agent 主循环")
        assert_contains(agent.run("/search Agent 主循环"), "agent.md")
        assert_contains(agent.run("/remember smoke test memory"), "smoke test memory")
        assert_contains(agent.run("/memory"), "smoke test memory")
        before_false_positive = table_count(database_file, "memories")
        false_positive_result = agent.run("这些笔记都是我不断优化的历史记录")
        if "已保存上一轮回答到长期记忆" in false_positive_result:
            raise AssertionError("Descriptive history-record text should not trigger save-last.")
        after_false_positive = table_count(database_file, "memories")
        if after_false_positive != before_false_positive:
            raise AssertionError("False positive save-last request wrote a memory row.")
        before_question = table_count(database_file, "memories")
        question_result = agent.run("你刚才保存了我前面的对话？")
        if "已保存上一轮回答到长期记忆" in question_result:
            raise AssertionError("Question about previous saves should not trigger save-last.")
        after_question = table_count(database_file, "memories")
        if after_question != before_question:
            raise AssertionError("Question about previous saves wrote a memory row.")
        need_info = agent.run("/experiment 帮我做实验")
        assert_contains(need_info, "Proposal 状态：need_info")
        assert_contains(need_info, "需要补充")
        experiment_proposal = agent.run("/experiment 比较 40/50/60 摄氏度下的反应效率")
        assert_contains(experiment_proposal, "Proposal 状态：ready")
        assert_contains(experiment_proposal, "/apply-proposal")
        assert_contains(agent.run("保存刚才的内容"), "已保存上一轮回答到长期记忆")
        assert_contains(agent.run("/memory"), "Proposal 状态：ready")
        proposal_detail = agent.run("/proposal-detail")
        assert_contains(proposal_detail, "实验工作流草案")
        assert_contains(proposal_detail, "温度梯度: 40 C, 50 C, 60 C")
        assert_contains(proposal_detail, "应用计划")
        apply_result = agent.run("/apply-proposal")
        assert_contains(apply_result, "Proposal 已应用到本地记录")
        assert_contains(agent.run("/apply-proposal"), "已应用过")
        assert_contains(agent.run("/diagnose 端口连接超时"), "诊断建议")
        assert_contains(agent.run("/memory"), "已应用实验工作流 Proposal")
        runs = agent.run("/runs")
        assert_contains(runs, "最近 Agent Run 日志")
        assert_contains(runs, "tools=")
        trace = agent.run("/runs --detail")
        assert_contains(trace, "Agent Trace")
        assert_contains(trace, "Run ID")
        assert_contains(agent.run("/trace latest"), "Agent Trace")
        assert_table_count_at_least(database_file, "agent_runs", 1)
        assert_table_count_at_least(database_file, "tool_calls", 1)
        assert_tool_call_audit(database_file, "plan_experiment_workflow", "proposal_flow")
        assert_tool_call_audit(database_file, "read_note", "local_command")
        assert_table_count_at_least(database_file, "proposals", 1)
        assert_table_count_at_least(database_file, "proposal_events", 1)
        assert_event_exists(database_file, "created")
        assert_event_exists(database_file, "viewed")
        assert_event_exists(database_file, "applied")
        assert_event_exists(database_file, "diagnosed")
        assert_event_transition(database_file, "viewed", "ready", "ready")
        assert_event_transition(database_file, "applied", "ready", "applied")
        assert_event_transition(database_file, "diagnosed", "applied", "diagnosed")
        del restarted_agent
        del agent
        gc.collect()

    test_note_file_types()
    test_tool_permission_boundaries()
    test_experiment_tool()
    test_state_machine_config()
    test_architecture_note_exists()

    print("Smoke test passed.")


def test_experiment_tool() -> None:
    registry = ToolRegistry()
    register_experiment_tools(registry)

    result = registry.call(
        "plan_experiment_workflow",
        {
            "objective": "比较 40/50/60 摄氏度下的反应效率",
            "constraints": ["只生成计划，不控制真实设备"],
        },
        confirmed=True,
        caller="test",
    )
    assert_contains(result, "Pilot")
    assert_contains(result, "40 C, 50 C, 60 C")
    assert_contains(result, "只生成计划，不控制真实设备")


def test_tool_permission_boundaries() -> None:
    with TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        notes_dir = temp_path / "notes"
        notes_dir.mkdir()
        (notes_dir / "sample.md").write_text("Agent note", encoding="utf-8")

        registry = ToolRegistry()
        register_note_tools(registry, notes_dir)
        register_experiment_tools(registry)
        sqlite_store = SQLiteAppStore(temp_path / "learning_agent.db")
        register_memory_tools(registry, SQLiteMemoryStore(sqlite_store))

        assert_raises_contains(
            lambda: registry.call("read_note", {"path": "../outside.md"}),
            "notes directory",
        )
        assert_raises_contains(
            lambda: registry.call("read_note", {"path": "sample.md", "unexpected": True}),
            "Unknown argument",
        )
        assert_raises_contains(
            lambda: registry.call("list_memory", {"limit": 101}),
            "<= 100",
        )
        assert_raises_contains(
            lambda: registry.call("missing_tool", {}),
            "Unknown tool",
        )
        assert_raises_contains(
            lambda: registry.call(
                "plan_experiment_workflow",
                {"objective": "比较 40/50/60 摄氏度下的反应效率"},
                caller="llm_tool_call",
            ),
            "requires explicit user confirmation",
        )
        try:
            registry.call(
                "plan_experiment_workflow",
                {"objective": "比较 40/50/60 摄氏度下的反应效率"},
                confirmed=False,
                caller="llm_tool_call",
            )
        except ToolPolicyError:
            pass
        else:
            raise AssertionError("Expected ToolPolicyError for unconfirmed risky tool.")
        assert_contains(
            registry.call(
                "plan_experiment_workflow",
                {"objective": "比较 40/50/60 摄氏度下的反应效率"},
                confirmed=True,
                caller="local_command",
            ),
            "实验工作流草案",
        )


def test_state_machine_config() -> None:
    state_machine = StateMachine.from_file(
        PROJECT_ROOT / "app" / "workflows" / "experiment_proposal_state_machine.json"
    )
    transition = state_machine.transition("ready", "applied")
    if transition.to_state != "applied":
        raise AssertionError(f"Unexpected transition target: {transition}")
    try:
        state_machine.transition("applied", "applied")
    except StateMachineError:
        return
    raise AssertionError("Expected repeated applied event from applied state to be rejected.")


def test_architecture_note_exists() -> None:
    note = PROJECT_ROOT / "notes" / "architecture-and-adr.md"
    if not note.exists():
        raise AssertionError("Expected notes/architecture-and-adr.md to exist.")
    text = note.read_text(encoding="utf-8")
    assert_contains(text, "会话记忆")
    assert_contains(text, "长期记忆")
    assert_contains(text, "工具权限边界")
    assert_contains(text, "ADR")


if __name__ == "__main__":
    main()
