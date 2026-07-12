"""Resilient JSON Lines client for a USB/UART-connected ESP32."""

from __future__ import annotations

import asyncio
import inspect
import socket
import threading
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from .device_state import DeviceStateMachine
from .protocol import (
    MAX_JSON_PAYLOAD_BYTES,
    Esp32ToPiMessage,
    EventMessage,
    HeartbeatMessage,
    PiToEsp32Message,
    PrivacyMessage,
    ProtocolError,
    StateMessage,
    TouchMessage,
    parse_esp32_message,
    serialize_pi_message,
)


@runtime_checkable
class SerialTransport(Protocol):
    """Small pyserial-compatible surface used for dependency injection."""

    def readline(self, size: int = -1) -> bytes: ...

    def write(self, data: bytes) -> int | None: ...

    def close(self) -> None: ...


class SerialClientError(RuntimeError):
    """Base class for serial lifecycle/I/O errors."""


class SerialDisconnectedError(SerialClientError):
    """An operation requires an open transport."""


class SerialWriteError(SerialClientError):
    """The transport could not write a complete JSON line."""


class SerialLineTooLongError(SerialClientError):
    """An incoming record exceeded the configured safety limit."""


class SocketTransport:
    """pyserial-like TCP transport for ``tools/mock_esp32.py``.

    ``readline`` intentionally returns whatever bytes are available per socket
    receive/timeout.  ``ESP32SerialClient`` owns JSONL reassembly, exactly as it
    does for timeout-delimited pyserial reads.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        *,
        timeout: float = 1.0,
        connect_timeout: float = 3.0,
    ) -> None:
        if not host:
            raise ValueError("host is required")
        if not 1 <= port <= 65535:
            raise ValueError("port must be in the range 1..65535")
        if timeout < 0 or connect_timeout <= 0:
            raise ValueError("socket timeouts are invalid")
        self.host = host
        self.port = port
        self.timeout = timeout
        self.connect_timeout = connect_timeout
        self._socket: socket.socket | None = None
        self._lock = threading.RLock()
        self.open()

    @property
    def is_open(self) -> bool:
        with self._lock:
            return self._socket is not None

    def open(self) -> None:
        with self._lock:
            if self._socket is not None:
                return
            connection = socket.create_connection(
                (self.host, self.port), timeout=self.connect_timeout
            )
            connection.settimeout(self.timeout)
            self._socket = connection

    def readline(self, size: int = -1) -> bytes:
        with self._lock:
            connection = self._socket
        if connection is None:
            return b""
        receive_size = 4096 if size is None or size < 1 else size
        try:
            data = connection.recv(receive_size)
        except socket.timeout:
            return b""
        except OSError:
            self.close()
            raise
        if not data:
            self.close()
        return data

    def write(self, data: bytes) -> int:
        with self._lock:
            connection = self._socket
        if connection is None:
            raise SerialDisconnectedError("TCP mock transport is closed")
        try:
            return connection.send(data)
        except OSError:
            self.close()
            raise

    def flush(self) -> None:
        return None

    def close(self) -> None:
        with self._lock:
            connection = self._socket
            self._socket = None
        if connection is not None:
            try:
                connection.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            connection.close()


MessageHandler = Callable[[Esp32ToPiMessage], Any | Awaitable[Any]]
ErrorHandler = Callable[[Exception], Any | Awaitable[Any]]
ConnectHandler = Callable[[], Any | Awaitable[Any]]
DisconnectHandler = Callable[[Exception | None], Any | Awaitable[Any]]
TransportFactory = Callable[[], SerialTransport]


def _transport_is_open(transport: SerialTransport | None) -> bool:
    if transport is None:
        return False
    return bool(getattr(transport, "is_open", True))


class ESP32SerialClient:
    """Background serial reader with callbacks and optional reconnect.

    Pass ``transport`` (or ``transport_factory``) in tests to avoid hardware and
    pyserial.  When neither is supplied, ``port`` is opened lazily with pyserial.
    """

    def __init__(
        self,
        port: str | None = None,
        *,
        baudrate: int = 115_200,
        timeout: float = 1.0,
        reconnect: bool = True,
        reconnect_interval: float = 1.0,
        max_line_bytes: int = MAX_JSON_PAYLOAD_BYTES,
        transport: SerialTransport | None = None,
        transport_factory: TransportFactory | None = None,
        callback_loop: asyncio.AbstractEventLoop | None = None,
        on_message: MessageHandler | None = None,
        on_error: ErrorHandler | None = None,
        on_connect: ConnectHandler | None = None,
        on_disconnect: DisconnectHandler | None = None,
    ) -> None:
        if transport is not None and transport_factory is not None:
            raise ValueError("pass transport or transport_factory, not both")
        if baudrate <= 0:
            raise ValueError("baudrate must be positive")
        if timeout < 0:
            raise ValueError("timeout cannot be negative")
        if reconnect_interval < 0:
            raise ValueError("reconnect_interval cannot be negative")
        if max_line_bytes < 1:
            raise ValueError("max_line_bytes must be positive")

        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self.reconnect = reconnect
        self.reconnect_interval = reconnect_interval
        self.max_line_bytes = max_line_bytes
        self._transport = transport
        self._injected_transport = transport
        self._transport_factory = transport_factory
        self._callback_loop = callback_loop
        self._connection_lock = threading.RLock()
        self._read_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._handlers_lock = threading.RLock()
        self._stop_event = threading.Event()
        self._connected_event = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._receive_buffer = bytearray()
        self._discard_until_lf = False
        self._message_handlers: list[MessageHandler] = []
        self._error_handlers: list[ErrorHandler] = []
        self._connect_handlers: list[ConnectHandler] = []
        self._disconnect_handlers: list[DisconnectHandler] = []
        self._state_unsubscribe: Callable[[], None] | None = None

        if _transport_is_open(transport):
            self._connected_event.set()
        if on_message is not None:
            self.add_message_handler(on_message)
        if on_error is not None:
            self.add_error_handler(on_error)
        if on_connect is not None:
            self.add_connect_handler(on_connect)
        if on_disconnect is not None:
            self.add_disconnect_handler(on_disconnect)

    @classmethod
    def for_tcp_mock(
        cls,
        host: str = "127.0.0.1",
        port: int = 8765,
        **kwargs: Any,
    ) -> "ESP32SerialClient":
        """Create a reconnectable client for ``tools/mock_esp32.py``."""

        timeout = float(kwargs.get("timeout", 1.0))
        return cls(
            transport_factory=lambda: SocketTransport(
                host=host,
                port=port,
                timeout=timeout,
            ),
            **kwargs,
        )

    @property
    def is_connected(self) -> bool:
        return self._connected_event.is_set() and _transport_is_open(self._transport)

    @property
    def is_running(self) -> bool:
        thread = self._reader_thread
        return bool(thread and thread.is_alive())

    @property
    def transport(self) -> SerialTransport | None:
        with self._connection_lock:
            return self._transport

    def add_message_handler(self, handler: MessageHandler) -> Callable[[], None]:
        return self._add_handler(self._message_handlers, handler)

    on_message = add_message_handler

    def add_error_handler(self, handler: ErrorHandler) -> Callable[[], None]:
        return self._add_handler(self._error_handlers, handler)

    on_error = add_error_handler

    def add_connect_handler(self, handler: ConnectHandler) -> Callable[[], None]:
        return self._add_handler(self._connect_handlers, handler)

    on_connect = add_connect_handler

    def add_disconnect_handler(self, handler: DisconnectHandler) -> Callable[[], None]:
        return self._add_handler(self._disconnect_handlers, handler)

    on_disconnect = add_disconnect_handler

    def connect(self) -> None:
        """Open the configured transport; safe to call more than once."""

        with self._connection_lock:
            if self.is_connected:
                return
            transport = self._transport
            if transport is not None and not _transport_is_open(transport):
                open_method = getattr(transport, "open", None)
                if callable(open_method):
                    open_method()
            if transport is None or not _transport_is_open(transport):
                transport = self._create_transport()
                self._transport = transport
            if not _transport_is_open(transport):
                raise SerialDisconnectedError("serial transport did not open")
            self._connected_event.set()

        self._emit_handlers(self._connect_handlers)

    def disconnect(self, error: Exception | None = None) -> None:
        """Close the transport and notify disconnect listeners once."""

        with self._connection_lock:
            transport = self._transport
            was_connected = self._connected_event.is_set() or _transport_is_open(
                transport
            )
            self._connected_event.clear()
            if transport is not None:
                try:
                    transport.close()
                except Exception as close_error:
                    self._emit_error(close_error)
            # Factories and pyserial produce a fresh object on reconnect.  A
            # directly injected fake remains available and may implement open().
            if self._injected_transport is None:
                self._transport = None
        with self._read_lock:
            self._receive_buffer.clear()
            self._discard_until_lf = False
        if was_connected:
            self._emit_handlers(self._disconnect_handlers, error)

    close = disconnect

    def start(self) -> None:
        """Start one daemon reader thread."""

        with self._connection_lock:
            if self.is_running:
                return
            self._stop_event.clear()
            self._reader_thread = threading.Thread(
                target=self._reader_loop,
                name="esp32-serial-reader",
                daemon=True,
            )
            self._reader_thread.start()

    def stop(self, *, close_transport: bool = True, join_timeout: float = 3.0) -> None:
        self._stop_event.set()
        thread = self._reader_thread
        if thread and thread is not threading.current_thread():
            thread.join(join_timeout)
        if close_transport:
            self.disconnect()

    def wait_connected(self, timeout: float | None = None) -> bool:
        return self._connected_event.wait(timeout)

    def read_once(self) -> Esp32ToPiMessage | None:
        """Read, validate, and dispatch one incoming line.

        ``None`` means a normal serial timeout.  Protocol and I/O failures are
        raised to make deterministic unit tests straightforward.
        """

        with self._read_lock:
            line = self._pop_complete_line_unlocked()
            if line is None:
                with self._connection_lock:
                    transport = self._transport
                    if not self.is_connected or transport is None:
                        raise SerialDisconnectedError(
                            "serial transport is not connected"
                        )
                try:
                    try:
                        # payload + optional CRLF + one byte to detect overflow
                        chunk = transport.readline(self.max_line_bytes + 3)
                    except TypeError:
                        # A few lightweight test/file transports expose
                        # readline() without pyserial's optional size argument.
                        chunk = transport.readline()
                except Exception as exc:
                    raise SerialDisconnectedError(f"serial read failed: {exc}") from exc
                if not chunk:
                    if not _transport_is_open(transport):
                        raise SerialDisconnectedError(
                            "serial transport closed while reading"
                        )
                    return None
                if isinstance(chunk, str):
                    try:
                        chunk_bytes = chunk.encode("utf-8", errors="strict")
                    except UnicodeEncodeError as exc:
                        raise ProtocolError(
                            "serial chunk is not valid Unicode"
                        ) from exc
                elif isinstance(chunk, (bytes, bytearray, memoryview)):
                    chunk_bytes = bytes(chunk)
                else:
                    raise SerialClientError(
                        "transport.readline() must return bytes or str"
                    )
                line = self._buffer_chunk_unlocked(chunk_bytes)
                if line is None:
                    return None

        message = parse_esp32_message(line)
        self._emit_handlers(self._message_handlers, message)
        return message

    def send(self, message: PiToEsp32Message) -> None:
        """Atomically write one validated Pi-to-ESP32 JSON line."""

        payload = serialize_pi_message(message)
        with self._write_lock:
            with self._connection_lock:
                transport = self._transport
                if not self.is_connected or transport is None:
                    raise SerialDisconnectedError("serial transport is not connected")
            offset = 0
            try:
                while offset < len(payload):
                    written = transport.write(payload[offset:])
                    if written is None:
                        written = len(payload) - offset
                    if type(written) is not int or written <= 0:
                        raise SerialWriteError(
                            "serial transport made no write progress"
                        )
                    offset += written
                flush = getattr(transport, "flush", None)
                if callable(flush):
                    flush()
            except SerialWriteError:
                raise
            except Exception as exc:
                raise SerialWriteError(f"serial write failed: {exc}") from exc

    write_message = send

    def send_state(self, state: str) -> None:
        self.send(StateMessage(state=state))

    async def async_send(self, message: PiToEsp32Message) -> None:
        await asyncio.to_thread(self.send, message)

    asend = async_send

    async def async_read_once(self) -> Esp32ToPiMessage | None:
        return await asyncio.to_thread(self.read_once)

    aread_once = async_read_once

    def bind_state_machine(
        self,
        state_machine: DeviceStateMachine,
        *,
        send_state_changes: bool = False,
    ) -> Callable[[], None]:
        """Apply ESP32 events/privacy/heartbeats to a state machine.

        Touch messages are intentionally surfaced to normal message callbacks
        without assigning product behavior here.
        """

        if self._state_unsubscribe is not None:
            self._state_unsubscribe()

        def apply_message(message: Esp32ToPiMessage) -> None:
            if isinstance(message, EventMessage):
                state_machine.handle_event(message.event)
            elif isinstance(message, PrivacyMessage):
                state_machine.set_privacy(
                    mic_muted=message.mic_muted,
                    camera_blocked=message.camera_blocked,
                    reason="ESP32 physical privacy event",
                )
            elif isinstance(message, HeartbeatMessage):
                state_machine.record_heartbeat(message.uptime_ms)
            elif isinstance(message, TouchMessage):
                return

        unsubscribe_message = self.add_message_handler(apply_message)
        unsubscribe_state: Callable[[], None] | None = None
        unsubscribe_connect: Callable[[], None] | None = None
        if send_state_changes:

            def publish_current_state() -> None:
                if self.is_connected:
                    self.send(StateMessage(state=state_machine.state))

            def publish_state(change: Any) -> None:
                del change
                publish_current_state()

            unsubscribe_state = state_machine.add_listener(publish_state)
            unsubscribe_connect = self.add_connect_handler(publish_current_state)
            # An injected/open transport may already be connected before bind.
            publish_current_state()

        def unbind() -> None:
            unsubscribe_message()
            if unsubscribe_state is not None:
                unsubscribe_state()
            if unsubscribe_connect is not None:
                unsubscribe_connect()
            if self._state_unsubscribe is unbind:
                self._state_unsubscribe = None

        self._state_unsubscribe = unbind
        return unbind

    def __enter__(self) -> "ESP32SerialClient":
        self.connect()
        self.start()
        return self

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        self.stop()

    def _create_transport(self) -> SerialTransport:
        if self._transport_factory is not None:
            return self._transport_factory()
        if not self.port:
            raise SerialDisconnectedError(
                "serial port is required when no transport/factory is injected"
            )
        try:
            import serial  # type: ignore[import-not-found]
        except ImportError as exc:
            raise SerialClientError(
                "pyserial is required for hardware serial; install the backend dependencies"
            ) from exc
        try:
            return serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                timeout=self.timeout,
                write_timeout=self.timeout,
            )
        except Exception as exc:
            raise SerialDisconnectedError(
                f"could not open serial port {self.port!r}: {exc}"
            ) from exc

    def _reader_loop(self) -> None:
        while not self._stop_event.is_set():
            if not self.is_connected:
                try:
                    self.connect()
                except Exception as exc:
                    self._emit_error(exc)
                    if not self.reconnect:
                        return
                    self._stop_event.wait(self.reconnect_interval)
                    continue
            try:
                message = self.read_once()
                if message is None:
                    # Protect against injected non-blocking transports spinning.
                    self._stop_event.wait(min(max(self.timeout, 0.01), 0.05))
            except (ProtocolError, SerialLineTooLongError) as exc:
                # A bad line is isolated; the next line may still be valid.
                self._emit_error(exc)
            except Exception as exc:
                self._emit_error(exc)
                self.disconnect(exc)
                if not self.reconnect:
                    return
                self._stop_event.wait(self.reconnect_interval)

    def _buffer_chunk_unlocked(self, chunk: bytes) -> bytes | None:
        """Append one timeout-delimited chunk and return a complete LF record.

        When an unterminated payload grows past the shared limit, bytes are
        discarded until the next LF so one corrupt record cannot poison all
        subsequent serial traffic.
        """

        if self._discard_until_lf:
            separator = chunk.find(b"\n")
            if separator < 0:
                return None
            self._discard_until_lf = False
            chunk = chunk[separator + 1 :]
            if not chunk:
                return None

        self._receive_buffer.extend(chunk)
        line = self._pop_complete_line_unlocked()
        if line is not None:
            return line

        payload_length = len(self._receive_buffer)
        if self._receive_buffer.endswith(b"\r"):
            payload_length -= 1
        if payload_length > self.max_line_bytes:
            self._receive_buffer.clear()
            self._discard_until_lf = True
            raise SerialLineTooLongError(
                f"incoming JSON payload exceeds {self.max_line_bytes} bytes; "
                "discarding until LF"
            )
        return None

    def _pop_complete_line_unlocked(self) -> bytes | None:
        separator = self._receive_buffer.find(b"\n")
        if separator < 0:
            return None
        line = bytes(self._receive_buffer[: separator + 1])
        del self._receive_buffer[: separator + 1]
        payload = line[:-1]
        if payload.endswith(b"\r"):
            payload = payload[:-1]
        if len(payload) > self.max_line_bytes:
            raise SerialLineTooLongError(
                f"incoming JSON payload exceeds {self.max_line_bytes} bytes"
            )
        return line

    def _add_handler(self, collection: list[Any], handler: Any) -> Callable[[], None]:
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._handlers_lock:
            if handler not in collection:
                collection.append(handler)

        def unsubscribe() -> None:
            with self._handlers_lock:
                try:
                    collection.remove(handler)
                except ValueError:
                    pass

        return unsubscribe

    def _emit_error(self, error: Exception) -> None:
        self._emit_handlers(self._error_handlers, error, suppress_errors=True)

    def _emit_handlers(
        self,
        collection: list[Any],
        *args: Any,
        suppress_errors: bool = False,
    ) -> None:
        with self._handlers_lock:
            handlers = tuple(collection)
        for handler in handlers:
            try:
                result = handler(*args)
                if inspect.isawaitable(result):
                    self._schedule_awaitable(result)
            except Exception as exc:
                if not suppress_errors:
                    self._emit_error(exc)

    def _schedule_awaitable(self, awaitable: Awaitable[Any]) -> None:
        loop = self._callback_loop
        if loop is not None and loop.is_running():
            asyncio.run_coroutine_threadsafe(awaitable, loop)
            return
        try:
            running_loop = asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(awaitable)
        else:
            running_loop.create_task(awaitable)


SerialClient = ESP32SerialClient


__all__ = [
    "ESP32SerialClient",
    "SerialClient",
    "SerialClientError",
    "SerialDisconnectedError",
    "SerialLineTooLongError",
    "SerialTransport",
    "SerialWriteError",
    "SocketTransport",
]
