from __future__ import annotations

from app.plugins.base import PluginContext
from app.tools.experiment_tools import register_experiment_tools
from app.tools.registry import ToolRegistry


class WorkflowPlugin:
    name = "workflow"

    def register(self, registry: ToolRegistry, context: PluginContext) -> None:
        register_experiment_tools(registry)
