from __future__ import annotations

import time
from typing import Any

from app.runtime.approval import ToolExecutionRequest, ToolExecutionResult
from app.tools.registry import ToolRegistry


#这是工具执行器的类 主要负责工具的执行、记录执行结果等
#一般由agent调用 通过调用工具执行器来执行工具
class ToolExecutor:
    """Executes registered tools and records the audit trail.

    This class is the boundary between planning and side effects. Agent code
    passes a `ToolExecutionRequest`; the executor enforces registry policy,
    calls the handler, records trace data, and returns normalized text.
    """

    def __init__(
        self,
        registry: ToolRegistry,
        session_state: Any,
        runtime_store: Any | None = None,
    ) -> None:
        self.registry = registry
        self.session = session_state
        self.runtime_store = runtime_store

    def call(self, request: ToolExecutionRequest) -> ToolExecutionResult:
        started = time.perf_counter()
        success = True
        error = ""
        policy_decision = ""

        try:
            policy_decision = self.registry.policy_decision(
                request.name,
                confirmed=request.confirmed,
                caller=request.caller,
            )
            content = self.registry.call(
                request.name,
                request.arguments,
                confirmed=request.confirmed,
                caller=request.caller,
            )
        except Exception as exc:
            success = False
            error = str(exc)
            if not policy_decision:
                policy_decision = f"error_before_policy_decision; caller={request.caller}"
            content = f"工具 {request.name} 执行失败：{exc}"

        duration_ms = max(0, int((time.perf_counter() - started) * 1000))
        self._record(request, content, success, error, duration_ms, policy_decision)
        return ToolExecutionResult(
            content=content,
            success=success,
            error=error,
            duration_ms=duration_ms,
            policy_decision=policy_decision,
        )

    def _record(
        self,
        request: ToolExecutionRequest,
        content: str,
        success: bool,
        error: str,
        duration_ms: int,
        policy_decision: str,
    ) -> None:
        if hasattr(self.session, "record_tool_result"):
            self.session.record_tool_result(request.name, content)

        if not self.runtime_store or not request.run_id:
            return

        audit_arguments = dict(request.arguments)
        audit_arguments["_audit"] = {
            "caller": request.caller,
            "confirmed": request.confirmed,
            "policy_decision": policy_decision,
        }
        self.runtime_store.add_tool_call(
            run_id=request.run_id,
            tool_name=request.name,
            arguments=audit_arguments,
            result=content,
            success=success,
            error=error,
            duration_ms=duration_ms,
        )
