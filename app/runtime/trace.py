from __future__ import annotations

import json
from typing import Any


def render_recent_runs(runtime_store: Any, limit: int = 10) -> str:
    if not runtime_store or not hasattr(runtime_store, "recent_agent_runs"):
        return "当前运行环境没有可读取的 Agent Run 日志。"
    runs = runtime_store.recent_agent_runs(limit=limit)
    if not runs:
        return "还没有 Agent Run 日志。"

    lines = ["# 最近 Agent Run 日志", ""]
    for run in runs:
        user_input = str(run.get("user_input") or "")
        error = str(run.get("error") or "")
        lines.append(
            "- "
            f"Run ID：{run.get('id')} | "
            f"{run.get('started_at')} | {run.get('status')} | "
            f"tools={run.get('tool_call_count')} "
            f"failed={run.get('failed_tool_call_count')} "
            f"duration={run.get('tool_duration_ms')}ms | "
            f"{user_input[:80]}"
        )
        if error:
            lines.append(f"  error: {error[:160]}")
    return "\n".join(lines)


def render_run_trace(
    runtime_store: Any,
    run_id: str = "latest",
    *,
    current_run_id: str = "",
) -> str:
    if not runtime_store or not hasattr(runtime_store, "agent_run_trace"):
        return "当前运行环境没有可读取的 Agent Trace。"
    trace = runtime_store.agent_run_trace(run_id, exclude_run_id=current_run_id)
    if trace is None:
        return f"没有找到 Agent Run：{run_id or 'latest'}"

    run = trace["run"]
    tool_calls = trace["tool_calls"]
    lines = [
        "# Agent Trace",
        "",
        f"- Run ID：{run['id']}",
        f"- Session：{run['session_id']}",
        f"- 状态：{run['status']}",
        f"- 开始：{run['started_at']}",
        f"- 结束：{run['ended_at'] or 'running'}",
        f"- 用户输入：{run['user_input']}",
        f"- 工具调用数：{len(tool_calls)}",
    ]
    if run.get("error"):
        lines.append(f"- Run 错误：{limit_trace_text(run['error'], 240)}")

    if not tool_calls:
        lines.append("")
        lines.append("本次运行没有工具调用。")
        return "\n".join(lines)

    lines.append("")
    lines.append("## 工具调用")
    for index, call in enumerate(tool_calls, start=1):
        status = "success" if call["success"] else "failed"
        arguments = json.dumps(call["arguments"], ensure_ascii=False, sort_keys=True)
        lines.append(
            f"{index}. `{call['tool_name']}` | {status} | "
            f"{call['duration_ms']}ms | {call['created_at']}"
        )
        lines.append(f"   args: {limit_trace_text(arguments, 400)}")
        if call.get("error"):
            lines.append(f"   error: {limit_trace_text(call['error'], 300)}")
        lines.append(f"   result: {limit_trace_text(call['result'], 500)}")
    return "\n".join(lines)


def limit_trace_text(value: str, limit: int) -> str:
    value = " ".join(str(value).split())
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)] + "..."
