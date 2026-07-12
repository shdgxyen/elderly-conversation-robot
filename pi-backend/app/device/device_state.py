"""Thread-safe device state and physical privacy controls.

The state machine deliberately keeps physical privacy switches authoritative.  A
caller cannot put the device into a microphone/camera-using state while the
corresponding switch is off, even by using ``force=True``.
"""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DeviceState(str, Enum):
    """All device states defined by ``docs/PROJECT_SPEC.md``."""

    BOOTING = "BOOTING"
    IDLE = "IDLE"
    FACE_SCANNING = "FACE_SCANNING"
    USER_RECOGNIZED = "USER_RECOGNIZED"
    UNKNOWN_USER = "UNKNOWN_USER"
    LISTENING = "LISTENING"
    THINKING = "THINKING"
    SPEAKING = "SPEAKING"
    CONFUSED = "CONFUSED"
    COMFORT = "COMFORT"
    PRIVACY_MIC_OFF = "PRIVACY_MIC_OFF"
    PRIVACY_CAMERA_OFF = "PRIVACY_CAMERA_OFF"
    NETWORK_ERROR = "NETWORK_ERROR"
    API_ERROR = "API_ERROR"
    LOW_POWER = "LOW_POWER"


PRIVACY_STATES = frozenset(
    {DeviceState.PRIVACY_MIC_OFF, DeviceState.PRIVACY_CAMERA_OFF}
)


class DeviceStateError(RuntimeError):
    """Base exception for state-machine errors."""


class InvalidStateTransition(DeviceStateError):
    """Raised when a requested transition is not part of the state graph."""

    def __init__(self, previous: DeviceState, requested: DeviceState) -> None:
        self.previous = previous
        self.requested = requested
        super().__init__(f"invalid device state transition: {previous} -> {requested}")


class PrivacyConstraintError(DeviceStateError):
    """Raised when a physical privacy control forbids an operation."""


class DeviceStateSnapshot(BaseModel):
    """Immutable, JSON-serializable view of the current device state."""

    model_config = ConfigDict(frozen=True, use_enum_values=False)

    state: DeviceState
    mic_muted: bool = False
    camera_blocked: bool = False
    current_user_id: str | None = None
    last_heartbeat: datetime | None = None
    last_heartbeat_uptime_ms: int | None = Field(default=None, ge=0)


class DeviceStateChange(BaseModel):
    """Notification delivered after an observable state/privacy change."""

    model_config = ConfigDict(frozen=True, use_enum_values=False)

    previous_state: DeviceState
    current_state: DeviceState
    reason: str | None = None
    changed_at: datetime
    snapshot: DeviceStateSnapshot

    @property
    def state(self) -> DeviceState:
        """Convenience alias that also makes simple listeners ergonomic."""

        return self.current_state


StateListener = Callable[[DeviceStateChange], Any | Awaitable[Any]]


_ERROR_STATES = frozenset({DeviceState.NETWORK_ERROR, DeviceState.API_ERROR})

