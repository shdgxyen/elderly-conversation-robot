from __future__ import annotations

from typing import Literal

import pytest
from pydantic import StrictInt

from app.device import DeviceState
from app.device.protocol import (
    DisplayMessage,
    ErrorMessage,
    EventMessage,
    FaceMessage,
    HeartbeatMessage,
    MAX_JSON_PAYLOAD_BYTES,
    MessageDirection,
    PrivacyMessage,
    ProtocolDecodeError,
    ProtocolValidationError,
    SoundMessage,
    StateMessage,
    TouchMessage,
    UnknownMessageTypeError,
    UserMessage,
    WireMessage,
    parse_esp32_message,
    parse_json_line,
    parse_pi_to_esp32_message,
    register_message_type,
    serialize_esp32_message,
    serialize_json_line,
    serialize_pi_message,
)


@pytest.mark.parametrize(
    "message",
    [
        StateMessage(state=DeviceState.LISTENING),
        FaceMessage(emotion="smile", intensity=0.8),
        UserMessage(recognized=True, display_name="张奶奶"),
        ErrorMessage(code="NETWORK_ERROR", message="网络连接失败"),
        DisplayMessage(brightness=70),
        SoundMessage(name="wake"),
    ],
)
def test_pi_to_esp32_messages_round_trip_as_utf8_jsonl(message: WireMessage) -> None:
    encoded = serialize_pi_message(message)  # type: ignore[arg-type]

    assert encoded.endswith(b"\n")
    assert parse_pi_to_esp32_message(encoded) == message


@pytest.mark.parametrize(
    "message",
    [
        EventMessage(event="WAKE_BUTTON_PRESSED"),
        EventMessage(event="STOP_BUTTON_PRESSED"),
        PrivacyMessage(mic_muted=True),
        PrivacyMessage(camera_blocked=True),
        PrivacyMessage(mic_muted=False, camera_blocked=False),
        TouchMessage(event="SCREEN_TAPPED", x=212, y=180),
        HeartbeatMessage(uptime_ms=123_456),
    ],
)
def test_esp32_messages_round_trip(message: WireMessage) -> None:
    encoded = serialize_esp32_message(message)  # type: ignore[arg-type]

    assert parse_esp32_message(encoded) == message


def test_direction_is_enforced() -> None:
    line = serialize_json_line(StateMessage(state=DeviceState.IDLE))

    with pytest.raises(ProtocolValidationError, match="invalid for esp32_to_pi"):
        parse_esp32_message(line)


@pytest.mark.parametrize(
    ("line", "error_type"),
    [
        (b"\xff\n", ProtocolDecodeError),
        (b"\n", ProtocolDecodeError),
        (b"[]\n", ProtocolDecodeError),
        (b'{"type":"heartbeat"}\n', ProtocolValidationError),
        (b'{"type":"heartbeat","uptime_ms":"5"}\n', ProtocolValidationError),
        (b'{"type":"heartbeat","uptime_ms":true}\n', ProtocolValidationError),
        (b'{"type":"heartbeat","uptime_ms":1,"extra":2}\n', ProtocolValidationError),
        (b'{"type":"future"}\n', UnknownMessageTypeError),
        (b'{"type":"heartbeat","type":"event","uptime_ms":1}\n', ProtocolDecodeError),
        (b'{"type":"heartbeat","uptime_ms":NaN}\n', ProtocolDecodeError),
        (b'{"type":"heartbeat","uptime_ms":1}\n{}\n', ProtocolDecodeError),
    ],
)
def test_malformed_or_unknown_input_is_rejected(
    line: bytes, error_type: type[Exception]
) -> None:
    with pytest.raises(error_type):
        parse_json_line(line)


def test_protocol_can_be_extended_without_relaxing_existing_models() -> None:
    class BatteryMessage(WireMessage):
        type: Literal["battery_test_extension"] = "battery_test_extension"
        percent: StrictInt

    register_message_type(
        MessageDirection.ESP32_TO_PI,
        "battery_test_extension",
        BatteryMessage,
    )

    parsed = parse_esp32_message(b'{"type":"battery_test_extension","percent":83}\n')
    assert isinstance(parsed, BatteryMessage)
    assert parsed.percent == 83
    with pytest.raises(ProtocolValidationError):
        parse_esp32_message(
            b'{"type":"battery_test_extension","percent":83,"unknown":true}\n'
        )


def test_payload_limit_excludes_jsonl_terminator() -> None:
    base = b'{"type":"heartbeat","uptime_ms":1}'
    at_limit = base + (b" " * (MAX_JSON_PAYLOAD_BYTES - len(base))) + b"\r\n"

    assert parse_esp32_message(at_limit) == HeartbeatMessage(uptime_ms=1)
    with pytest.raises(ProtocolDecodeError, match="payload exceeds"):
        parse_esp32_message(
            base + (b" " * (MAX_JSON_PAYLOAD_BYTES - len(base) + 1)) + b"\n"
        )
