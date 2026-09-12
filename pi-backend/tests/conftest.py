from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


@pytest.fixture(autouse=True)
def isolated_settings_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's local configuration out of the test run.

    ``Settings`` reads ``.env`` and ``ELDER_ROBOT_`` variables by design.  In a
    test that would mean enabling a real LLM backend locally makes the API
    tests issue live, billable requests, so both sources are removed here.
    """

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.startswith("ELDER_ROBOT_"):
            monkeypatch.delenv(name, raising=False)


@pytest.fixture
def test_app(tmp_path):
    settings = Settings(
        environment="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
    )
    return create_app(settings)


@pytest.fixture
def client(test_app) -> Iterator[TestClient]:
    with TestClient(test_app) as test_client:
        yield test_client
