"""Synchronous Kimi chat client for the Moonshot OpenAI-compatible API."""

from __future__ import annotations

from typing import Any

import httpx

from app.llm.prompts import COMPANION_SYSTEM_PROMPT


class KimiAPIError(RuntimeError):
    """Raised when Kimi cannot return a usable assistant reply."""


class KimiChatClient:
    """Generate one companion reply through Kimi's chat-completions API."""

    backend_name = "kimi"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://api.moonshot.cn/v1",
        model: str = "kimi-k3",
        reasoning_effort: str = "low",
        max_completion_tokens: int = 2048,
        connect_timeout_seconds: float = 5.0,
        read_timeout_seconds: float = 60.0,
        http_client: httpx.Client | None = None,
    ) -> None:
        clean_api_key = api_key.strip()
        if not clean_api_key:
            raise ValueError("Kimi API key must not be blank")
        clean_base_url = base_url.strip().rstrip("/")
        if not clean_base_url:
            raise ValueError("Kimi base URL must not be blank")
        if not model.strip():
            raise ValueError("Kimi model must not be blank")
        if not reasoning_effort.strip():
            raise ValueError("Kimi reasoning effort must not be blank")
        if max_completion_tokens <= 0:
            raise ValueError("Kimi max completion tokens must be positive")

        self._api_key = clean_api_key
        self._endpoint = f"{clean_base_url}/chat/completions"
        self._model = model.strip()
        self._reasoning_effort = reasoning_effort.strip()
        self._max_completion_tokens = max_completion_tokens
        self._owns_http_client = http_client is None
        self._http_client = http_client or httpx.Client(
            timeout=httpx.Timeout(
                read_timeout_seconds,
                connect=connect_timeout_seconds,
                write=read_timeout_seconds,
                pool=connect_timeout_seconds,
            )
        )

    def generate_reply(self, text: str, *, display_name: str | None = None) -> str:
        clean_text = text.strip()
        if not clean_text:
            raise ValueError("text must not be blank")

        system_prompt = COMPANION_SYSTEM_PROMPT
        clean_display_name = (display_name or "").strip()
        if clean_display_name and clean_display_name != "访客":
            system_prompt += (
                f"\n当前使用者的称呼是“{clean_display_name}”，请自然地使用这个称呼。"
            )

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": clean_text},
            ],
            "reasoning_effort": self._reasoning_effort,
            "max_completion_tokens": self._max_completion_tokens,
        }
        try:
            response = self._http_client.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise KimiAPIError(
                f"Kimi request failed with HTTP {exc.response.status_code}"
            ) from exc
        except httpx.RequestError as exc:
            raise KimiAPIError("Kimi request failed") from exc

        try:
            response_body = response.json()
            reply = response_body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise KimiAPIError("Kimi returned an invalid response") from exc

        if not isinstance(reply, str) or not reply.strip():
            raise KimiAPIError("Kimi returned an empty reply")
        return reply.strip()

    def close(self) -> None:
        """Close the internally created HTTP client."""

        if self._owns_http_client:
            self._http_client.close()
