from __future__ import annotations

import json
import re
from typing import Any

#agent主循环
from app.config import AppConfig
from app.core.llm import LLMError, OpenAICompatibleClient
from app.core.prompts import SYSTEM_PROMPT
from app.proposals.experiment import (
    create_experiment_proposal,
    diagnose_experiment_issue,
    render_proposal_card,
    render_proposal_detail,
)
from app.runtime.approval import ToolExecutionRequest
from app.runtime.command_router import CommandRouter
from app.runtime.tool_executor import ToolExecutor
from app.runtime.trace import render_recent_runs, render_run_trace
from app.session.state import SessionState
from app.tools.registry import ToolRegistry
from app.workflows.state_machine import StateMachineError

#
class SimpleAgent:
    def __init__(
        self,
        config: AppConfig,
        registry: ToolRegistry,
        memory_store: Any,
        proposal_store: Any,
        session_state: Any | None = None,
        runtime_store: Any | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.memory_store = memory_store
        self.proposal_store = proposal_store
        self.session = session_state or SessionState()
        self.runtime_store = runtime_store
        self.llm = OpenAICompatibleClient(config)
        self.tool_executor = ToolExecutor(registry, self.session, runtime_store)
        self.command_router = self._build_command_router()

    def run(self, user_input: str) -> str:
        # Agent 的第一层分流：显式 / 命令走本地确定性逻辑，普通自然语言才交给 LLM。
        # 这样即使没有 API Key，项目也能保持一个可运行、可测试的最小闭环。
        user_input = user_input.strip().lstrip("\ufeff")
        if not user_input:
            return "请输入内容，或输入 /help 查看命令。"

        run_id = self._start_run(user_input)
        try:
            response = self._handle_user_input(user_input, run_id)
            self._finish_run(run_id, "completed")
            return response
        except Exception as exc:
            self._finish_run(run_id, "failed", str(exc))
            raise

    def _handle_user_input(self, user_input: str, run_id: str) -> str:
        if user_input.startswith("/"):
            response = self._run_local_command(user_input, run_id)
            if self._should_record_session_turn(user_input):
                self.session.record_turn(user_input, response)
            return response

        if self._is_tool_inventory_question(user_input):
            response = self._tool_inventory_text()
            self.session.record_turn(user_input, response)
            return response

        if self._is_save_last_answer_request(user_input):
            return self._save_last_answer()

        if not self.config.has_llm:
            response = (
                "当前是本地演示模式，还没有配置大模型。\n"
                "你可以先使用 /help 查看本地命令，或配置 OPENAI_API_KEY 与 OPENAI_MODEL 后再用自然语言对话。"
            )
            self.session.record_turn(user_input, response)
            return response

        response = self._run_llm_turn(user_input, run_id)
        self.session.record_turn(user_input, response)
        return response

    def _run_local_command(self, user_input: str, run_id: str) -> str:
        # Slash commands are deterministic runtime operations. Keeping their
        # routing outside the LLM path makes local tests stable and cheap.
        return self.command_router.route(user_input, run_id)

    def _build_command_router(self) -> CommandRouter:
        return CommandRouter(
            {
                "/help": lambda _rest, _run_id: self._help_text(),
                "/session": lambda _rest, _run_id: self.session.summary(),
                "/runs": self._handle_runs_command,
                "/trace": self._handle_trace_command,
                "/save-last": lambda _rest, _run_id: self._save_last_answer(),
                "/tools": lambda _rest, _run_id: self._tool_inventory_text(),
                "/notes": self._handle_notes_command,
                "/read": self._handle_read_command,
                "/search": self._handle_search_command,
                "/remember": self._handle_remember_command,
                "/memory": self._handle_memory_command,
                "/experiment": self._handle_experiment_command,
                "/proposal": lambda _rest, _run_id: self._current_proposal_card(),
                "/proposal-detail": lambda _rest, run_id: self._current_proposal_detail(run_id),
                "/apply-proposal": lambda _rest, run_id: self._apply_current_proposal(run_id),
                "/diagnose": self._handle_diagnose_command,
                "/exit": lambda _rest, _run_id: "bye",
            }
        )

    def _handle_runs_command(self, rest: str, run_id: str) -> str:
        if rest == "--detail":
            return render_run_trace(self.runtime_store, "latest", current_run_id=run_id)
        return render_recent_runs(self.runtime_store)

    def _handle_trace_command(self, rest: str, run_id: str) -> str:
        return render_run_trace(self.runtime_store, rest or "latest", current_run_id=run_id)

    def _handle_notes_command(self, _rest: str, run_id: str) -> str:
        return self._call_tool("list_notes", {}, run_id, confirmed=True, caller="local_command")

    def _handle_read_command(self, rest: str, run_id: str) -> str:
        if not rest:
            return "用法：/read agent.md"
        return self._call_tool(
            "read_note",
            {"path": rest},
            run_id,
            confirmed=True,
            caller="local_command",
        )

    def _handle_search_command(self, rest: str, run_id: str) -> str:
        if not rest:
            return "用法：/search Agent 主循环"
        return self._call_tool(
            "search_notes",
            {"query": rest},
            run_id,
            confirmed=True,
            caller="local_command",
        )

    def _handle_remember_command(self, rest: str, run_id: str) -> str:
        if not rest:
            return "用法：/remember 今天理解了工具调用"
        return self._call_tool(
            "save_memory",
            {"content": rest, "tag": "learning"},
            run_id,
            confirmed=True,
            caller="local_command",
        )

    def _handle_memory_command(self, _rest: str, run_id: str) -> str:
        return self._call_tool("list_memory", {}, run_id, confirmed=True, caller="local_command")

    def _handle_experiment_command(self, rest: str, run_id: str) -> str:
        if not rest:
            return "用法：/experiment 比较 40/50/60 摄氏度下的反应效率"
        return self._create_experiment_proposal(rest, run_id)

    def _handle_diagnose_command(self, rest: str, run_id: str) -> str:
        transition_error = self._record_proposal_event("diagnosed", {"issue": rest}, run_id)
        if transition_error:
            return transition_error
        return diagnose_experiment_issue(self.proposal_store.current(), rest)

    def _should_record_session_turn(self, user_input: str) -> bool:
        command = user_input.partition(" ")[0]
        return command not in {"/session", "/runs", "/trace", "/save-last", "/exit"}

    def _is_tool_inventory_question(self, user_input: str) -> bool:
        normalized = user_input.lower()
        tool_words = ("工具", "tool", "tools", "function", "函数")
        inventory_words = ("几个", "哪些", "列表", "可以调用", "有什么", "当前有")
        return any(word in normalized for word in tool_words) and any(
            word in normalized for word in inventory_words
        )

    def _tool_inventory_text(self) -> str:
        summaries = self.registry.permission_summaries()
        lines = [f"当前本项目注册了 {len(summaries)} 个工具："]
        for index, (name, description, permission) in enumerate(summaries, start=1):
            lines.append(f"{index}. `{name}`：{description}")
            lines.append(f"   权限边界：{permission}")
        lines.append("")
        lines.append("说明：这里列出的只是真正传给本项目 LLM Tool Calling 的工具，不包括 Codex 外层开发工具。")
        return "\n".join(lines)

    def _is_save_last_answer_request(self, user_input: str) -> bool:
        normalized = user_input.lower()
        transform_words = ("改写", "重写", "整理成", "总结成", "一句话")
        non_request_phrases = (
            "保存了",
            "已保存",
            "是否保存",
            "有没有保存",
            "有保存",
            "被保存",
            "历史记录",
            "运行记录",
            "日志记录",
            "记录表",
        )
        question_markers = ("?", "？", "吗", "么", "是不是", "是否", "有没有")
        if any(word in normalized for word in transform_words):
            return False
        if any(word in normalized for word in non_request_phrases):
            return False
        if any(word in normalized for word in question_markers):
            return False

        request_patterns = (
            r"(请|帮我|麻烦)?(保存|记住|存一下|存起来|记录一下|记录下来).*(刚才|上面|上一轮|上轮|last|这些内容|这些要点|这些结论|这个结果|这个回答|这段回答|这条回答)",
            r"把(刚才|上面|上一轮|上轮|这些内容|这些要点|这些结论|这个结果|这个回答|这段回答|这条回答).*(保存|记住|存一下|存起来|记录一下|记录下来)",
            r"save\s+(last|previous)",
        )
        return any(re.search(pattern, normalized) for pattern in request_patterns)

    def _save_last_answer(self) -> str:
        if not self.session.last_answer:
            return "当前会话还没有上一轮回答可保存。"
        item = self.memory_store.add(content=self.session.last_answer, tag="session")
        return f"已保存上一轮回答到长期记忆 #{item['id']} [session]。"

    def _create_experiment_proposal(self, objective: str, run_id: str) -> str:
        self._set_proposal_run(run_id)
        proposal = create_experiment_proposal(
            objective,
            self.registry,
            tool_caller=lambda name, arguments: self._call_tool(
                name,
                arguments,
                run_id,
                confirmed=True,
                caller="proposal_flow",
            ),
        )
        proposal = self.proposal_store.save_current(proposal)
        return render_proposal_card(proposal)

    def _current_proposal_card(self) -> str:
        proposal = self.proposal_store.current()
        if proposal is None:
            return "当前没有 Proposal。先使用 `/experiment ...` 生成一个实验工作流提案。"
        return render_proposal_card(proposal)

    def _current_proposal_detail(self, run_id: str) -> str:
        proposal = self.proposal_store.current()
        if proposal is None:
            return "当前没有 Proposal。先使用 `/experiment ...` 生成一个实验工作流提案。"
        transition_error = self._record_proposal_event("viewed", {"view": "detail"}, run_id)
        if transition_error:
            return transition_error
        return render_proposal_detail(proposal)

    def _apply_current_proposal(self, run_id: str) -> str:
        proposal = self.proposal_store.current()
        if proposal is None:
            return "当前没有 Proposal，无法应用。"
        if proposal.get("status") == "need_info":
            return "当前 Proposal 仍是 need_info 状态，不能应用。请先补充信息并重新生成。"
        if proposal.get("status") == "applied":
            return "当前 Proposal 已应用过。为避免重复执行，本命令不会再次应用。"

        self._set_proposal_run(run_id)
        try:
            applied = self.proposal_store.mark_applied()
        except (ValueError, StateMachineError) as exc:
            return f"Proposal 状态转换失败：{exc}"
        item = self.memory_store.add(
            content=f"已应用实验工作流 Proposal：{applied.get('summary', '')}",
            tag="proposal",
        )
        return (
            "Proposal 已应用到本地记录。\n"
            "当前阶段没有控制真实设备，也没有写入外部系统。\n"
            f"审计记忆：#{item['id']}"
        )

    def _run_llm_turn(self, user_input: str, run_id: str) -> str:
        # 最小 Tool Calling 循环：
        # 1. 把用户问题和工具 schema 发给模型；
        # 2. 如果模型返回 tool_calls，就由 Python 执行真实工具；
        # 3. 把工具结果再交回模型，让模型组织最终答案。
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            *self.session.recent_messages(),
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
                    messages.append(self._execute_tool_call(tool_call, run_id))

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

    def _execute_tool_call(self, tool_call: dict[str, Any], run_id: str) -> dict[str, Any]:
        # 模型只负责“提出要调用哪个工具和参数”，真实执行必须回到受控的 Python 工具注册器。
        # 这也是权限控制边界：模型不能直接访问文件系统，只能调用 registry 暴露的工具。
        function = tool_call.get("function") or {}
        name = str(function.get("name") or "")
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}

        result = self._call_tool(name, arguments, run_id, confirmed=False, caller="llm_tool_call")

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id", name),
            "name": name,
            "content": result,
        }

    def _call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        run_id: str,
        *,
        confirmed: bool = False,
        caller: str = "unknown",
    ) -> str:
        request = ToolExecutionRequest(
                name,
            arguments=arguments,
            run_id=run_id,
            confirmed=confirmed,
            caller=caller,
        )
        return self.tool_executor.call(request).content

    def _start_run(self, user_input: str) -> str:
        if not self.runtime_store:
            return ""
        session_id = str(getattr(self.session, "session_id", "in-memory"))
        return str(self.runtime_store.start_agent_run(session_id, user_input))

    def _finish_run(self, run_id: str, status: str, error: str = "") -> None:
        if self.runtime_store and run_id:
            self.runtime_store.finish_agent_run(run_id, status, error)

    def _set_proposal_run(self, run_id: str) -> None:
        if hasattr(self.proposal_store, "set_current_run"):
            self.proposal_store.set_current_run(run_id)

    def _record_proposal_event(self, event_type: str, event: dict[str, Any], run_id: str) -> str:
        self._set_proposal_run(run_id)
        if hasattr(self.proposal_store, "record_event"):
            try:
                self.proposal_store.record_event(event_type, event)
            except (ValueError, StateMachineError) as exc:
                return f"Proposal 状态转换失败：{exc}"
        return ""

    def _help_text(self) -> str:
        return """本地演示命令：
/session                       查看当前会话短期上下文
/runs                          查看最近 Agent Run 与工具调用日志
/trace <run_id>                查看指定或最近一次 Agent Run 的 trace 明细
/runs --detail                 兼容别名，等价于 /trace latest
/save-last                     保存上一轮 Agent 回答到长期记忆
/tools                         查看当前项目注册的工具
/notes                         列出 notes/ 下的笔记
/read agent.md                 读取某篇笔记
/search Agent 主循环           搜索笔记内容
/remember 今天理解了工具调用   保存一条学习记忆
/memory                        查看最近学习记忆
/experiment 比较 40/50/60 摄氏度下的反应效率
                               生成实验工作流 Proposal
/proposal                      查看当前 Proposal 卡片
/proposal-detail               查看当前 Proposal 详情
/apply-proposal                人工确认后应用到本地记录
/diagnose 端口连接超时        基于当前 Proposal 生成诊断建议
/exit                          退出 CLI

配置大模型后，也可以直接输入自然语言，例如：
帮我搜索笔记里关于 Agent 主循环的内容，并总结成 3 点。"""
