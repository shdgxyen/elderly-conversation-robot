"""SQLAlchemy engine lifecycle and FastAPI session dependency."""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

from fastapi import Request
from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.models import Base


class Database:
    """Own the engine and session factory for one application instance."""

    def __init__(self, database_url: str, *, echo: bool = False) -> None:
        self.database_url = database_url
        self._ensure_sqlite_parent_exists(database_url)

        engine_kwargs: dict[str, object] = {"echo": echo, "pool_pre_ping": True}
        if database_url.startswith("sqlite"):
            engine_kwargs["connect_args"] = {"check_same_thread": False}
            if database_url in {"sqlite://", "sqlite:///:memory:"}:
                engine_kwargs["poolclass"] = StaticPool

        self.engine: Engine = create_engine(database_url, **engine_kwargs)
        if database_url.startswith("sqlite"):
            event.listen(self.engine, "connect", self._enable_sqlite_foreign_keys)

        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )

    @staticmethod
    def _ensure_sqlite_parent_exists(database_url: str) -> None:
        url = make_url(database_url)
        if url.drivername.startswith("sqlite") and url.database not in {
            None,
            "",
            ":memory:",
        }:
            Path(url.database).expanduser().parent.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _enable_sqlite_foreign_keys(dbapi_connection: object, _: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)

    def dispose(self) -> None:
        self.engine.dispose()


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield one request-scoped session and always close it."""

    database: Database = request.app.state.database
    with database.session_factory() as session:
        yield session
