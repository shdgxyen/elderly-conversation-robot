"""Run the backend with host/port/log settings loaded from ``.env``."""

from __future__ import annotations

import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
        reload=settings.environment.lower() == "development",
    )


if __name__ == "__main__":
    main()
