from __future__ import annotations

from app.memory.store import MemoryStore
from app.tools.base import Tool, ToolPermission
from app.tools.registry import ToolRegistry


def register_memory_tools(registry: ToolRegistry, memory_store: MemoryStore) -> None:
    def save_memory(arguments: dict) -> str:
        # 记忆工具只保存明确传入的 content，不让模型直接写任意文件。
        content = str(arguments.get("content", "")).strip()
        tag = str(arguments.get("tag", "general")).strip() or "general"
        item = memory_store.add(content=content, tag=tag)
        tags = ", ".join(item.get("tags") or ["general"])
        return f"已保存记忆 #{item['id']} [{tags}]: {item['content']}"

    def list_memory(arguments: dict) -> str:
        # limit 做边界控制，避免一次把长期记忆全部塞回上下文。
        raw_limit = arguments.get("limit", 20)
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            limit = 20

        memories = memory_store.list(limit=limit)
        if not memories:
            return "还没有保存学习记忆。"
        return "\n".join(
            f"#{item.get('id')} [{', '.join(item.get('tags') or ['general'])}] {item.get('content', '')}"
            for item in memories
        )

    registry.register(
        Tool(
            name="save_memory",
            description="保存一条长期学习记忆，用于记录项目进展、学习心得或待办。",
            parameters={
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "要保存的记忆内容。",
                    },
                    "tag": {
                        "type": "string",
                        "description": "用于分类的标签，例如 llm、agent、rag。",
                    },
                },
                "required": ["content"],
                "additionalProperties": False,
            },
            handler=save_memory,
            permission=ToolPermission(
                write_scope=("memories",),
                risk_level="medium",
                requires_confirmation=False,
            ),
        )
    )
    registry.register(
        Tool(
            name="list_memory",
            description="查看最近保存的学习记忆。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "最多返回多少条记忆。",
                        "minimum": 1,
                        "maximum": 100,
                    }
                },
                "additionalProperties": False,
            },
            handler=list_memory,
            permission=ToolPermission(read_scope=("memories",), risk_level="low"),
        )
    )
