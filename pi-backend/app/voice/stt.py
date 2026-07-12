"""Speech-to-text interface and mock implementation."""

from __future__ import annotations

from typing import Protocol


class SpeechToText(Protocol):
    backend_name: str

    def transcribe(self, audio: bytes) -> str:
        """Convert one complete audio buffer into text."""


class MockSTT:
    backend_name = "mock"

    def __init__(self, transcript: str = "这是一段模拟语音输入") -> None:
        self.transcript = transcript

    def transcribe(self, audio: bytes) -> str:
        if not audio:
            raise ValueError("audio must not be empty")
        return self.transcript
