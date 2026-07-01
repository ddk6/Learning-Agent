from __future__ import annotations

from app.plugins.base import PluginContext
from app.tools.note_tools import register_note_tools
from app.tools.registry import ToolRegistry


class NotesPlugin:
    name = "notes"

    def register(self, registry: ToolRegistry, context: PluginContext) -> None:
        register_note_tools(registry, context.config.notes_dir)
