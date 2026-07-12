#!/usr/bin/env python3
"""Hardware-free ESP32 simulator for the Phase 2 JSON Lines protocol.

Examples:

    # Default: listen for a backend TCP client on 127.0.0.1:8765
    python tools/mock_esp32.py

    # Connect to a backend TCP test endpoint, with no interactive prompt
    python tools/mock_esp32.py --connect 127.0.0.1:8765 --no-interactive

The TCP stream intentionally uses the exact same UTF-8 JSON Lines records as
USB serial, making it useful with a tiny socket transport in tests.
"""

from __future__ import annotations

import argparse
import shlex
import socket
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "pi-backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

try:
    from app.device.protocol import (
        DisplayMessage,
        ErrorMessage,
        EventMessage,
        FaceMessage,
        HeartbeatMessage,
        MAX_JSON_PAYLOAD_BYTES,
        PrivacyMessage,
        ProtocolError,
        SoundMessage,
        StateMessage,
        TouchMessage,
        UserMessage,
        parse_esp32_message,
        parse_pi_to_esp32_message,
        serialize_esp32_message,
    )
except ImportError as exc:  # pragma: no cover - friendly CLI dependency failure
    raise SystemExit(
        "Backend dependencies are missing. Install pi-backend/requirements.txt "
        f"before running the simulator ({exc})."
    ) from exc


DEFAULT_ADDRESS = "127.0.0.1:8765"


def _format_message(message: Any) -> str:
    if isinstance(message, StateMessage):
        return f"state → {message.state.value}"
    if isinstance(message, FaceMessage):
        return f"face → {message.emotion} (intensity={message.intensity:.2f})"
    if isinstance(message, UserMessage):
        identity = message.display_name or "访客"
        return f"user → {identity} (recognized={message.recognized})"
    if isinstance(message, ErrorMessage):
        return f"error → {message.code}: {message.message}"
    if isinstance(message, DisplayMessage):
        return f"display → brightness={message.brightness}"
    if isinstance(message, SoundMessage):
        return f"sound → {message.name}"
    return repr(message)


