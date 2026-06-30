from __future__ import annotations

from typing import Any

from app.tools.base import Tool


class ToolPolicyError(PermissionError):
    pass


class ToolRegistry:
    def __init__(self) -> None:
        # 注册器是 Agent 和工具之间的边界层。
        # Agent 只通过工具名调用能力，不直接依赖具体工具文件的内部实现。
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._tools)) or "none"
            raise ValueError(f"Unknown tool: {name}. Available tools: {available}") from exc

    def call(
        self,
        name: str,
        arguments: dict[str, Any] | None = None,
        *,
        confirmed: bool = False,
        caller: str = "unknown",
    ) -> str:
        # 所有工具调用都收敛到这里，方便以后统一加权限检查、日志、重试和耗时统计。
        tool = self.get(name)
        self._enforce_policy(tool, confirmed=confirmed, caller=caller)
        return tool.run(arguments or {})

    def policy_decision(
        self,
        name: str,
        *,
        confirmed: bool = False,
        caller: str = "unknown",
    ) -> str:
        tool = self.get(name)
        if tool.permission.requires_confirmation and not confirmed:
            return (
                "blocked: confirmation_required; "
                f"caller={caller}; risk={tool.permission.risk_level}"
            )
        return (
            "allowed; "
            f"caller={caller}; risk={tool.permission.risk_level}; "
            f"confirmed={'yes' if confirmed else 'no'}"
        )

    def _enforce_policy(self, tool: Tool, *, confirmed: bool, caller: str) -> None:
        if tool.permission.requires_confirmation and not confirmed:
            raise ToolPolicyError(
                f"Tool {tool.name} requires explicit user confirmation before execution "
                f"(caller={caller}, risk={tool.permission.risk_level})."
            )

    def tool_schemas(self) -> list[dict[str, Any]]:
        return [tool.to_openai_tool() for tool in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def summaries(self) -> list[tuple[str, str]]:
        return [
            (name, tool.description)
            for name, tool in sorted(self._tools.items())
        ]

    def permission_summaries(self) -> list[tuple[str, str, str]]:
        return [
            (name, tool.description, tool.permission_summary())
            for name, tool in sorted(self._tools.items())
        ]
