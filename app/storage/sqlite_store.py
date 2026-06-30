from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.session.state import limit_text
from app.workflows.state_machine import StateMachine


class SQLiteAppStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def add_memory(self, content: str, tag: str = "general") -> dict[str, Any]:
        content = content.strip()
        tag = tag.strip() or "general"
        if not content:
            raise ValueError("Memory content cannot be empty.")

        item = {
            "id": str(uuid4()),
            "content": content,
            "tags": [tag],
            "created_at": now_iso(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO memories (id, content, tags_json, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["content"],
                    json.dumps(item["tags"], ensure_ascii=False),
                    item["created_at"],
                ),
            )
        return item

    def list_memories(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, content, tags_json, created_at
                FROM memories
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._memory_from_row(row) for row in reversed(rows)]

    def memory_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM memories").fetchone()
        return int(row["count"])

    def import_memories_from_json(self, path: Path) -> int:
        if not path.exists() or self.memory_count() > 0:
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        if not isinstance(data, list):
            return 0

        imported = 0
        with self._connect() as conn:
            for item in data:
                normalized = normalize_memory_item(item)
                if normalized is None:
                    continue
                conn.execute(
                    """
                    INSERT OR IGNORE INTO memories (id, content, tags_json, created_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        normalized["id"],
                        normalized["content"],
                        json.dumps(normalized["tags"], ensure_ascii=False),
                        normalized["created_at"],
                    ),
                )
                imported += 1
        return imported

    def ensure_session(self, session_id: str) -> None:
        current = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, created_at, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET updated_at = excluded.updated_at
                """,
                (session_id, current, current),
            )

    def add_message(self, session_id: str, role: str, content: str) -> None:
        self.ensure_session(session_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO messages (id, session_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid4()), session_id, role, content, now_iso()),
            )

    def recent_messages(self, session_id: str, limit: int) -> list[dict[str, str]]:
        limit = max(1, min(limit, 100))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT role, content
                FROM messages
                WHERE session_id = ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {"role": str(row["role"]), "content": str(row["content"])}
            for row in reversed(rows)
        ]

    def last_message(self, session_id: str, role: str) -> str:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT content
                FROM messages
                WHERE session_id = ? AND role = ?
                ORDER BY rowid DESC
                LIMIT 1
                """,
                (session_id, role),
            ).fetchone()
        if row is None:
            return ""
        return str(row["content"])

    def add_tool_result(self, session_id: str, tool_name: str, content: str) -> None:
        self.ensure_session(session_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_results (id, session_id, tool_name, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(uuid4()), session_id, tool_name, limit_text(content, 1000), now_iso()),
            )

    def recent_tool_results(self, session_id: str, limit: int = 6) -> list[dict[str, str]]:
        limit = max(1, min(limit, 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT tool_name, content
                FROM tool_results
                WHERE session_id = ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        return [
            {"name": str(row["tool_name"]), "content": str(row["content"])}
            for row in reversed(rows)
        ]

    def start_agent_run(self, session_id: str, user_input: str) -> str:
        self.ensure_session(session_id)
        run_id = str(uuid4())
        current = now_iso()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_runs (id, session_id, user_input, status, started_at, ended_at, error)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (run_id, session_id, user_input, "running", current, "", ""),
            )
        return run_id

    def finish_agent_run(self, run_id: str, status: str, error: str = "") -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE agent_runs
                SET status = ?, ended_at = ?, error = ?
                WHERE id = ?
                """,
                (status, now_iso(), error, run_id),
            )

    def add_tool_call(
        self,
        run_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        result: str,
        success: bool,
        error: str = "",
        duration_ms: int = 0,
    ) -> dict[str, Any]:
        item = {
            "id": str(uuid4()),
            "run_id": run_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "result": result,
            "success": success,
            "error": error,
            "duration_ms": duration_ms,
            "created_at": now_iso(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tool_calls (
                    id, run_id, tool_name, arguments_json, result_text,
                    success, error, duration_ms, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["run_id"],
                    item["tool_name"],
                    json.dumps(arguments, ensure_ascii=False),
                    result,
                    1 if success else 0,
                    error,
                    duration_ms,
                    item["created_at"],
                ),
            )
        return item

    def recent_agent_runs(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 50))
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    r.id,
                    r.session_id,
                    r.user_input,
                    r.status,
                    r.started_at,
                    r.ended_at,
                    r.error,
                    COUNT(c.id) AS tool_call_count,
                    SUM(CASE WHEN c.success = 0 THEN 1 ELSE 0 END) AS failed_tool_call_count,
                    COALESCE(SUM(c.duration_ms), 0) AS tool_duration_ms
                FROM agent_runs r
                LEFT JOIN tool_calls c ON c.run_id = r.id
                GROUP BY r.id
                ORDER BY r.rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [self._agent_run_from_row(row) for row in rows]

    def save_current_proposal(self, proposal: dict[str, Any], run_id: str = "") -> dict[str, Any]:
        item = dict(proposal)
        item.setdefault("id", str(uuid4()))
        item.setdefault("created_at", now_iso())
        item.setdefault("status", "ready")
        item.setdefault("applied_at", "")
        item.setdefault("apply_count", 0)
        item["updated_at"] = now_iso()
        with self._connect() as conn:
            conn.execute("UPDATE proposals SET is_current = 0 WHERE is_current = 1")
            conn.execute(
                """
                INSERT INTO proposals (
                    id, run_id, status, kind, summary, objective, snapshot_json,
                    created_at, updated_at, applied_at, apply_count, is_current
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(id) DO UPDATE SET
                    run_id = excluded.run_id,
                    status = excluded.status,
                    kind = excluded.kind,
                    summary = excluded.summary,
                    objective = excluded.objective,
                    snapshot_json = excluded.snapshot_json,
                    updated_at = excluded.updated_at,
                    applied_at = excluded.applied_at,
                    apply_count = excluded.apply_count,
                    is_current = 1
                """,
                self._proposal_values(item, run_id),
            )
        return item

    def current_proposal(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT snapshot_json
                FROM proposals
                WHERE is_current = 1
                ORDER BY rowid DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return parse_json_dict(str(row["snapshot_json"]))

    def mark_current_proposal_applied(self, run_id: str = "") -> dict[str, Any]:
        return self.update_current_proposal_status("applied", run_id=run_id, applied=True)

    def update_current_proposal_status(
        self,
        status: str,
        run_id: str = "",
        applied: bool = False,
    ) -> dict[str, Any]:
        proposal = self.current_proposal()
        if proposal is None:
            raise ValueError("No current proposal.")
        proposal = dict(proposal)
        proposal["status"] = status
        if applied and not proposal.get("applied_at"):
            proposal["applied_at"] = now_iso()
            proposal["apply_count"] = int(proposal.get("apply_count") or 0) + 1
        proposal["updated_at"] = now_iso()
        proposal_id = str(proposal["id"])
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE proposals
                SET status = ?, snapshot_json = ?, updated_at = ?, applied_at = ?, apply_count = ?
                WHERE id = ?
                """,
                (
                    proposal["status"],
                    json.dumps(proposal, ensure_ascii=False),
                    proposal["updated_at"],
                    proposal["applied_at"],
                    proposal["apply_count"],
                    proposal_id,
                ),
            )
        return proposal

    def add_proposal_event(
        self,
        proposal_id: str,
        event_type: str,
        event: dict[str, Any] | None = None,
        run_id: str = "",
    ) -> dict[str, Any]:
        item = {
            "id": str(uuid4()),
            "proposal_id": proposal_id,
            "run_id": run_id,
            "event_type": event_type,
            "event": event or {},
            "created_at": now_iso(),
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO proposal_events (id, proposal_id, run_id, event_type, event_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item["id"],
                    item["proposal_id"],
                    item["run_id"],
                    item["event_type"],
                    json.dumps(item["event"], ensure_ascii=False),
                    item["created_at"],
                ),
            )
        return item

    def import_proposals_from_json(self, path: Path) -> int:
        if not path.exists() or self._proposal_count() > 0:
            return 0
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return 0
        if not isinstance(data, dict):
            return 0

        imported = 0
        history = data.get("history")
        if isinstance(history, list):
            for proposal in history:
                if isinstance(proposal, dict):
                    self._insert_legacy_proposal(proposal, is_current=False)
                    imported += 1

        current = data.get("current")
        if isinstance(current, dict):
            self._insert_legacy_proposal(current, is_current=True)
            imported += 1
        return imported

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = DELETE;

                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    tags_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS tool_results (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS agent_runs (
                    id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    error TEXT NOT NULL,
                    FOREIGN KEY (session_id) REFERENCES sessions(id)
                );

                CREATE TABLE IF NOT EXISTS tool_calls (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    tool_name TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    result_text TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES agent_runs(id)
                );

                CREATE TABLE IF NOT EXISTS proposals (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    apply_count INTEGER NOT NULL,
                    is_current INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS proposal_events (
                    id TEXT PRIMARY KEY,
                    proposal_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (proposal_id) REFERENCES proposals(id)
                );

                CREATE INDEX IF NOT EXISTS idx_messages_session_rowid
                    ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_tool_results_session_rowid
                    ON tool_results(session_id);
                CREATE INDEX IF NOT EXISTS idx_agent_runs_session_rowid
                    ON agent_runs(session_id);
                CREATE INDEX IF NOT EXISTS idx_tool_calls_run_id
                    ON tool_calls(run_id);
                CREATE INDEX IF NOT EXISTS idx_proposals_current
                    ON proposals(is_current);
                CREATE INDEX IF NOT EXISTS idx_proposal_events_proposal_id
                    ON proposal_events(proposal_id);
                """
            )

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _memory_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            tags = json.loads(str(row["tags_json"]))
        except json.JSONDecodeError:
            tags = ["general"]
        if not isinstance(tags, list):
            tags = ["general"]
        return {
            "id": str(row["id"]),
            "content": str(row["content"]),
            "tags": [str(tag) for tag in tags if str(tag).strip()] or ["general"],
            "created_at": str(row["created_at"]),
        }

    def _agent_run_from_row(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": str(row["id"]),
            "session_id": str(row["session_id"]),
            "user_input": str(row["user_input"]),
            "status": str(row["status"]),
            "started_at": str(row["started_at"]),
            "ended_at": str(row["ended_at"]),
            "error": str(row["error"]),
            "tool_call_count": int(row["tool_call_count"] or 0),
            "failed_tool_call_count": int(row["failed_tool_call_count"] or 0),
            "tool_duration_ms": int(row["tool_duration_ms"] or 0),
        }

    def _proposal_values(self, item: dict[str, Any], run_id: str) -> tuple[Any, ...]:
        return (
            str(item["id"]),
            run_id,
            str(item.get("status") or ""),
            str(item.get("kind") or ""),
            str(item.get("summary") or ""),
            str(item.get("objective") or ""),
            json.dumps(item, ensure_ascii=False),
            str(item.get("created_at") or now_iso()),
            str(item.get("updated_at") or now_iso()),
            str(item.get("applied_at") or ""),
            int(item.get("apply_count") or 0),
        )

    def _proposal_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM proposals").fetchone()
        return int(row["count"])

    def _insert_legacy_proposal(self, proposal: dict[str, Any], is_current: bool) -> None:
        item = dict(proposal)
        item.setdefault("id", str(uuid4()))
        item.setdefault("created_at", now_iso())
        item.setdefault("updated_at", now_iso())
        item.setdefault("applied_at", "")
        item.setdefault("apply_count", 0)
        with self._connect() as conn:
            if is_current:
                conn.execute("UPDATE proposals SET is_current = 0 WHERE is_current = 1")
            conn.execute(
                """
                INSERT OR IGNORE INTO proposals (
                    id, run_id, status, kind, summary, objective, snapshot_json,
                    created_at, updated_at, applied_at, apply_count, is_current
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (*self._proposal_values(item, ""), 1 if is_current else 0),
            )
        self.add_proposal_event(str(item["id"]), "imported", {"source": "json"})


class SQLiteMemoryStore:
    def __init__(self, store: SQLiteAppStore) -> None:
        self.store = store

    def add(self, content: str, tag: str = "general") -> dict[str, Any]:
        return self.store.add_memory(content=content, tag=tag)

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.list_memories(limit=limit)


class SQLiteSessionState:
    def __init__(
        self,
        store: SQLiteAppStore,
        session_id: str = "default-cli",
        max_messages: int = 12,
    ) -> None:
        self.store = store
        self.session_id = session_id
        self.max_messages = max_messages
        self.store.ensure_session(session_id)

    @property
    def last_user_input(self) -> str:
        return self.store.last_message(self.session_id, "user")

    @property
    def last_answer(self) -> str:
        return self.store.last_message(self.session_id, "assistant")

    def recent_messages(self) -> list[dict[str, Any]]:
        return self.store.recent_messages(self.session_id, self.max_messages)

    def record_turn(self, user_input: str, answer: str) -> None:
        user_input = user_input.strip()
        answer = answer.strip()
        if not user_input or not answer:
            return
        self.store.add_message(self.session_id, "user", user_input)
        self.store.add_message(self.session_id, "assistant", answer)

    def record_tool_result(self, name: str, content: str) -> None:
        self.store.add_tool_result(self.session_id, name, content.strip())

    def summary(self) -> str:
        messages = self.recent_messages()
        if not messages:
            return "当前会话还没有可展示的短期上下文。"

        last_answer = self.last_answer
        lines = [
            "# 当前会话短期上下文",
            "",
            f"- Session ID：{self.session_id}",
            f"- 已加载最近消息数：{len(messages)}",
            f"- 上一轮用户输入：{self.last_user_input or '无'}",
            f"- 上一轮回答长度：{len(last_answer)} 字符",
        ]

        tool_results = self.store.recent_tool_results(self.session_id)
        if tool_results:
            lines.append("- 最近工具结果：")
            for record in tool_results:
                lines.append(f"  - {record['name']}: {record['content']}")
        else:
            lines.append("- 最近工具结果：无")

        lines.append("")
        lines.append("## 最近消息")
        for message in messages[-6:]:
            role = message.get("role", "unknown")
            content = limit_text(str(message.get("content", "")), 180)
            lines.append(f"- {role}: {content}")
        return "\n".join(lines)


class SQLiteProposalStore:
    def __init__(self, store: SQLiteAppStore, state_machine: StateMachine | None = None) -> None:
        self.store = store
        self.state_machine = state_machine
        self.current_run_id = ""

    def set_current_run(self, run_id: str) -> None:
        self.current_run_id = run_id

    def save_current(self, proposal: dict[str, Any]) -> dict[str, Any]:
        item = self.store.save_current_proposal(proposal, run_id=self.current_run_id)
        self.store.add_proposal_event(
            str(item["id"]),
            "created",
            {
                "from_state": "",
                "event_type": "created",
                "to_state": str(item.get("status") or ""),
            },
            run_id=self.current_run_id,
        )
        return item

    def current(self) -> dict[str, Any] | None:
        return self.store.current_proposal()

    def mark_applied(self) -> dict[str, Any]:
        return self.transition("applied", applied=True)

    def record_event(self, event_type: str, event: dict[str, Any] | None = None) -> None:
        self.transition(event_type, event=event or {})

    def transition(
        self,
        event_type: str,
        event: dict[str, Any] | None = None,
        applied: bool = False,
    ) -> dict[str, Any]:
        proposal = self.current()
        if proposal is None:
            raise ValueError("No current proposal.")
        from_state = str(proposal.get("status") or "")
        if self.state_machine:
            transition = self.state_machine.transition(from_state, event_type)
            to_state = transition.to_state
        else:
            to_state = from_state

        updated = proposal
        if to_state != from_state or applied:
            updated = self.store.update_current_proposal_status(
                to_state,
                run_id=self.current_run_id,
                applied=applied,
            )

        event_payload = dict(event or {})
        event_payload.update(
            {
                "from_state": from_state,
                "event_type": event_type,
                "to_state": to_state,
            }
        )
        self.store.add_proposal_event(
            str(proposal.get("id") or ""),
            event_type,
            event_payload,
            run_id=self.current_run_id,
        )
        return updated


def measure_ms(start: float) -> int:
    return max(0, int((time.perf_counter() - start) * 1000))


def normalize_memory_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    content = str(item.get("content", "")).strip()
    if not content:
        return None

    raw_tags = item.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    else:
        tags = [str(item.get("tag", "general")).strip() or "general"]

    return {
        "id": str(item.get("id") or uuid4()),
        "content": content,
        "tags": tags or ["general"],
        "created_at": str(item.get("created_at") or now_iso()),
    }


def parse_json_dict(raw: str) -> dict[str, Any] | None:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if isinstance(data, dict):
        return data
    return None


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
