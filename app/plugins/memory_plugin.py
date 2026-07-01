from __future__ import annotations

from app.plugins.base import PluginContext
from app.tools.memory_tools import register_memory_tools
from app.tools.registry import ToolRegistry


class MemoryPlugin:
    name = "memory"

    def register(self, registry: ToolRegistry, context: PluginContext) -> None:
        register_memory_tools(registry, context.memory_store)
