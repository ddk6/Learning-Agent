from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class MemoryStore:
    def __init__(self, path: Path) -> None:
        # 当前阶段用 JSON 文件做最小长期记忆，便于学习和调试。
        # 后续可以平滑迁移到 SQLite/PostgreSQL/向量数据库。
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def add(self, content: str, tag: str = "general") -> dict[str, Any]:
        # 这里给每条记忆补充 id、tags、created_at，形成可迁移的数据结构。
        content = content.strip()
        tag = tag.strip() or "general"
        if not content:
            raise ValueError("Memory content cannot be empty.")

        memories = self._read_all()
        item = {
            "id": str(uuid4()),
            "content": content,
            "tags": [tag],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        memories.append(item)
        self._write_all(memories)
        return item

    def list(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 100))
        return self._read_all()[-limit:]

    def _read_all(self) -> list[dict[str, Any]]:
        # 读取失败时返回空列表，保证本地记忆文件损坏不会导致整个 Agent 无法启动。
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []
        if not isinstance(data, list):
            return []
        memories: list[dict[str, Any]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            normalized = self._normalize_item(item)
            if normalized is not None:
                memories.append(normalized)
        return memories

    def _write_all(self, memories: list[dict[str, Any]]) -> None:
        self.path.write_text(
            json.dumps(memories, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        # 兼容早期 schema：旧数据可能是 tag 字符串，也可能是 tags 列表。
        content = str(item.get("content", "")).strip()
        if not content:
            return None

        raw_tags = item.get("tags")
        if isinstance(raw_tags, list):
            tags = [str(tag).strip() for tag in raw_tags if str(tag).strip()]
        else:
            tag = str(item.get("tag", "general")).strip() or "general"
            tags = [tag]

        return {
            "id": str(item.get("id") or uuid4()),
            "content": content,
            "tags": tags or ["general"],
            "created_at": str(
                item.get("created_at") or datetime.now(timezone.utc).isoformat()
            ),
        }
