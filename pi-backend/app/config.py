"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings.

    All environment variables use the ``ELDER_ROBOT_`` prefix.  Keeping the
    defaults in mock mode makes a fresh checkout runnable without API keys or
    attached hardware.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="ELDER_ROBOT_",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = "Elder Companion Robot API"
    environment: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8000, ge=1, le=65535)
    log_level: str = "INFO"

    database_url: str = "sqlite:///./data/elder_companion.db"
    database_echo: bool = False

    llm_backend: Literal["mock", "kimi", "qwen"] = "mock"
    kimi_api_key: SecretStr | None = None
    kimi_base_url: str = "https://api.moonshot.cn/v1"
    kimi_model: str = "kimi-k3"
    kimi_reasoning_effort: Literal["low", "high", "max"] = "low"
    kimi_max_completion_tokens: int = Field(default=2048, ge=256, le=8192)
    kimi_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    kimi_read_timeout_seconds: float = Field(default=60.0, gt=0)
    qwen_api_key: SecretStr | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    qwen_max_tokens: int = Field(default=2048, ge=256, le=8192)
    # Leave unset to use the model default; Qwen3 needs false when not streaming.
    qwen_enable_thinking: bool | None = None
    qwen_connect_timeout_seconds: float = Field(default=5.0, gt=0)
    qwen_read_timeout_seconds: float = Field(default=60.0, gt=0)
    stt_backend: str = "mock"
    tts_backend: str = "mock"
    audio_backend: str = "mock"

    # Device communication is opt-in so the API remains hardware-free by
    # default. Both real serial and the TCP simulator use the same JSONL
    # protocol and reconnect in a background reader thread.
    device_transport: Literal["none", "serial", "mock_tcp"] = "none"
    device_serial_port: str | None = None
    device_serial_baudrate: int = Field(default=115_200, gt=0)
    device_io_timeout_seconds: float = Field(default=1.0, gt=0)
    device_reconnect_interval_seconds: float = Field(default=1.0, ge=0)
    device_mock_tcp_host: str = Field(default="127.0.0.1", min_length=1)
    device_mock_tcp_port: int = Field(default=8765, ge=1, le=65535)

    default_user_id: str = "default-user"
    default_display_name: str = "访客"


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide settings instance."""

    return Settings()
