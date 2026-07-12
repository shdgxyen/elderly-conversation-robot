"""Pydantic request and response schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatTextRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str = Field(min_length=1, max_length=8_000)
    user_id: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    source: Literal["voice", "touch", "system"] = "touch"
    should_remember: bool = True
    privacy_level: Literal["private", "family", "public"] = "private"

    @field_validator("text", "user_id", "display_name")
    @classmethod
    def reject_blank_strings(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value


class ChatTextResponse(BaseModel):
    reply: str
    state: str
    user_id: str


class HealthResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]
    llm_backend: str
    stt_backend: str
    tts_backend: str
    audio_backend: str
    state: str
