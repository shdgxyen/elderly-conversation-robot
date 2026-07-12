"""Small adapter between HTTP workflows and the device state machine."""

from __future__ import annotations

import logging
from typing import Protocol

logger = logging.getLogger(__name__)


class StateController(Protocol):
    @property
    def current_state(self) -> str:
        """Current state name."""

    def transition_to(self, state: str, *, reason: str | None = None) -> None:
        """Move to a named state."""


class InMemoryStateController:
    """Fallback used when the optional serial/device package is unavailable."""

    def __init__(self, initial_state: str = "IDLE") -> None:
        self._state = initial_state

    @property
    def current_state(self) -> str:
        return self._state

    def transition_to(self, state: str, *, reason: str | None = None) -> None:
        del reason
        self._state = state

    def snapshot(self) -> dict[str, str]:
        return {"state": self.current_state}


class DeviceStateController:
    """Normalize ``DeviceStateMachine`` to the HTTP workflow interface."""

    def __init__(self, machine: object, state_enum: type) -> None:
        self.machine = machine
        self.state_enum = state_enum

    @property
    def current_state(self) -> str:
        state = self.machine.state  # type: ignore[attr-defined]
        return getattr(state, "value", str(state))

    def transition_to(self, state: str, *, reason: str | None = None) -> None:
        enum_state = self.state_enum(state)
        self.machine.transition(enum_state, reason=reason)  # type: ignore[attr-defined]


def build_state_controller() -> StateController:
    """Use the real local state machine when installed, otherwise a safe mock."""

    try:
        from app.device.device_state import DeviceState, DeviceStateMachine

        machine = DeviceStateMachine(initial_state=DeviceState.BOOTING)
        machine.transition(DeviceState.IDLE, reason="backend startup")
        return DeviceStateController(machine, DeviceState)
    except ImportError:
        logger.info("Device state module is unavailable; using in-memory state")
        return InMemoryStateController()
