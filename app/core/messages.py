from __future__ import annotations

from typing import Any, TypedDict


class ChatMessage(TypedDict, total=False):
    role: str
    content: str | None
    name: str
    tool_call_id: str
    tool_calls: list[dict[str, Any]]
