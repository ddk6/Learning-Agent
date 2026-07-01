from __future__ import annotations

import sys
from pathlib import Path

#这是核心入口
from app.agents.simple_agent import SimpleAgent
from app.config import load_config
from app.plugins import PluginContext, register_default_plugins
from app.storage.sqlite_store import (
    SQLiteAppStore,
    SQLiteMemoryStore,
    SQLiteProposalStore,
    SQLiteSessionState,
)
from app.tools.registry import ToolRegistry
from app.workflows.state_machine import StateMachine


WELCOME = """Agent Runtime Lab 已启动。
输入 /help 查看本地演示命令，输入 /exit 退出。
"""
# 程序入口只负责交互。

#这是构建agent的函数
#主要负责组装agent的各个组件
def build_agent(
    memory_file: Path | None = None,
    proposal_file: Path | None = None,
    database_file: Path | None = None,
    session_id: str = "default-cli",
) -> SimpleAgent:
    # 组装依赖：配置、工具注册器、记忆存储。
    # 这一步相当于最小版 dependency injection，方便后续替换数据库、LLM 或工具实现。
    config = load_config()
    registry = ToolRegistry()
    sqlite_store = SQLiteAppStore(database_file or config.database_file)
    sqlite_store.import_memories_from_json(memory_file or config.memory_file)
    sqlite_store.import_proposals_from_json(proposal_file or config.proposal_file)
    memory_store = SQLiteMemoryStore(sqlite_store)
    session_state = SQLiteSessionState(sqlite_store, session_id=session_id)
    state_machine = StateMachine.from_file(
        config.project_root / "app" / "workflows" / "experiment_proposal_state_machine.json"
    )
    proposal_store = SQLiteProposalStore(sqlite_store, state_machine=state_machine)
    register_default_plugins(registry, PluginContext(config=config, memory_store=memory_store))
    #返回组装好的agent 这里返回的是agent的实例 能直接调用agent里的方法
    return SimpleAgent(
        config=config,
        registry=registry,
        memory_store=memory_store,
        proposal_store=proposal_store,
        session_state=session_state,
        runtime_store=sqlite_store,
    )


#这是程序入口
#主要负责与用户交互
def main() -> None:
    #构建agent
    agent = build_agent()
    #如果命令行的参数大于1，则认为用户输入了命令
    if len(sys.argv) > 1:
        user_input = " ".join(sys.argv[1:]).strip()
        #运行agent
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
