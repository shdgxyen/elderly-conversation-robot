"""Strict and extensible JSON Lines protocol shared with the ESP32.

Every call parses exactly one UTF-8 JSON object.  Unknown message types,
unknown fields, duplicate keys, non-standard JSON constants, and direction
mismatches are rejected.  New message types can be added explicitly with
``register_message_type`` without weakening validation of existing messages.
"""

from __future__ import annotations

import json
import re
import threading
from enum import Enum
from typing import Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
    model_validator,
)

from .device_state import DeviceState


# Maximum encoded JSON payload, explicitly excluding the trailing LF/CRLF.
# Keep this value aligned with CONFIG_ELDER_JSON_LINE_MAX_LENGTH in firmware.
MAX_JSON_PAYLOAD_BYTES = 2_048
# Backward-compatible name; its value has payload (not terminator) semantics.
MAX_JSON_LINE_BYTES = MAX_JSON_PAYLOAD_BYTES


class ProtocolError(ValueError):
    """Base exception for a malformed or invalid wire message."""


class ProtocolDecodeError(ProtocolError):
    """The line was not one valid UTF-8 JSON object."""


class ProtocolValidationError(ProtocolError):
    """The JSON object did not conform to its declared message schema."""


class UnknownMessageTypeError(ProtocolValidationError):
    """The ``type`` discriminator is not registered."""


class MessageDirection(str, Enum):
    PI_TO_ESP32 = "pi_to_esp32"
    ESP32_TO_PI = "esp32_to_pi"


class ButtonEvent(str, Enum):
    WAKE_BUTTON_PRESSED = "WAKE_BUTTON_PRESSED"
    STOP_BUTTON_PRESSED = "STOP_BUTTON_PRESSED"


class TouchEvent(str, Enum):
    SCREEN_TAPPED = "SCREEN_TAPPED"