class MockESP32:
    """Protocol-level simulator independent of sockets and terminal I/O."""

    def __init__(self, *, output: Callable[[str], None] = print) -> None:
        self.output = output
        self.started_at = time.monotonic()
        self.state = "BOOTING"
        self.face: tuple[str, float] | None = None
        self.display_name: str | None = None
        self.brightness = 70
        self.last_error: tuple[str, str] | None = None
        self.last_sound: str | None = None
        self.mic_muted = False
        self.camera_blocked = False
        self._send_bytes: Callable[[bytes], None] | None = None
        self._lock = threading.RLock()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._send_bytes is not None

    def attach(self, sender: Callable[[bytes], None]) -> None:
        with self._lock:
            self._send_bytes = sender
        self.output("[连接] 后端已连接")

    def detach(self) -> None:
        with self._lock:
            had_sender = self._send_bytes is not None
            self._send_bytes = None
        if had_sender:
            self.output("[断开] 后端连接已断开")

    def receive_line(self, line: str | bytes) -> Any:
        """Validate and display one Pi-to-ESP32 command."""

        message = parse_pi_to_esp32_message(line)
        with self._lock:
            if isinstance(message, StateMessage):
                self.state = message.state.value
            elif isinstance(message, FaceMessage):
                self.face = (message.emotion, message.intensity)
            elif isinstance(message, UserMessage):
                self.display_name = message.display_name
            elif isinstance(message, ErrorMessage):
                self.last_error = (message.code, message.message)
            elif isinstance(message, DisplayMessage):
                self.brightness = message.brightness
            elif isinstance(message, SoundMessage):
                self.last_sound = message.name
        self.output(f"[树莓派 → ESP32] {_format_message(message)}")
        return message

    def emit(self, message: Any) -> bool:
        """Send one validated ESP32-to-Pi event if connected."""

        # Direction validation happens before touching the socket.
        payload = serialize_esp32_message(message)
        with self._lock:
            sender = self._send_bytes
            if sender is None:
                self.output("[未连接] 事件未发送")
                return False
            try:
                sender(payload)
            except OSError as exc:
                self.output(f"[发送失败] {exc}")
                self._send_bytes = None
                return False
        self.output(f"[ESP32 → 树莓派] {payload.decode('utf-8').rstrip()}")
        return True

    def emit_heartbeat(self) -> bool:
        return self.emit(HeartbeatMessage(uptime_ms=self.uptime_ms()))

    def uptime_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)

    def handle_command(self, command: str) -> bool:
        """Handle a REPL command. Return False when the simulator should quit."""

        try:
            words = shlex.split(command)
        except ValueError as exc:
            self.output(f"命令格式错误: {exc}")
            return True
        if not words:
            return True
        action = words[0].lower()
        try:
            if action in {"quit", "exit", "q"}:
                return False
            if action in {"help", "?"}:
                self.output(COMMAND_HELP)
            elif action == "wake":
                self.emit(EventMessage(event="WAKE_BUTTON_PRESSED"))
            elif action == "stop":
                self.emit(EventMessage(event="STOP_BUTTON_PRESSED"))
            elif action == "mic":
                if len(words) != 2 or words[1].lower() not in {
                    "mute",
                    "unmute",
                    "off",
                    "on",
                }:
                    raise ValueError("用法: mic mute|unmute")
                muted = words[1].lower() in {"mute", "off"}
                self.mic_muted = muted
                self.emit(PrivacyMessage(mic_muted=muted))
            elif action == "camera":
                if len(words) != 2 or words[1].lower() not in {
                    "block",
                    "unblock",
                    "close",
                    "open",
                    "off",
                    "on",
                }:
                    raise ValueError("用法: camera block|unblock")
                blocked = words[1].lower() in {"block", "close", "off"}
                self.camera_blocked = blocked
                self.emit(PrivacyMessage(camera_blocked=blocked))
            elif action == "touch":
                if len(words) == 1:
                    x, y = 212, 180
                elif len(words) == 3:
                    x, y = int(words[1]), int(words[2])
                else:
                    raise ValueError("用法: touch [x y]")
                self.emit(TouchMessage(event="SCREEN_TAPPED", x=x, y=y))
            elif action in {"heartbeat", "hb"}:
                self.emit_heartbeat()
            elif action == "status":
                self.output(self.status_text())
            elif action == "json":
                raw = command.partition(" ")[2]
                if not raw:
                    raise ValueError('用法: json {"type":...}')
                self.emit(parse_esp32_message(raw))
            else:
                raise ValueError(f"未知命令: {action}（输入 help 查看帮助）")
        except (ProtocolError, ValueError) as exc:
            self.output(f"命令失败: {exc}")
        return True

    def status_text(self) -> str:
        with self._lock:
            return (
                f"state={self.state}, connected={self.connected}, "
                f"mic_muted={self.mic_muted}, camera_blocked={self.camera_blocked}, "
                f"brightness={self.brightness}, user={self.display_name or '-'}"
            )


COMMAND_HELP = """可用命令:
  wake                    发送唤醒按钮事件
  stop                    发送停止按钮事件
  mic mute|unmute         切换麦克风物理静音
  camera block|unblock    切换摄像头滑盖
  touch [x y]             发送屏幕点击（默认 212,180）
  heartbeat               立即发送一次心跳
  json {JSON}             发送一条自定义但经过校验的 ESP32 消息
  status                  显示模拟设备状态
  help                    显示本帮助
  quit                    退出
"""


def parse_address(value: str) -> tuple[str, int]:
    host, separator, port_text = value.rpartition(":")
    if not separator or not host:
        raise argparse.ArgumentTypeError("地址格式应为 HOST:PORT")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("端口必须是整数") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("端口应在 1..65535 范围内")
    return host, port


def socket_session(
    connection: socket.socket,
    simulator: MockESP32,
    stop_event: threading.Event,
) -> None:
    connection.settimeout(0.5)
    send_lock = threading.Lock()

    def send(payload: bytes) -> None:
        with send_lock:
            connection.sendall(payload)

    simulator.attach(send)
    buffer = b""
    try:
        while not stop_event.is_set():
            try:
                chunk = connection.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                payload = line[:-1] if line.endswith(b"\r") else line
                if len(payload) > MAX_JSON_PAYLOAD_BYTES:
                    simulator.output("[协议错误] 收到超长 payload，关闭连接")
                    return
                try:
                    simulator.receive_line(line + b"\n")
                except ProtocolError as exc:
                    simulator.output(f"[协议错误] {exc}")
            if len(buffer) > MAX_JSON_PAYLOAD_BYTES:
                simulator.output("[协议错误] 收到超长 payload，关闭连接")
                break
    except OSError as exc:
        if not stop_event.is_set():
            simulator.output(f"[连接错误] {exc}")
    finally:
        simulator.detach()
        try:
            connection.close()
        except OSError:
            pass


