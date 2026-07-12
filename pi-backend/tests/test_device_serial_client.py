from __future__ import annotations

import socket
import threading
from collections import deque

import pytest

from app.device import DeviceState, DeviceStateMachine
from app.device.protocol import EventMessage, HeartbeatMessage, StateMessage
from app.device.serial_client import (
    ESP32SerialClient,
    SerialDisconnectedError,
    SerialLineTooLongError,
)


class FakeTransport:
    def __init__(
        self, lines: list[bytes] | None = None, *, partial_writes: bool = False
    ):
        self.lines = deque(lines or [])
        self.writes = bytearray()
        self.is_open = True
        self.partial_writes = partial_writes
        self.flushed = False

    def readline(self, size: int = -1) -> bytes:
        if not self.lines:
            return b""
        line = self.lines.popleft()
        return line if size < 0 else line[:size]

    def write(self, data: bytes) -> int:
        length = min(3, len(data)) if self.partial_writes else len(data)
        self.writes.extend(data[:length])
        return length

    def flush(self) -> None:
        self.flushed = True

    def close(self) -> None:
        self.is_open = False


def test_injected_transport_reads_dispatches_and_writes_complete_lines() -> None:
    transport = FakeTransport(
        [b'{"type":"event","event":"WAKE_BUTTON_PRESSED"}\n'],
        partial_writes=True,
    )
    received = []
    client = ESP32SerialClient(transport=transport, on_message=received.append)

    message = client.read_once()
    client.send(StateMessage(state=DeviceState.LISTENING))

    assert message == EventMessage(event="WAKE_BUTTON_PRESSED")
    assert received == [message]
    assert bytes(transport.writes) == b'{"type":"state","state":"LISTENING"}\n'
    assert transport.flushed is True


def test_client_binds_events_privacy_and_heartbeat_to_state_machine() -> None:
    transport = FakeTransport(
        [
            b'{"type":"event","event":"WAKE_BUTTON_PRESSED"}\n',
            b'{"type":"privacy","mic_muted":true}\n',
            b'{"type":"heartbeat","uptime_ms":999}\n',
        ]
    )
    machine = DeviceStateMachine(DeviceState.IDLE)
    client = ESP32SerialClient(transport=transport)
    client.bind_state_machine(machine)

    assert isinstance(client.read_once(), EventMessage)
    assert machine.state is DeviceState.LISTENING
    client.read_once()
    assert machine.state is DeviceState.PRIVACY_MIC_OFF
    assert machine.mic_muted is True
    assert client.read_once() == HeartbeatMessage(uptime_ms=999)
    assert machine.last_heartbeat_uptime_ms == 999


def test_disconnected_operations_fail_cleanly() -> None:
    transport = FakeTransport()
    client = ESP32SerialClient(transport=transport)
    client.disconnect()

    with pytest.raises(SerialDisconnectedError):
        client.read_once()
    with pytest.raises(SerialDisconnectedError):
        client.send(StateMessage(state=DeviceState.IDLE))


def test_timeout_delimited_partial_chunks_are_buffered_until_lf() -> None:
    transport = FakeTransport(
        [
            b'{"type":"heart',
            b'beat","uptime_ms":12}',
            b"\n",
        ]
    )
    client = ESP32SerialClient(transport=transport)

    assert client.read_once() is None
    assert client.read_once() is None
    assert client.read_once() == HeartbeatMessage(uptime_ms=12)


def test_oversized_partial_record_discards_until_lf_then_resynchronizes() -> None:
    valid = b'{"type":"heartbeat","uptime_ms":7}\n'
    transport = FakeTransport([b"x" * 65, b"discard-me\n" + valid])
    client = ESP32SerialClient(transport=transport, max_line_bytes=64)

    with pytest.raises(SerialLineTooLongError, match="discarding until LF"):
        client.read_once()

    # The corrupt record's remaining bytes are dropped through its LF, then a
    # valid record in the same subsequent chunk is processed normally.
    assert client.read_once() == HeartbeatMessage(uptime_ms=7)


def test_tcp_mock_factory_exchanges_the_same_json_lines() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    port = server.getsockname()[1]
    received: list[bytes] = []

    def mock_peer() -> None:
        connection, _ = server.accept()
        with connection:
            connection.sendall(b'{"type":"heartbeat","uptime_ms":55}\n')
            received.append(connection.recv(256))
        server.close()

    peer_thread = threading.Thread(target=mock_peer, daemon=True)
    peer_thread.start()
    client = ESP32SerialClient.for_tcp_mock(
        port=port,
        reconnect=False,
        timeout=0.2,
    )
    try:
        client.connect()
        assert client.read_once() == HeartbeatMessage(uptime_ms=55)
        client.send(StateMessage(state=DeviceState.IDLE))
    finally:
        client.disconnect()
        peer_thread.join(timeout=1)

    assert received == [b'{"type":"state","state":"IDLE"}\n']


def test_bound_state_is_sent_immediately_on_first_connect_and_reconnect() -> None:
    first = FakeTransport()
    second = FakeTransport()
    transports = iter((first, second))
    machine = DeviceStateMachine(DeviceState.IDLE)
    client = ESP32SerialClient(
        transport_factory=lambda: next(transports),
        reconnect=False,
    )
    client.bind_state_machine(machine, send_state_changes=True)

    client.connect()
    assert bytes(first.writes) == b'{"type":"state","state":"IDLE"}\n'
    client.disconnect()

    machine.transition(DeviceState.THINKING)
    client.connect()
    assert bytes(second.writes) == b'{"type":"state","state":"THINKING"}\n'
    client.disconnect()
