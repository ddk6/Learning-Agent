from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class StateMachineError(ValueError):
    pass


@dataclass(frozen=True)
class StateTransition:
    from_state: str
    event_type: str
    to_state: str


class StateMachine:
    def __init__(self, name: str, initial_state: str, states: dict[str, dict[str, Any]]) -> None:
        self.name = name
        self.initial_state = initial_state
        self.states = states
        if initial_state not in states:
            raise StateMachineError(f"Initial state is not defined: {initial_state}")

    @classmethod
    def from_file(cls, path: Path) -> "StateMachine":
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise StateMachineError("State machine config must be a JSON object.")
        name = str(data.get("name") or path.stem)
        initial_state = str(data.get("initial_state") or "")
        states = data.get("states")
        if not isinstance(states, dict):
            raise StateMachineError("State machine config must contain a states object.")
        normalized: dict[str, dict[str, Any]] = {}
        for state, config in states.items():
            if not isinstance(config, dict):
                raise StateMachineError(f"State config must be an object: {state}")
            events = config.get("events", {})
            if not isinstance(events, dict):
                raise StateMachineError(f"State events must be an object: {state}")
            normalized[str(state)] = {
                "description": str(config.get("description") or ""),
                "events": {str(event): str(target) for event, target in events.items()},
            }
        return cls(name=name, initial_state=initial_state, states=normalized)

    def transition(self, current_state: str, event_type: str) -> StateTransition:
        current_state = current_state.strip()
        event_type = event_type.strip()
        if current_state not in self.states:
            raise StateMachineError(f"Unknown state: {current_state}")
        events = self.states[current_state].get("events", {})
        if event_type not in events:
            allowed = ", ".join(sorted(events)) or "none"
            raise StateMachineError(
                f"Event {event_type!r} is not allowed from state {current_state!r}. "
                f"Allowed events: {allowed}."
            )
        to_state = str(events[event_type])
        if to_state not in self.states:
            raise StateMachineError(f"Transition target is not defined: {to_state}")
        return StateTransition(
            from_state=current_state,
            event_type=event_type,
            to_state=to_state,
        )
