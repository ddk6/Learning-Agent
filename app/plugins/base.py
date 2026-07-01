from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from app.config import AppConfig
from app.tools.registry import ToolRegistry


@dataclass(frozen=True)
class PluginContext:
    """Shared runtime dependencies exposed to plugin registration functions."""

    config: AppConfig
    memory_store: Any


class RuntimePlugin(Protocol):
    """Small plugin contract for registering tools into the runtime."""

    name: str

    def register(self, registry: ToolRegistry, context: PluginContext) -> None:
        ...


def register_default_plugins(registry: ToolRegistry, context: PluginContext) -> None:
    # Import inside the function to keep plugin modules independent and cheap to load.
    from app.plugins.memory_plugin import MemoryPlugin
    from app.plugins.notes_plugin import NotesPlugin
    from app.plugins.web_plugin import WebPlugin
    from app.plugins.workflow_plugin import WorkflowPlugin

    for plugin in (MemoryPlugin(), NotesPlugin(), WebPlugin(), WorkflowPlugin()):
        plugin.register(registry, context)
