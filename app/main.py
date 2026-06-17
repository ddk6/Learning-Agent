from __future__ import annotations

import sys
from pathlib import Path

from app.agents.simple_agent import SimpleAgent
from app.config import load_config
from app.memory.store import MemoryStore
from app.tools.memory_tools import register_memory_tools
from app.tools.note_tools import register_note_tools
from app.tools.registry import ToolRegistry


WELCOME = """Learning Agent 已启动。
输入 /help 查看本地演示命令，输入 /exit 退出。
"""
# 程序入口只负责交互。


def build_agent(memory_file: Path | None = None) -> SimpleAgent:
    # 组装依赖：配置、工具注册器、记忆存储。
    # 这一步相当于最小版 dependency injection，方便后续替换数据库、LLM 或工具实现。
    config = load_config()
    registry = ToolRegistry()
    memory_store = MemoryStore(memory_file or config.memory_file)
    register_memory_tools(registry, memory_store)
    register_note_tools(registry, config.notes_dir)
    return SimpleAgent(config=config, registry=registry, memory_store=memory_store)


def main() -> None:
    agent = build_agent()

    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:]).strip()
        if user_input:
            print(agent.run(user_input))
        return

    print(WELCOME)
    while True:
        try:
            user_input = input("你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n已退出。")
            return

        if not user_input:
            continue
        if user_input.lower() in {"/exit", "exit", "quit", "q"}:
            print("已退出。")
            return

        print(f"\nAgent> {agent.run(user_input)}\n")


if __name__ == "__main__":
    main()
