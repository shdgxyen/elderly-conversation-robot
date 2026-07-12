from __future__ import annotations

import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from tools.mock_esp32 import MockESP32, socket_session  # noqa: E402


def _wait_until(predicate: Callable[[], bool], timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition was not met before timeout")


def test_fastapi_lifespan_exchanges_state_and_events_with_tcp_mock(tmp_path) -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    server.settimeout(2.0)
    port = server.getsockname()[1]
    stop_event = threading.Event()
    simulator = MockESP32(output=lambda _: None)

    def serve_mock() -> None:
        try:
            connection, _ = server.accept()
        except (OSError, socket.timeout):
            return
        socket_session(connection, simulator, stop_event)

    server_thread = threading.Thread(
        target=serve_mock,
        name="test-mock-esp32-server",
        daemon=True,
    )
    server_thread.start()

    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'lifecycle.db'}",
        device_transport="mock_tcp",
        device_mock_tcp_host="127.0.0.1",
        device_mock_tcp_port=port,
        device_io_timeout_seconds=0.05,
        device_reconnect_interval_seconds=0.02,
    )
    app = create_app(settings)

    try:
        with TestClient(app) as client:
            device_client = app.state.device_client
            assert device_client is not None
            _wait_until(lambda: device_client.is_connected and simulator.connected)

            response = client.post(
                "/chat/text",
                json={"user_id": "tcp-user", "text": "你好"},
            )
            assert response.status_code == 200
            _wait_until(lambda: simulator.state == "SPEAKING")

            assert simulator.emit_heartbeat() is True
            _wait_until(
                lambda: (
                    client.get("/device/state").json()["last_heartbeat_uptime_ms"]
                    is not None
                )
            )

            assert simulator.handle_command("mic mute") is True
            _wait_until(lambda: client.get("/device/state").json()["mic_muted"] is True)
            # Mic privacy blocks future LISTENING, but does not interrupt the
            # already generated spoken reply. Privacy becomes the idle visual
            # once STOP ends that active state.
            assert simulator.state == "SPEAKING"
            assert simulator.handle_command("stop") is True
            _wait_until(lambda: simulator.state == "PRIVACY_MIC_OFF")

        assert device_client.is_running is False
        assert device_client.is_connected is False
    finally:
        stop_event.set()
        try:
            server.close()
        except OSError:
            pass
        server_thread.join(timeout=2.0)

    assert server_thread.is_alive() is False


def test_unavailable_device_does_not_block_api_startup(tmp_path) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    unavailable_port = probe.getsockname()[1]
    probe.close()

    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'unavailable.db'}",
        device_transport="mock_tcp",
        device_mock_tcp_port=unavailable_port,
        device_io_timeout_seconds=0.05,
        device_reconnect_interval_seconds=0.02,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        device_client = app.state.device_client
        assert device_client is not None
        assert device_client.is_running is True

    assert device_client.is_running is False
