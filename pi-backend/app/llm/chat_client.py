"""Chat model boundary and deterministic phase-one implementation."""

from __future__ import annotations

from typing import Protocol


class ChatClient(Protocol):
    backend_name: str

    def generate_reply(self, text: str, *, display_name: str | None = None) -> str:
        """Generate one assistant turn for the supplied user text."""


class MockLLM:
    """A local, deterministic model substitute suitable for tests and demos."""

    backend_name = "mock"

    def generate_reply(self, text: str, *, display_name: str | None = None) -> str:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text must not be blank")

        greeting = (
            f"{display_name}，" if display_name and display_name != "访客" else ""
        )
        return f"{greeting}我听到您说“{clean_text}”。谢谢您愿意和我聊聊。"