# This is intentionally explicit: it catches programming errors without making
# normal text-chat transitions unnecessarily cumbersome.
_ALLOWED_TRANSITIONS: dict[DeviceState, frozenset[DeviceState]] = {
    DeviceState.BOOTING: frozenset(
        {
            DeviceState.IDLE,
            DeviceState.NETWORK_ERROR,
            DeviceState.API_ERROR,
            DeviceState.LOW_POWER,
        }
    ),
    DeviceState.IDLE: frozenset(
        {
            DeviceState.FACE_SCANNING,
            DeviceState.USER_RECOGNIZED,
            DeviceState.UNKNOWN_USER,
            DeviceState.LISTENING,
            DeviceState.THINKING,
            DeviceState.SPEAKING,
            DeviceState.COMFORT,
            DeviceState.LOW_POWER,
            *_ERROR_STATES,
        }
    ),
    DeviceState.FACE_SCANNING: frozenset(
        {
            DeviceState.USER_RECOGNIZED,
            DeviceState.UNKNOWN_USER,
            DeviceState.IDLE,
            *_ERROR_STATES,
        }
    ),
    DeviceState.USER_RECOGNIZED: frozenset(
        {DeviceState.LISTENING, DeviceState.SPEAKING, DeviceState.IDLE, *_ERROR_STATES}
    ),
    DeviceState.UNKNOWN_USER: frozenset(
        {DeviceState.LISTENING, DeviceState.SPEAKING, DeviceState.IDLE, *_ERROR_STATES}
    ),
    DeviceState.LISTENING: frozenset(
        {
            DeviceState.THINKING,
            DeviceState.CONFUSED,
            DeviceState.IDLE,
            DeviceState.COMFORT,
            *_ERROR_STATES,
        }
    ),
    DeviceState.THINKING: frozenset(
        {
            DeviceState.SPEAKING,
            DeviceState.CONFUSED,
            DeviceState.COMFORT,
            DeviceState.IDLE,
            *_ERROR_STATES,
        }
    ),
    DeviceState.SPEAKING: frozenset(
        {
            DeviceState.IDLE,
            DeviceState.LISTENING,
            DeviceState.COMFORT,
            *_ERROR_STATES,
        }
    ),
    DeviceState.CONFUSED: frozenset(
        {DeviceState.IDLE, DeviceState.LISTENING, DeviceState.SPEAKING, *_ERROR_STATES}
    ),
    DeviceState.COMFORT: frozenset(
        {DeviceState.IDLE, DeviceState.LISTENING, DeviceState.SPEAKING, *_ERROR_STATES}
    ),
    DeviceState.NETWORK_ERROR: frozenset(
        {
            DeviceState.IDLE,
            DeviceState.NETWORK_ERROR,
            DeviceState.API_ERROR,
            DeviceState.LOW_POWER,
        }
    ),
    DeviceState.API_ERROR: frozenset(
        {
            DeviceState.IDLE,
            DeviceState.NETWORK_ERROR,
            DeviceState.API_ERROR,
            DeviceState.LOW_POWER,
        }
    ),
    DeviceState.LOW_POWER: frozenset(
        {DeviceState.IDLE, DeviceState.NETWORK_ERROR, DeviceState.API_ERROR}
    ),
    # Privacy states are handled by physical flag logic rather than this graph.
    DeviceState.PRIVACY_MIC_OFF: frozenset(),
    DeviceState.PRIVACY_CAMERA_OFF: frozenset(),
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceStateMachine:
    """Synchronous state machine safe for threads and async request handlers.

    Operations never await while holding the internal re-entrant lock.  The
    normal methods can therefore be called directly from FastAPI routes; async
    aliases are provided for codebases that prefer an awaitable interface.
    """

    def __init__(
        self,
        initial_state: DeviceState | str = DeviceState.BOOTING,
        *,
        history_size: int = 100,
    ) -> None:
        if history_size < 1:
            raise ValueError("history_size must be at least 1")
        state = DeviceState(initial_state)
        self._lock = threading.RLock()
        self._state = state
        self._mic_muted = state == DeviceState.PRIVACY_MIC_OFF
        self._camera_blocked = state == DeviceState.PRIVACY_CAMERA_OFF
        self._current_user_id: str | None = None
        self._last_heartbeat: datetime | None = None
        self._last_heartbeat_uptime_ms: int | None = None
        self._listeners: list[StateListener] = []
        self._history: deque[DeviceStateChange] = deque(maxlen=history_size)

    @property
    def state(self) -> DeviceState:
        with self._lock:
            return self._state

    @property
    def current_state(self) -> DeviceState:
        return self.state

    @property
    def mic_muted(self) -> bool:
        with self._lock:
            return self._mic_muted

    @property
    def camera_blocked(self) -> bool:
        with self._lock:
            return self._camera_blocked

    @property
    def current_user_id(self) -> str | None:
        with self._lock:
            return self._current_user_id

    @property
    def last_heartbeat(self) -> datetime | None:
        with self._lock:
            return self._last_heartbeat

    @property
    def last_heartbeat_uptime_ms(self) -> int | None:
        with self._lock:
            return self._last_heartbeat_uptime_ms

    def snapshot(self) -> DeviceStateSnapshot:
        with self._lock:
            return self._snapshot_unlocked()

    def get_state(self) -> DeviceStateSnapshot:
        """Compatibility/readability alias for ``snapshot``."""

        return self.snapshot()

    def to_dict(self, *, mode: str = "json") -> dict[str, Any]:
        return self.snapshot().model_dump(mode=mode)

    def history(self) -> tuple[DeviceStateChange, ...]:
        with self._lock:
            return tuple(self._history)

    def add_listener(self, listener: StateListener) -> Callable[[], None]:
        if not callable(listener):
            raise TypeError("listener must be callable")
        with self._lock:
            if listener not in self._listeners:
                self._listeners.append(listener)

        def unsubscribe() -> None:
            self.remove_listener(listener)

        return unsubscribe

    subscribe = add_listener

    def remove_listener(self, listener: StateListener) -> None:
        with self._lock:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

    def transition(
        self,
        new_state: DeviceState | str,
        *,
        reason: str | None = None,
        force: bool = False,
    ) -> DeviceStateSnapshot:
        requested = DeviceState(new_state)
        if requested == DeviceState.PRIVACY_MIC_OFF:
            return self.set_mic_muted(True, reason=reason or "mic privacy enabled")
        if requested == DeviceState.PRIVACY_CAMERA_OFF:
            return self.set_camera_blocked(
                True, reason=reason or "camera privacy enabled"
            )

        with self._lock:
            previous = self._state
            if self._mic_muted and requested == DeviceState.LISTENING:
                raise PrivacyConstraintError(
                    "cannot listen while the microphone is muted"
                )
            if self._camera_blocked and requested == DeviceState.FACE_SCANNING:
                raise PrivacyConstraintError(
                    "cannot scan a face while the camera is blocked"
                )

            # PRIVACY_* is the visual form of safe idle, not a global mode.  The
            # flags independently constrain only capabilities that need the
            # corresponding sensor.
            target = (
                self._idle_display_state_unlocked()
                if requested == DeviceState.IDLE
                else requested
            )
            if target == previous:
                return self._snapshot_unlocked()
            logical_previous = (
                DeviceState.IDLE if previous in PRIVACY_STATES else previous
            )
            if not force and requested not in _ALLOWED_TRANSITIONS[logical_previous]:
                raise InvalidStateTransition(previous, requested)
            self._state = target
            change, listeners = self._record_change_unlocked(previous, reason)

        self._notify(listeners, change)
        return change.snapshot

    set_state = transition

    def set_mic_muted(
        self, muted: bool, *, reason: str | None = None
    ) -> DeviceStateSnapshot:
        if type(muted) is not bool:
            raise TypeError("muted must be a bool")
        return self.set_privacy(mic_muted=muted, reason=reason)

    def set_camera_blocked(
        self, blocked: bool, *, reason: str | None = None
    ) -> DeviceStateSnapshot:
        if type(blocked) is not bool:
            raise TypeError("blocked must be a bool")
        return self.set_privacy(camera_blocked=blocked, reason=reason)

    def set_privacy(
        self,
        *,
        mic_muted: bool | None = None,
        camera_blocked: bool | None = None,
        reason: str | None = None,
    ) -> DeviceStateSnapshot:
        if mic_muted is None and camera_blocked is None:
            raise ValueError("at least one privacy value is required")
        if mic_muted is not None and type(mic_muted) is not bool:
            raise TypeError("mic_muted must be a bool")
        if camera_blocked is not None and type(camera_blocked) is not bool:
            raise TypeError("camera_blocked must be a bool")

        with self._lock:
            previous = self._state
            old_flags = (self._mic_muted, self._camera_blocked)

            if mic_muted is not None:
                self._mic_muted = mic_muted
            if camera_blocked is not None:
                self._camera_blocked = camera_blocked

            # A newly disabled sensor immediately terminates only an operation
            # that needs that sensor.  Other active states continue normally.
            if previous in PRIVACY_STATES or previous == DeviceState.IDLE:
                self._state = self._idle_display_state_unlocked()
            elif previous == DeviceState.LISTENING and self._mic_muted:
                self._state = self._idle_display_state_unlocked()
            elif previous == DeviceState.FACE_SCANNING and self._camera_blocked:
                self._state = self._idle_display_state_unlocked()

            new_flags = (self._mic_muted, self._camera_blocked)
            if previous == self._state and old_flags == new_flags:
                return self._snapshot_unlocked()
            change, listeners = self._record_change_unlocked(
                previous, reason or "physical privacy control changed"
            )

        self._notify(listeners, change)
        return change.snapshot

    def set_current_user_id(self, user_id: str | None) -> DeviceStateSnapshot:
        if user_id is not None:
            if not isinstance(user_id, str):
                raise TypeError("user_id must be a string or None")
            user_id = user_id.strip()
            if not user_id:
                raise ValueError("user_id cannot be empty")
        with self._lock:
            self._current_user_id = user_id
            return self._snapshot_unlocked()

    set_current_user = set_current_user_id

    def record_heartbeat(self, uptime_ms: int | None = None) -> DeviceStateSnapshot:
        if uptime_ms is not None and (type(uptime_ms) is not int or uptime_ms < 0):
            raise ValueError("uptime_ms must be a non-negative integer or None")
        with self._lock:
            self._last_heartbeat = _utcnow()
            self._last_heartbeat_uptime_ms = uptime_ms
            return self._snapshot_unlocked()

    update_heartbeat = record_heartbeat

    def heartbeat_age_seconds(self, *, now: datetime | None = None) -> float | None:
        with self._lock:
            heartbeat = self._last_heartbeat
        if heartbeat is None:
            return None
        current = now or _utcnow()
        if current.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        return max(0.0, (current - heartbeat).total_seconds())

    def is_alive(self, timeout_seconds: float = 10.0) -> bool:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        age = self.heartbeat_age_seconds()
        return age is not None and age <= timeout_seconds

    def handle_event(self, event: str | Enum) -> DeviceStateSnapshot:
        """Apply one of the button events defined by the wire protocol."""

        value = event.value if isinstance(event, Enum) else event
        if value == "WAKE_BUTTON_PRESSED":
            # A physical wake is an explicit request to recover from error/low
            # power and begin a fresh interaction.  Mic privacy still wins.
            return self.transition(DeviceState.LISTENING, reason=value, force=True)
        if value == "STOP_BUTTON_PRESSED":
            return self.transition(DeviceState.IDLE, reason=value, force=True)
        raise ValueError(f"unsupported device event: {value!r}")

    async def atransition(
        self,
        new_state: DeviceState | str,
        *,
        reason: str | None = None,
        force: bool = False,
    ) -> DeviceStateSnapshot:
        return self.transition(new_state, reason=reason, force=force)

    aset_state = atransition

    async def aset_mic_muted(
        self, muted: bool, *, reason: str | None = None
    ) -> DeviceStateSnapshot:
        return self.set_mic_muted(muted, reason=reason)

    async def aset_camera_blocked(
        self, blocked: bool, *, reason: str | None = None
    ) -> DeviceStateSnapshot:
        return self.set_camera_blocked(blocked, reason=reason)

    async def aset_current_user_id(self, user_id: str | None) -> DeviceStateSnapshot:
        return self.set_current_user_id(user_id)

    async def arecord_heartbeat(
        self, uptime_ms: int | None = None
    ) -> DeviceStateSnapshot:
        return self.record_heartbeat(uptime_ms)

    def _snapshot_unlocked(self) -> DeviceStateSnapshot:
        return DeviceStateSnapshot(
            state=self._state,
            mic_muted=self._mic_muted,
            camera_blocked=self._camera_blocked,
            current_user_id=self._current_user_id,
            last_heartbeat=self._last_heartbeat,
            last_heartbeat_uptime_ms=self._last_heartbeat_uptime_ms,
        )

    def _record_change_unlocked(
        self, previous: DeviceState, reason: str | None
    ) -> tuple[DeviceStateChange, tuple[StateListener, ...]]:
        change = DeviceStateChange(
            previous_state=previous,
            current_state=self._state,
            reason=reason,
            changed_at=_utcnow(),
            snapshot=self._snapshot_unlocked(),
        )
        self._history.append(change)
        return change, tuple(self._listeners)

    def _idle_display_state_unlocked(self) -> DeviceState:
        """Return the safe-idle visual state for the current physical flags."""

        if self._mic_muted:
            return DeviceState.PRIVACY_MIC_OFF
        if self._camera_blocked:
            return DeviceState.PRIVACY_CAMERA_OFF
        return DeviceState.IDLE

    @staticmethod
    def _notify(
        listeners: tuple[StateListener, ...], change: DeviceStateChange
    ) -> None:
        for listener in listeners:
            try:
                result = listener(change)
                if inspect.isawaitable(result):
                    try:
                        loop = asyncio.get_running_loop()
                    except RuntimeError:
                        asyncio.run(result)
                    else:
                        loop.create_task(result)
            except Exception:
                # A monitoring callback must never corrupt the device state or
                # prevent other listeners from running.
                continue


__all__ = [
    "DeviceState",
    "DeviceStateChange",
    "DeviceStateError",
    "DeviceStateMachine",
    "DeviceStateSnapshot",
    "InvalidStateTransition",
    "PrivacyConstraintError",
]
