from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


class ProposalStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save_current(self, proposal: dict[str, Any]) -> dict[str, Any]:
        item = dict(proposal)
        item.setdefault("id", str(uuid4()))
        item.setdefault("created_at", now_iso())
        item.setdefault("status", "ready")
        item.setdefault("applied_at", "")
        item.setdefault("apply_count", 0)
        self._write({"current": item, "history": self.history()})
        return item

    def current(self) -> dict[str, Any] | None:
        data = self._read()
        current = data.get("current")
        if isinstance(current, dict):
            return current
        return None

    def mark_applied(self) -> dict[str, Any]:
        proposal = self.current()
        if proposal is None:
            raise ValueError("No current proposal.")
        if proposal.get("status") == "applied":
            return proposal

        proposal = dict(proposal)
        proposal["status"] = "applied"
        proposal["applied_at"] = now_iso()
        proposal["apply_count"] = int(proposal.get("apply_count") or 0) + 1
        history = self.history()
        history.append(proposal)
        self._write({"current": proposal, "history": history[-50:]})
        return proposal

    def history(self) -> list[dict[str, Any]]:
        data = self._read()
        history = data.get("history")
        if not isinstance(history, list):
            return []
        return [item for item in history if isinstance(item, dict)]

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"current": None, "history": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {"current": None, "history": []}
        if not isinstance(data, dict):
            return {"current": None, "history": []}
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
