"""Audio playback boundary; no real device is opened in phase one."""

from __future__ import annotations

from typing import Protocol


class AudioPlayer(Protocol):
    backend_name: str

    def play(self, audio: bytes) -> None:
        """Play one complete audio buffer."""


class MockAudioPlayer:
    backend_name = "mock"

    def __init__(self) -> None:
        self.last_audio: bytes | None = None
        self.play_count = 0

    def play(self, audio: bytes) -> None:
        if not audio:
            raise ValueError("audio must not be empty")
        self.last_audio = audio
        self.play_count += 1
