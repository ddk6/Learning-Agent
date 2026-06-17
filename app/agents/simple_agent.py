from __future__ import annotations

import json
from typing import Any

from app.config import AppConfig
from app.core.llm import LLMError, OpenAICompatibleClient
from app.core.prompts import SYSTEM_PROMPT
from app.memory.store import MemoryStore
from app.tools.registry import ToolRegistry


class SimpleAgent:
    def __init__(self, config: AppConfig, registry: ToolRegistry, memory_store: MemoryStore) -> None:
        self.config = config
        self.registry = registry
        self.memory_store = memory_store
        self.llm = OpenAICompatibleClient(config)

    def run(self, user_input: str) -> str:
        # Agent 的第一层分流：显式 / 命令走本地确定性逻辑，普通自然语言才交给 LLM。
        # 这样即使没有 API Key，项目也能保持一个可运行、可测试的最小闭环。
        user_input = user_input.strip()
        if not user_input:
            return "请输入内容，或输入 /help 查看命令。"

        if user_input.startswith("/"):
            return self._run_local_command(user_input)

        if not self.config.has_llm:
            return (
                "当前是本地演示模式，还没有配置大模型。\n"
                "你可以先使用 /help 查看本地命令，或配置 OPENAI_API_KEY 与 OPENAI_MODEL 后再用自然语言对话。"
            )

        return self._run_llm_turn(user_input)

    def _run_local_command(self, user_input: str) -> str:
        # 本地命令是学习阶段的“确定性工具入口”，用于验证工具实现本身是否正确。
        # 未来接入 Web UI 时，这些能力仍可以复用，只是入口不再是 CLI 命令。
        command, _, rest = user_input.partition(" ")
        rest = rest.strip()

        if command == "/help":
            return self._help_text()
        if command == "/notes":
            return self.registry.call("list_notes")
        if command == "/read":
            if not rest:
                return "用法：/read agent.md"
            return self.registry.call("read_note", {"path": rest})
        if command == "/search":
            if not rest:
                return "用法：/search Agent 主循环"
            return self.registry.call("search_notes", {"query": rest})
        if command == "/remember":
            if not rest:
                return "用法：/remember 今天理解了工具调用"
            return self.registry.call("save_memory", {"content": rest, "tag": "learning"})
        if command == "/memory":
            return self.registry.call("list_memory")
        if command == "/experiment":
            if not rest:
                return "用法：/experiment 比较 40/50/60 摄氏度下的反应效率"
            return self.registry.call("plan_experiment_workflow", {"objective": rest})
        if command == "/exit":
            return "bye"

        return f"未知命令：{command}\n输入 /help 查看可用命令。"

    def _run_llm_turn(self, user_input: str) -> str:
        # 最小 Tool Calling 循环：
        # 1. 把用户问题和工具 schema 发给模型；
        # 2. 如果模型返回 tool_calls，就由 Python 执行真实工具；
        # 3. 把工具结果再交回模型，让模型组织最终答案。
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_input},
        ]
        tools = self.registry.tool_schemas()

        try:
            # 限制工具调用轮数，避免模型陷入“反复调用工具但不给最终答案”的循环。
            for _ in range(4):
                assistant_message = self.llm.chat(messages=messages, tools=tools)
                tool_calls = assistant_message.get("tool_calls") or []
                if not tool_calls:
                    return str(assistant_message.get("content") or "").strip() or "模型没有返回内容。"

                messages.append(self._assistant_message_for_history(assistant_message))
                for tool_call in tool_calls:
                    messages.append(self._execute_tool_call(tool_call))

            return "工具调用轮数过多，已停止。请把问题拆小一点再试。"
        except LLMError as exc:
            return f"大模型调用失败：{exc}"
        except Exception as exc:
            return f"Agent 执行失败：{exc}"

    def _assistant_message_for_history(self, message: dict[str, Any]) -> dict[str, Any]:
        # OpenAI tool calling 要求把 assistant 的 tool_calls 原样放回消息历史，
        # 后续 tool 角色消息才能和对应的 tool_call_id 对齐。
        history_message: dict[str, Any] = {
            "role": "assistant",
            "content": message.get("content"),
        }
        if message.get("tool_calls"):
            history_message["tool_calls"] = message["tool_calls"]
        return history_message

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        # 模型只负责“提出要调用哪个工具和参数”，真实执行必须回到受控的 Python 工具注册器。
        # 这也是权限控制边界：模型不能直接访问文件系统，只能调用 registry 暴露的工具。
        function = tool_call.get("function") or {}
        name = str(function.get("name") or "")
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}

        try:
            result = self.registry.call(name, arguments)
        except Exception as exc:
            result = f"工具 {name} 执行失败：{exc}"

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", name),
            "name": name,
            "content": result,
        }

    def _help_text(self) -> str:
        return """本地演示命令：
/notes                         列出 notes/ 下的笔记
/read agent.md                 读取某篇笔记
/search Agent 主循环           搜索笔记内容
/remember 今天理解了工具调用   保存一条学习记忆
/memory                        查看最近学习记忆
/experiment 比较 40/50/60 摄氏度下的反应效率
                               生成实验自动化工作流草案
/exit                          退出 CLI

配置大模型后，也可以直接输入自然语言，例如：
帮我搜索笔记里关于 Agent 主循环的内容，并总结成 3 点。"""
