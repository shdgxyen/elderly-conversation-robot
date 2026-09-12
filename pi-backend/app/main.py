"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import Settings, get_settings
from app.db.session import Database
from app.device.serial_client import ESP32SerialClient
from app.llm.chat_client import ChatClient, MockLLM
from app.llm.kimi_client import KimiChatClient
from app.llm.qwen_client import QwenChatClient
from app.runtime_state import StateController, build_state_controller
from app.voice.audio_player import AudioPlayer, MockAudioPlayer
from app.voice.stt import MockSTT, SpeechToText
from app.voice.tts import MockTTS, TextToSpeech
from app.web.routes import router

logger = logging.getLogger(__name__)


def _build_llm(settings: Settings) -> ChatClient:
    """Build the configured chat backend without weakening the mock default."""

    if settings.llm_backend == "mock":
        return MockLLM()

    if settings.llm_backend == "qwen":
        qwen_key = settings.qwen_api_key
        if qwen_key is None or not qwen_key.get_secret_value().strip():
            raise ValueError(
                "ELDER_ROBOT_QWEN_API_KEY is required when "
                "ELDER_ROBOT_LLM_BACKEND=qwen"
            )
        return QwenChatClient(
            api_key=qwen_key.get_secret_value(),
            base_url=settings.qwen_base_url,
            model=settings.qwen_model,
            max_tokens=settings.qwen_max_tokens,
            enable_thinking=settings.qwen_enable_thinking,
            connect_timeout_seconds=settings.qwen_connect_timeout_seconds,
            read_timeout_seconds=settings.qwen_read_timeout_seconds,
        )

    api_key = settings.kimi_api_key
    if api_key is None or not api_key.get_secret_value().strip():
        raise ValueError(
            "ELDER_ROBOT_KIMI_API_KEY is required when "
            "ELDER_ROBOT_LLM_BACKEND=kimi"
        )
    return KimiChatClient(
        api_key=api_key.get_secret_value(),
        base_url=settings.kimi_base_url,
        model=settings.kimi_model,
        reasoning_effort=settings.kimi_reasoning_effort,
        max_completion_tokens=settings.kimi_max_completion_tokens,
        connect_timeout_seconds=settings.kimi_connect_timeout_seconds,
        read_timeout_seconds=settings.kimi_read_timeout_seconds,
    )


def _build_device_client(settings: Settings) -> ESP32SerialClient | None:
    """Create, but do not synchronously connect, the configured device client."""

    common_options = {
        "timeout": settings.device_io_timeout_seconds,
        "reconnect": True,
        "reconnect_interval": settings.device_reconnect_interval_seconds,
        "on_error": _log_device_error,
    }
    if settings.device_transport == "serial":
        return ESP32SerialClient(
            port=settings.device_serial_port,
            baudrate=settings.device_serial_baudrate,
            **common_options,
        )
    if settings.device_transport == "mock_tcp":
        return ESP32SerialClient.for_tcp_mock(
            host=settings.device_mock_tcp_host,
            port=settings.device_mock_tcp_port,
            **common_options,
        )
    return None


def _log_device_error(error: Exception) -> None:
    logger.warning(
        "Device transport error; background reconnect will continue: %s", error
    )


def create_app(
    settings: Settings | None = None,
    *,
    llm: ChatClient | None = None,
    stt: SpeechToText | None = None,
    tts: TextToSpeech | None = None,
    audio_player: AudioPlayer | None = None,
    state_controller: StateController | None = None,
) -> FastAPI:
    """Application factory with injectable mock boundaries for tests."""

    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        database = Database(
            runtime_settings.database_url,
            echo=runtime_settings.database_echo,
        )
        database.create_schema()
        application.state.database = database
        device_client = _build_device_client(runtime_settings)
        device_unbind = None
        application.state.device_client = device_client
        application.state.device_serial_client = device_client
        if device_client is not None:
            device_unbind = device_client.bind_state_machine(
                application.state.device_state_machine,
                send_state_changes=True,
            )
            # start() never waits for a connection. Missing hardware or a
            # stopped simulator is handled by the reader's reconnect loop and
            # therefore cannot prevent the HTTP API from starting.
            device_client.start()
        try:
            yield
        finally:
            close_llm = getattr(application.state.llm, "close", None)
            if callable(close_llm):
                close_llm()
            if device_client is not None:
                device_client.stop()
            if device_unbind is not None:
                device_unbind()
            database.dispose()

    application = FastAPI(
        title=runtime_settings.app_name,
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = runtime_settings
    application.state.llm = (
        llm if llm is not None else _build_llm(runtime_settings)
    )
    application.state.stt = stt or MockSTT()
    application.state.tts = tts or MockTTS()
    application.state.audio_player = audio_player or MockAudioPlayer()
    controller = state_controller or build_state_controller()
    application.state.state_controller = controller
    application.state.device_state_machine = getattr(controller, "machine", controller)
    application.state.device_client = None
    application.state.device_serial_client = None
    application.include_router(router)
    return application


def __getattr__(name: str) -> FastAPI:
    """Build the ASGI application on first attribute access.

    ``uvicorn`` imports this module through the ``app.main:app`` string, while
    the tests import only the factory helpers.  Building lazily keeps a missing
    or invalid API key from breaking test collection, and keeps ambient
    configuration out of runs that never serve a request.
    """

    if name == "app":
        application = create_app()
        globals()["app"] = application
        return application
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
