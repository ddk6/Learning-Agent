from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolExecutionRequest:
    """Runtime-facing description of one tool call.

    The model can request a tool, but the runtime owns caller identity,
    confirmation state, run correlation, and audit metadata.
    """

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    run_id: str = ""
    confirmed: bool = False
    caller: str = "unknown"


@dataclass(frozen=True)
class ToolExecutionResult:
    """Normalized result used by the agent, trace store, and future approval UI."""

    content: str
    success: bool
    error: str
    duration_ms: int
    policy_decision: str
