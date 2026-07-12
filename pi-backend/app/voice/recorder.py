"""Audio capture boundary; hardware capture is intentionally deferred."""

from __future__ import annotations

from typing import Protocol


class AudioRecorder(Protocol):
    backend_name: str

    def record_once(self) -> bytes:
        """Capture one utterance and return its bytes."""


class MockAudioRecorder:
    backend_name = "mock"

    def __init__(self, audio: bytes = b"MOCK_AUDIO_INPUT") -> None:
        self.audio = audio

    def record_once(self) -> bytes:
        return self.audio
