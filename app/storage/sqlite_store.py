from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.session.state import limit_text


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

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                PRAGMA journal_mode = WAL;

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

                CREATE INDEX IF NOT EXISTS idx_messages_session_rowid
                    ON messages(session_id);
                CREATE INDEX IF NOT EXISTS idx_tool_results_session_rowid
                    ON tool_results(session_id);
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


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
