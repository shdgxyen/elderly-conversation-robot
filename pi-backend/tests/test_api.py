from __future__ import annotations

from datetime import timezone

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from app.db.models import ConversationTurn, User


def test_health_and_all_phase_one_tables_exist(client: TestClient, test_app) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "database": "ok",
        "llm_backend": "mock",
        "stt_backend": "mock",
        "tts_backend": "mock",
        "audio_backend": "mock",
        "state": "IDLE",
    }
    assert set(inspect(test_app.state.database.engine).get_table_names()) == {
        "autobiography_chapters",
        "conversation_turns",
        "daily_summaries",
        "face_profiles",
        "life_events",
        "memory_facts",
        "users",
    }


def test_device_state_snapshot(client: TestClient) -> None:
    response = client.get("/device/state")

    assert response.status_code == 200
    assert response.json()["state"] == "IDLE"
    assert response.json()["mic_muted"] is False
    assert response.json()["camera_blocked"] is False


def test_text_chat_creates_user_and_atomic_turn_pair(
    client: TestClient,
    test_app,
) -> None:
    response = client.post(
        "/chat/text",
        json={
            "user_id": "grandma-zhang",
            "display_name": "张奶奶",
            "text": "今天天气真好。",
            "source": "touch",
            "privacy_level": "family",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == "grandma-zhang"
    assert body["state"] == "SPEAKING"
    assert "今天天气真好" in body["reply"]

    with test_app.state.database.session_factory() as session:
        user = session.get(User, "grandma-zhang")
        turns = list(
            session.scalars(
                select(ConversationTurn).where(
                    ConversationTurn.user_id == "grandma-zhang"
                )
            )
        )

    assert user is not None
    assert user.display_name == "张奶奶"
    assert len(turns) == 2
    assert {turn.role for turn in turns} == {"user", "assistant"}
    user_turn = next(turn for turn in turns if turn.role == "user")
    assistant_turn = next(turn for turn in turns if turn.role == "assistant")
    assert user_turn.text == "今天天气真好。"
    assert user_turn.created_at.tzinfo is timezone.utc
    assert user_turn.source == "touch"
    assert user_turn.privacy_level == "family"
    assert assistant_turn.text == body["reply"]
    assert assistant_turn.source == "system"
    assert client.get("/device/state").json()["current_user_id"] == "grandma-zhang"
    assert test_app.state.audio_player.play_count == 1
    assert test_app.state.audio_player.last_audio.startswith(b"MOCK_AUDIO:")


def test_text_chat_uses_default_user_and_accepts_second_turn(
    client: TestClient,
    test_app,
) -> None:
    first = client.post("/chat/text", json={"text": "你好"})
    second = client.post("/chat/text", json={"text": "我又来了"})

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["state"] == "SPEAKING"
    with test_app.state.database.session_factory() as session:
        assert session.get(User, "default-user") is not None
        turns = list(
            session.scalars(
                select(ConversationTurn).where(
                    ConversationTurn.user_id == "default-user"
                )
            )
        )
    assert len(turns) == 4
    assert all(turn.should_remember is False for turn in turns)


def test_blank_text_is_rejected_without_writes(client: TestClient, test_app) -> None:
    response = client.post(
        "/chat/text",
        json={"user_id": "invalid", "text": "   "},
    )

    assert response.status_code == 422
    with test_app.state.database.session_factory() as session:
        assert session.scalar(select(User).where(User.id == "invalid")) is None
        assert session.scalar(select(ConversationTurn)) is None


def test_do_not_remember_phrase_marks_both_turns(client: TestClient, test_app) -> None:
    response = client.post(
        "/chat/text",
        json={"user_id": "privacy-user", "text": "这件事不记这个"},
    )

    assert response.status_code == 200
    with test_app.state.database.session_factory() as session:
        turns = list(
            session.scalars(
                select(ConversationTurn).where(
                    ConversationTurn.user_id == "privacy-user"
                )
            )
        )
    assert len(turns) == 2
    assert all(turn.should_remember is False for turn in turns)
