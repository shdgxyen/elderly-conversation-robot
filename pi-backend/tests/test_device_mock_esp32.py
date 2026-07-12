from __future__ import annotations

import sys
from pathlib import Path

from app.device.protocol import EventMessage, parse_esp32_message


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.mock_esp32 import MockESP32  # noqa: E402


def test_mock_esp32_interactive_commands_and_pi_updates() -> None:
    output: list[str] = []
    sent: list[bytes] = []
    simulator = MockESP32(output=output.append)
    simulator.attach(sent.append)

    assert simulator.handle_command("wake") is True
    assert simulator.handle_command("mic mute") is True
    simulator.receive_line(b'{"type":"state","state":"LISTENING"}\n')
    simulator.receive_line(
        '{"type":"user","recognized":true,"display_name":"张奶奶"}\n'
    )

    assert parse_esp32_message(sent[0]) == EventMessage(event="WAKE_BUTTON_PRESSED")
    assert simulator.mic_muted is True
    assert simulator.state == "LISTENING"
    assert simulator.display_name == "张奶奶"
    assert any("树莓派 → ESP32" in line for line in output)
