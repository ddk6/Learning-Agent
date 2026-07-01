from __future__ import annotations

from app.plugins.base import PluginContext
from app.tools.registry import ToolRegistry
from app.tools.web_tools import register_web_tools


class WebPlugin:
    name = "web"

    def register(self, registry: ToolRegistry, context: PluginContext) -> None:
        register_web_tools(
            registry,
            provider=context.config.web_search_provider,
            tavily_api_key=context.config.tavily_api_key,
            brave_search_api_key=context.config.brave_search_api_key,
        )
