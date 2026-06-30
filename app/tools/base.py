from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


ToolHandler = Callable[[dict[str, Any]], str]


@dataclass(frozen=True)
class ToolPermission:
    # 权限元数据只描述本项目工具的边界，不授予额外能力。
    read_scope: tuple[str, ...] = ()
    write_scope: tuple[str, ...] = ()
    risk_level: str = "low"
    requires_confirmation: bool = False
    audit: bool = True

    def summary(self) -> str:
        read_scope = ", ".join(self.read_scope) if self.read_scope else "none"
        write_scope = ", ".join(self.write_scope) if self.write_scope else "none"
        confirmation = "yes" if self.requires_confirmation else "no"
        return (
            f"risk={self.risk_level}; read={read_scope}; "
            f"write={write_scope}; confirmation={confirmation}"
        )


@dataclass(frozen=True)
class Tool:
    # Tool 是 Agent 能力的最小封装：
    # name/description/parameters 给模型看，handler 给 Python Runtime 执行。
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler
    permission: ToolPermission = field(default_factory=ToolPermission)

    def run(self, arguments: dict[str, Any] | None = None) -> str:
        normalized = arguments or {}
        self._validate_arguments(normalized)
        return self.handler(normalized)

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

    def permission_summary(self) -> str:
        return self.permission.summary()

    def _validate_arguments(self, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ValueError(f"Tool arguments must be an object: {self.name}")

        properties = self.parameters.get("properties") or {}
        if not isinstance(properties, dict):
            properties = {}

        if self.parameters.get("additionalProperties") is False:
            unknown = sorted(set(arguments) - set(properties))
            if unknown:
                raise ValueError(
                    f"Unknown argument(s) for {self.name}: {', '.join(unknown)}"
                )

        required = self.parameters.get("required") or []
        for key in required:
            if key not in arguments:
                raise ValueError(f"Missing required argument for {self.name}: {key}")

        for key, value in arguments.items():
            schema = properties.get(key)
            if isinstance(schema, dict):
                validate_value(self.name, key, value, schema)


def validate_value(tool_name: str, key: str, value: Any, schema: dict[str, Any]) -> None:
    expected_type = schema.get("type")
    if expected_type == "string" and not isinstance(value, str):
        raise ValueError(f"Argument {key} for {tool_name} must be a string.")
    if expected_type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"Argument {key} for {tool_name} must be an integer.")
        minimum = schema.get("minimum")
        maximum = schema.get("maximum")
        if isinstance(minimum, int | float) and value < minimum:
            raise ValueError(f"Argument {key} for {tool_name} must be >= {minimum}.")
        if isinstance(maximum, int | float) and value > maximum:
            raise ValueError(f"Argument {key} for {tool_name} must be <= {maximum}.")
    if expected_type == "boolean" and not isinstance(value, bool):
        raise ValueError(f"Argument {key} for {tool_name} must be a boolean.")
    if expected_type == "array":
        if not isinstance(value, list):
            raise ValueError(f"Argument {key} for {tool_name} must be an array.")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                validate_value(tool_name, f"{key}[{index}]", item, item_schema)