def run_server(
    address: tuple[str, int],
    simulator: MockESP32,
    stop_event: threading.Event,
) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(address)
        server.listen(1)
        server.settimeout(0.5)
        simulator.output(f"[监听] TCP {address[0]}:{address[1]}，等待后端连接")
        while not stop_event.is_set():
            try:
                connection, peer = server.accept()
            except socket.timeout:
                continue
            simulator.output(f"[接入] {peer[0]}:{peer[1]}")
            socket_session(connection, simulator, stop_event)


def run_client(
    address: tuple[str, int],
    simulator: MockESP32,
    stop_event: threading.Event,
    retry_interval: float,
) -> None:
    while not stop_event.is_set():
        simulator.output(f"[连接] 正在连接 TCP {address[0]}:{address[1]}")
        try:
            connection = socket.create_connection(address, timeout=3.0)
        except OSError as exc:
            simulator.output(f"[连接失败] {exc}")
            stop_event.wait(retry_interval)
            continue
        socket_session(connection, simulator, stop_event)
        if not stop_event.is_set():
            stop_event.wait(retry_interval)


def heartbeat_loop(
    simulator: MockESP32,
    stop_event: threading.Event,
    interval: float,
) -> None:
    if interval <= 0:
        return
    while not stop_event.wait(interval):
        if simulator.connected:
            simulator.emit_heartbeat()


def interactive_loop(simulator: MockESP32, stop_event: threading.Event) -> None:
    simulator.output(COMMAND_HELP)
    while not stop_event.is_set():
        try:
            command = input("esp32> ")
        except (EOFError, KeyboardInterrupt):
            break
        if not simulator.handle_command(command):
            break
    stop_event.set()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ESP32 JSON Lines TCP/interactive simulator"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--listen",
        metavar="HOST:PORT",
        help=f"作为 TCP 服务端监听（默认 {DEFAULT_ADDRESS}）",
    )
    mode.add_argument(
        "--connect", metavar="HOST:PORT", help="作为 TCP 客户端连接后端测试端口"
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=5.0,
        help="自动心跳秒数；0 表示禁用（默认 5）",
    )
    parser.add_argument(
        "--retry-interval",
        type=float,
        default=1.0,
        help="客户端断线重连间隔秒数（默认 1）",
    )
    parser.add_argument(
        "--no-interactive", action="store_true", help="禁用终端交互命令"
    )
    parser.add_argument(
        "--run-seconds",
        type=float,
        default=0.0,
        help="运行指定秒数后退出；0 表示一直运行",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_argument_parser().parse_args(argv)
    if args.heartbeat_interval < 0 or args.retry_interval < 0 or args.run_seconds < 0:
        raise SystemExit("时间参数不能为负数")

    simulator = MockESP32()
    stop_event = threading.Event()
    address = parse_address(args.connect or args.listen or DEFAULT_ADDRESS)
    network_target = run_client if args.connect else run_server
    network_args: tuple[Any, ...]
    if args.connect:
        network_args = (address, simulator, stop_event, args.retry_interval)
    else:
        network_args = (address, simulator, stop_event)
    network_thread = threading.Thread(
        target=network_target,
        args=network_args,
        name="mock-esp32-network",
        daemon=True,
    )
    network_thread.start()

    heartbeat_thread = threading.Thread(
        target=heartbeat_loop,
        args=(simulator, stop_event, args.heartbeat_interval),
        name="mock-esp32-heartbeat",
        daemon=True,
    )
    heartbeat_thread.start()

    timer: threading.Timer | None = None
    if args.run_seconds:
        timer = threading.Timer(args.run_seconds, stop_event.set)
        timer.daemon = True
        timer.start()

    try:
        if args.no_interactive:
            while not stop_event.wait(0.5):
                pass
        else:
            interactive_loop(simulator, stop_event)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        simulator.detach()
        if timer is not None:
            timer.cancel()
        network_thread.join(timeout=1.5)
        heartbeat_thread.join(timeout=1.5)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
