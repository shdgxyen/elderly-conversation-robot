from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import select

from app.config import Settings
from app.db.models import ConversationTurn, User
from app.main import create_app


class FailingLLM:
    backend_name = "failing-mock"

    def generate_reply(self, text: str, *, display_name: str | None = None) -> str:
        del text, display_name
        raise RuntimeError("simulated model outage")


def test_llm_failure_does_not_leave_partial_database_rows(tmp_path) -> None:
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'failure.db'}",
    )
    app = create_app(settings, llm=FailingLLM())

    with TestClient(app) as client:
        response = client.post(
            "/chat/text",
            json={
                "user_id": "rollback-user",
                "display_name": "测试用户",
                "text": "这次调用会失败",
            },
        )

        assert response.status_code == 502
        assert client.get("/device/state").json()["state"] == "API_ERROR"
        with app.state.database.session_factory() as session:
            assert session.scalar(select(User)) is None
            assert session.scalar(select(ConversationTurn)) is None
