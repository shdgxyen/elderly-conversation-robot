"""Phase-one health and text-chat endpoints."""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import text as sql_text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.session import get_db_session
from app.services.chat import ChatService
from app.web.schemas import ChatTextRequest, ChatTextResponse, HealthResponse

logger = logging.getLogger(__name__)
router = APIRouter()
DatabaseSession = Annotated[Session, Depends(get_db_session)]


@router.get("/health", response_model=HealthResponse, tags=["system"])
def health(request: Request, session: DatabaseSession) -> HealthResponse:
    session.execute(sql_text("SELECT 1"))
    state_controller = request.app.state.state_controller
    return HealthResponse(
        status="ok",
        database="ok",
        llm_backend=request.app.state.llm.backend_name,
        stt_backend=request.app.state.stt.backend_name,
        tts_backend=request.app.state.tts.backend_name,
        audio_backend=request.app.state.audio_player.backend_name,
        state=state_controller.current_state,
    )


@router.get("/device/state", tags=["device"])
def device_state(request: Request) -> dict[str, object]:
    """Return a serializable snapshot of the local device state machine."""

    machine = request.app.state.device_state_machine
    snapshot_method = getattr(machine, "snapshot", None)
    if not callable(snapshot_method):
        return {
            "state": request.app.state.state_controller.current_state,
            "mic_muted": False,
            "camera_blocked": False,
            "current_user_id": None,
            "last_heartbeat": None,
            "last_heartbeat_uptime_ms": None,
        }
    snapshot = snapshot_method()
    if hasattr(snapshot, "model_dump"):
        return snapshot.model_dump(mode="json")
    return dict(snapshot)


@router.post(
    "/chat/text",
    response_model=ChatTextResponse,
    status_code=status.HTTP_200_OK,
    tags=["chat"],
)
def chat_text(
    payload: ChatTextRequest,
    request: Request,
    session: DatabaseSession,
) -> ChatTextResponse:
    settings: Settings = request.app.state.settings
    user_id = payload.user_id or settings.default_user_id
    display_name = payload.display_name or settings.default_display_name
    # The implicit fallback identity is a visitor, so it is never eligible for
    # long-term memory without an explicit user selection/recognition step.
    should_remember = (
        payload.user_id is not None
        and payload.should_remember
        and "不记这个" not in payload.text
    )
    state_controller = request.app.state.state_controller
    chat_service = ChatService(request.app.state.llm)

    try:
        _transition_to_thinking(state_controller)
        result = chat_service.chat(
            session,
            user_id=user_id,
            text=payload.text,
            display_name=display_name,
            source=payload.source,
            should_remember=should_remember,
            privacy_level=payload.privacy_level,
        )
        set_current_user = getattr(
            request.app.state.device_state_machine,
            "set_current_user_id",
            None,
        )
        if callable(set_current_user):
            set_current_user(result.user_id)
        state_controller.transition_to("SPEAKING", reason="reply ready")

        # Exercise the audio boundary without implementing a real audio chain.
        audio = request.app.state.tts.synthesize(result.reply)
        request.app.state.audio_player.play(audio)
    except (SQLAlchemyError, ValueError) as exc:
        session.rollback()
        _transition_to_error(state_controller)
        logger.exception("Text chat failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to complete the conversation turn",
        ) from exc
    except Exception as exc:
        session.rollback()
        _transition_to_error(state_controller)
        logger.exception("Unexpected text chat failure")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Conversation service is unavailable",
        ) from exc

    return ChatTextResponse(
        reply=result.reply,
        state=state_controller.current_state,
        user_id=result.user_id,
    )


def _transition_to_thinking(state_controller: object) -> None:
    """Start a text turn, recovering from the prior terminal display state."""

    try:
        state_controller.transition_to("THINKING", reason="text received")  # type: ignore[attr-defined]
    except Exception:
        state_controller.transition_to("IDLE", reason="new text turn")  # type: ignore[attr-defined]
        state_controller.transition_to("THINKING", reason="text received")  # type: ignore[attr-defined]


def _transition_to_error(state_controller: object) -> None:
    try:
        state_controller.transition_to("API_ERROR", reason="chat failure")  # type: ignore[attr-defined]
    except Exception:
        logger.exception("Could not transition device to API_ERROR")
