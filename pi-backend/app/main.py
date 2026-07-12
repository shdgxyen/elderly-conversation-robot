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
from app.runtime_state import StateController, build_state_controller
from app.voice.audio_player import AudioPlayer, MockAudioPlayer
from app.voice.stt import MockSTT, SpeechToText
from app.voice.tts import MockTTS, TextToSpeech
from app.web.routes import router

logger = logging.getLogger(__name__)


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
    application.state.llm = llm or MockLLM()
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


app = create_app()