class WireMessage(BaseModel):
    """Base model for protocol messages.

    Subclasses must use a literal ``type`` field.  ``extra='forbid'`` is kept
    per model so a firmware/backend version mismatch fails loudly.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, use_enum_values=False)

    type: StrictStr


class StateMessage(WireMessage):
    type: Literal["state"] = "state"
    state: DeviceState


class FaceMessage(WireMessage):
    type: Literal["face"] = "face"
    emotion: StrictStr = Field(min_length=1, max_length=64)
    intensity: float = Field(ge=0.0, le=1.0, strict=True)

    @field_validator("emotion")
    @classmethod
    def emotion_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("emotion cannot be blank")
        return value


class UserMessage(WireMessage):
    type: Literal["user"] = "user"
    recognized: StrictBool
    display_name: StrictStr | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def recognized_user_has_a_name(self) -> "UserMessage":
        if self.display_name is not None and not self.display_name.strip():
            raise ValueError("display_name cannot be blank")
        if self.recognized and self.display_name is None:
            raise ValueError("display_name is required for a recognized user")
        return self


class ErrorMessage(WireMessage):
    type: Literal["error"] = "error"
    code: StrictStr = Field(min_length=1, max_length=64)
    message: StrictStr = Field(min_length=1, max_length=512)

    @field_validator("code", "message")
    @classmethod
    def error_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("error fields cannot be blank")
        return value


class DisplayMessage(WireMessage):
    type: Literal["display"] = "display"
    brightness: StrictInt = Field(ge=0, le=100)


class SoundMessage(WireMessage):
    type: Literal["sound"] = "sound"
    name: StrictStr = Field(min_length=1, max_length=64)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("sound name cannot be blank")
        return value


class EventMessage(WireMessage):
    type: Literal["event"] = "event"
    event: ButtonEvent


class PrivacyMessage(WireMessage):
    type: Literal["privacy"] = "privacy"
    mic_muted: StrictBool | None = None
    camera_blocked: StrictBool | None = None

    @model_validator(mode="after")
    def at_least_one_switch_is_present(self) -> "PrivacyMessage":
        if self.mic_muted is None and self.camera_blocked is None:
            raise ValueError("privacy requires mic_muted and/or camera_blocked")
        return self


class TouchMessage(WireMessage):
    type: Literal["touch"] = "touch"
    event: TouchEvent
    x: StrictInt = Field(ge=0)
    y: StrictInt = Field(ge=0)


class HeartbeatMessage(WireMessage):
    type: Literal["heartbeat"] = "heartbeat"
    uptime_ms: StrictInt = Field(ge=0)


PiToEsp32Message: TypeAlias = (
    StateMessage
    | FaceMessage
    | UserMessage
    | ErrorMessage
    | DisplayMessage
    | SoundMessage
)
Esp32ToPiMessage: TypeAlias = (
    EventMessage | PrivacyMessage | TouchMessage | HeartbeatMessage
)
ProtocolMessage: TypeAlias = PiToEsp32Message | Esp32ToPiMessage

# Descriptive aliases retained for callers that prefer command-oriented names.
SetStateMessage = StateMessage
SetFaceMessage = FaceMessage
SetUserMessage = UserMessage
SetDisplayMessage = DisplayMessage
PlaySoundMessage = SoundMessage
DeviceEventMessage = EventMessage


_PI_TO_ESP32_MODELS: dict[str, type[WireMessage]] = {
    "state": StateMessage,
    "face": FaceMessage,
    "user": UserMessage,
    "error": ErrorMessage,
    "display": DisplayMessage,
    "sound": SoundMessage,
}
_ESP32_TO_PI_MODELS: dict[str, type[WireMessage]] = {
    "event": EventMessage,
    "privacy": PrivacyMessage,
    "touch": TouchMessage,
    "heartbeat": HeartbeatMessage,
}
_REGISTRY_LOCK = threading.RLock()
_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def _registry(direction: MessageDirection) -> dict[str, type[WireMessage]]:
    if direction == MessageDirection.PI_TO_ESP32:
        return _PI_TO_ESP32_MODELS
    return _ESP32_TO_PI_MODELS


def register_message_type(
    direction: MessageDirection | str,
    message_type: str,
    model: type[WireMessage],
    *,
    replace: bool = False,
) -> None:
    """Explicitly register an extension message schema.

    Extensions remain strict because the model must derive from ``WireMessage``.
    Registration is process-local and thread-safe.
    """

    parsed_direction = MessageDirection(direction)
    if not isinstance(message_type, str) or not _TYPE_PATTERN.fullmatch(message_type):
        raise ValueError("message_type must match [a-z][a-z0-9_]{0,63}")
    if not isinstance(model, type) or not issubclass(model, WireMessage):
        raise TypeError("model must be a WireMessage subclass")
    registry = _registry(parsed_direction)
    other_registry = _registry(
        MessageDirection.ESP32_TO_PI
        if parsed_direction == MessageDirection.PI_TO_ESP32
        else MessageDirection.PI_TO_ESP32
    )
    with _REGISTRY_LOCK:
        if message_type in other_registry:
            raise ValueError(
                f"message type {message_type!r} is registered in the other direction"
            )
        if message_type in registry and not replace:
            raise ValueError(f"message type {message_type!r} is already registered")
        registry[message_type] = model


def parse_json_line(
    line: str | bytes | bytearray | memoryview,
    *,
    direction: MessageDirection | str | None = None,
    max_bytes: int = MAX_JSON_PAYLOAD_BYTES,
) -> ProtocolMessage:
    """Parse exactly one UTF-8 JSON Lines record."""

    text = _decode_one_line(line, max_bytes=max_bytes)
    try:
        payload = json.loads(
            text,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_json_constant,
        )
    except ProtocolDecodeError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise ProtocolDecodeError(f"invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ProtocolDecodeError("a protocol line must contain one JSON object")

    message_type = payload.get("type")
    if not isinstance(message_type, str):
        raise ProtocolValidationError("message type must be a string")

    parsed_direction = MessageDirection(direction) if direction is not None else None
    with _REGISTRY_LOCK:
        if parsed_direction is None:
            matches = [
                registry[message_type]
                for registry in (_PI_TO_ESP32_MODELS, _ESP32_TO_PI_MODELS)
                if message_type in registry
            ]
            if not matches:
                raise UnknownMessageTypeError(f"unknown message type: {message_type!r}")
            if len(matches) > 1:
                raise ProtocolValidationError(
                    f"ambiguous message type {message_type!r}; specify direction"
                )
            model = matches[0]
        else:
            registry = _registry(parsed_direction)
            model = registry.get(message_type)
            if model is None:
                other = _registry(
                    MessageDirection.ESP32_TO_PI
                    if parsed_direction == MessageDirection.PI_TO_ESP32
                    else MessageDirection.PI_TO_ESP32
                )
                if message_type in other:
                    raise ProtocolValidationError(
                        f"message type {message_type!r} is invalid for {parsed_direction.value}"
                    )
                raise UnknownMessageTypeError(f"unknown message type: {message_type!r}")

    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        raise ProtocolValidationError(
            f"invalid {message_type!r} message: {exc}"
        ) from exc


def parse_pi_to_esp32_message(
    line: str | bytes | bytearray | memoryview,
) -> PiToEsp32Message:
    return parse_json_line(line, direction=MessageDirection.PI_TO_ESP32)  # type: ignore[return-value]


def parse_esp32_message(
    line: str | bytes | bytearray | memoryview,
) -> Esp32ToPiMessage:
    return parse_json_line(line, direction=MessageDirection.ESP32_TO_PI)  # type: ignore[return-value]


parse_esp32_to_pi_message = parse_esp32_message
parse_message = parse_json_line
decode_message = parse_json_line


def serialize_json_line(
    message: WireMessage,
    *,
    direction: MessageDirection | str | None = None,
    newline: bool = True,
) -> bytes:
    """Serialize a validated message as compact UTF-8 JSON Lines bytes."""

    if not isinstance(message, WireMessage):
        raise TypeError("message must be a validated WireMessage instance")
    message_type = message.type
    parsed_direction = MessageDirection(direction) if direction is not None else None
    if parsed_direction is not None:
        with _REGISTRY_LOCK:
            expected = _registry(parsed_direction).get(message_type)
        if expected is None or not isinstance(message, expected):
            raise ProtocolValidationError(
                f"message type {message_type!r} is invalid for {parsed_direction.value}"
            )

    payload = message.model_dump(mode="json", exclude_none=True)
    text = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    encoded_payload = text.encode("utf-8", errors="strict")
    if len(encoded_payload) > MAX_JSON_PAYLOAD_BYTES:
        raise ProtocolValidationError("serialized message exceeds maximum payload size")
    return encoded_payload + (b"\n" if newline else b"")


def serialize_pi_message(message: PiToEsp32Message, *, newline: bool = True) -> bytes:
    return serialize_json_line(
        message, direction=MessageDirection.PI_TO_ESP32, newline=newline
    )


serialize_pi_to_esp32_message = serialize_pi_message


def serialize_esp32_message(
    message: Esp32ToPiMessage, *, newline: bool = True
) -> bytes:
    return serialize_json_line(
        message, direction=MessageDirection.ESP32_TO_PI, newline=newline
    )


serialize_esp32_to_pi_message = serialize_esp32_message
serialize_message = serialize_json_line
encode_message = serialize_json_line


def message_to_json(message: WireMessage) -> str:
    """Return one compact JSON object without the JSON Lines terminator."""

    return serialize_json_line(message, newline=False).decode("utf-8")


def _decode_one_line(
    raw: str | bytes | bytearray | memoryview, *, max_bytes: int
) -> str:
    if max_bytes < 1:
        raise ValueError("max_bytes must be positive")
    if isinstance(raw, str):
        try:
            raw.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ProtocolDecodeError(
                "line contains an invalid Unicode surrogate"
            ) from exc
        text = raw
    elif isinstance(raw, (bytes, bytearray, memoryview)):
        data = bytes(raw)
        try:
            text = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise ProtocolDecodeError("line is not valid UTF-8") from exc
    else:
        raise TypeError("line must be str or bytes-like")
    # Accept one conventional JSONL terminator, but reject embedded/additional
    # records so callers cannot accidentally validate only the first object.
    if text.endswith("\n"):
        text = text[:-1]
        if text.endswith("\r"):
            text = text[:-1]
    if "\n" in text or "\r" in text:
        raise ProtocolDecodeError("expected exactly one JSON line")
    if not text.strip():
        raise ProtocolDecodeError("empty JSON line")
    # Recalculate after removing LF/CRLF: the shared protocol limit applies to
    # the encoded JSON payload only.
    payload_bytes = len(text.encode("utf-8", errors="strict"))
    if payload_bytes > max_bytes:
        raise ProtocolDecodeError(f"JSON payload exceeds {max_bytes} bytes")
    return text


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProtocolDecodeError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ProtocolDecodeError(f"non-standard JSON constant is not allowed: {value}")


__all__ = [
    "ButtonEvent",
    "DeviceEventMessage",
    "DisplayMessage",
    "ErrorMessage",
    "Esp32ToPiMessage",
    "EventMessage",
    "FaceMessage",
    "HeartbeatMessage",
    "MAX_JSON_LINE_BYTES",
    "MAX_JSON_PAYLOAD_BYTES",
    "MessageDirection",
    "PiToEsp32Message",
    "PlaySoundMessage",
    "PrivacyMessage",
    "ProtocolDecodeError",
    "ProtocolError",
    "ProtocolMessage",
    "ProtocolValidationError",
    "SetDisplayMessage",
    "SetFaceMessage",
    "SetStateMessage",
    "SetUserMessage",
    "SoundMessage",
    "StateMessage",
    "TouchEvent",
    "TouchMessage",
    "UnknownMessageTypeError",
    "UserMessage",
    "WireMessage",
    "decode_message",
    "encode_message",
    "message_to_json",
    "parse_esp32_message",
    "parse_esp32_to_pi_message",
    "parse_json_line",
    "parse_message",
    "parse_pi_to_esp32_message",
    "register_message_type",
    "serialize_esp32_message",
    "serialize_esp32_to_pi_message",
    "serialize_json_line",
    "serialize_message",
    "serialize_pi_message",
    "serialize_pi_to_esp32_message",
]
