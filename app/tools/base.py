from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class Tool:
    # Tool 是 Agent 能力的最小封装：
    # name/description/parameters 给模型看，handler 给 Python Runtime 执行。
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def run(self, arguments: dict[str, Any] | None = None) -> str:
        return self.handler(arguments or {})

    def to_openai_tool(self) -> dict[str, Any]:
        # 转成 OpenAI 兼容的 function tool schema，让 LLM 能“看懂”有哪些工具可用。
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }
