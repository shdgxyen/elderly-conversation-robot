from __future__ import annotations

import json

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.llm.chat_client import MockLLM
from app.llm.kimi_client import KimiAPIError, KimiChatClient
from app.main import _build_llm


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_kimi_client_sends_expected_single_turn_without_sampling_parameters() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.moonshot.cn/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-token"
        payload = json.loads(request.content)
        assert payload["model"] == "kimi-k3"
        assert payload["reasoning_effort"] == "low"
        assert payload["max_completion_tokens"] == 2048
        assert payload["messages"][0]["role"] == "system"
        assert "面向老人" in payload["messages"][0]["content"]
        assert "张奶奶" in payload["messages"][0]["content"]
        assert payload["messages"][1] == {
            "role": "user",
            "content": "今天天气怎么样？",
        }
        assert "temperature" not in payload
        assert "top_p" not in payload
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": " 今天很适合散步。 "}}]},
        )

    client = KimiChatClient(
        api_key="test-token",
        http_client=_mock_client(handler),
    )

    assert (
        client.generate_reply("今天天气怎么样？", display_name="张奶奶")
        == "今天很适合散步。"
    )


@pytest.mark.parametrize(
    ("response", "message"),
    [
        (httpx.Response(401), "HTTP 401"),
        (httpx.Response(200, text="not-json"), "invalid response"),
        (httpx.Response(200, json={"choices": []}), "invalid response"),
        (
            httpx.Response(
                200,
                json={"choices": [{"message": {"content": "   "}}]},
            ),
            "empty reply",
        ),
    ],
)
def test_kimi_client_rejects_failed_or_unusable_responses(
    response: httpx.Response,
    message: str,
) -> None:
    client = KimiChatClient(
        api_key="test-token",
        http_client=_mock_client(lambda request: response),
    )

    with pytest.raises(KimiAPIError, match=message):
        client.generate_reply("你好")


def test_kimi_client_wraps_transport_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("simulated timeout", request=request)

    client = KimiChatClient(
        api_key="test-token",
        http_client=_mock_client(handler),
    )

    with pytest.raises(KimiAPIError, match="request failed"):
        client.generate_reply("你好")


def test_llm_factory_keeps_mock_default() -> None:
    assert isinstance(_build_llm(Settings()), MockLLM)


def test_llm_factory_requires_kimi_key_without_exposing_a_value() -> None:
    settings = Settings(llm_backend="kimi", kimi_api_key=None)

    with pytest.raises(ValueError, match="ELDER_ROBOT_KIMI_API_KEY is required"):
        _build_llm(settings)


def test_llm_factory_builds_kimi_from_secret_configuration() -> None:
    settings = Settings(
        llm_backend="kimi",
        kimi_api_key=SecretStr("test-token"),
    )

    client = _build_llm(settings)
    try:
        assert isinstance(client, KimiChatClient)
        assert client.backend_name == "kimi"
    finally:
        client.close()  # type: ignore[attr-defined]
