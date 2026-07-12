"""Text-to-speech interface and mock implementation."""

from __future__ import annotations

from typing import Protocol


class TextToSpeech(Protocol):
    backend_name: str

    def synthesize(self, text: str) -> bytes:
        """Synthesize a complete mock or real audio buffer."""


class MockTTS:
    backend_name = "mock"

    def synthesize(self, text: str) -> bytes:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text must not be blank")
        # This is deliberately not a real audio format.  The phase-one player
        # only verifies the boundary; no original or generated audio is saved.
        return b"MOCK_AUDIO:" + clean_text.encode("utf-8")
