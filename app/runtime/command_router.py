from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


CommandHandler = Callable[[str, str], str]


@dataclass(frozen=True)
class ParsedCommand:
    name: str
    rest: str


class CommandRouter:
    """Routes slash commands to deterministic local handlers.

    Natural-language turns stay in `SimpleAgent`; explicit slash commands are
    parsed here so command wiring can grow without bloating the agent loop.
    """

    def __init__(self, handlers: dict[str, CommandHandler]) -> None:
        self.handlers = handlers

    def route(self, user_input: str, run_id: str) -> str:
        parsed = parse_command(user_input)
        handler = self.handlers.get(parsed.name)
        if handler is None:
            return f"未知命令：{parsed.name}\n输入 /help 查看可用命令。"
        return handler(parsed.rest, run_id)


def parse_command(user_input: str) -> ParsedCommand:
    command, _, rest = user_input.partition(" ")
    return ParsedCommand(name=command.strip(), rest=rest.strip())
