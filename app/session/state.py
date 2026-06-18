from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolResultRecord:
    name: str
    content: str


@dataclass
class SessionState:
    max_messages: int = 12
    messages: list[dict[str, str]] = field(default_factory=list)
    last_user_input: str = ""
    last_answer: str = ""
    last_tool_results: list[ToolResultRecord] = field(default_factory=list)

    def recent_messages(self) -> list[dict[str, Any]]:
        return [dict(message) for message in self.messages[-self.max_messages :]]

    def record_turn(self, user_input: str, answer: str) -> None:
        user_input = user_input.strip()
        answer = answer.strip()
        if not user_input or not answer:
            return

        self.messages.append({"role": "user", "content": user_input})
        self.messages.append({"role": "assistant", "content": answer})
        self.messages = self.messages[-self.max_messages :]
        self.last_user_input = user_input
        self.last_answer = answer

    def record_tool_result(self, name: str, content: str) -> None:
        self.last_tool_results.append(
            ToolResultRecord(
                name=name,
                content=limit_text(content.strip(), 500),
            )
        )
        self.last_tool_results = self.last_tool_results[-6:]

    def summary(self) -> str:
        if not self.messages:
            return "当前会话还没有可展示的短期上下文。"

        lines = [
            "# 当前会话短期上下文",
            "",
            f"- 已记录消息数：{len(self.messages)}",
            f"- 上一轮用户输入：{self.last_user_input or '无'}",
            f"- 上一轮回答长度：{len(self.last_answer)} 字符",
        ]

        if self.last_tool_results:
            lines.append("- 最近工具结果：")
            for record in self.last_tool_results:
                lines.append(f"  - {record.name}: {record.content}")
        else:
            lines.append("- 最近工具结果：无")

        lines.append("")
        lines.append("## 最近消息")
        for message in self.messages[-6:]:
            role = message.get("role", "unknown")
            content = limit_text(message.get("content", ""), 180)
            lines.append(f"- {role}: {content}")
        return "\n".join(lines)


def limit_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars]}..."
