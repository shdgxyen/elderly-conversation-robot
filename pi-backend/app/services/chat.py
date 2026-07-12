"""Transactional text-chat use case."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import ConversationTurn, User
from app.llm.chat_client import ChatClient


@dataclass(frozen=True, slots=True)
class ChatResult:
    user_id: str
    reply: str
    user_turn_id: str
    assistant_turn_id: str


class ChatService:
    """Generate and atomically persist one user/assistant turn pair."""

    def __init__(self, llm: ChatClient) -> None:
        self.llm = llm

    def chat(
        self,
        session: Session,
        *,
        user_id: str,
        text: str,
        display_name: str,
        source: str,
        should_remember: bool,
        privacy_level: str,
    ) -> ChatResult:
        with session.begin():
            user = session.get(User, user_id)
            if user is None:
                user = User(id=user_id, display_name=display_name)
                effective_display_name = display_name
            else:
                # The stored identity is authoritative.  A caller cannot use
                # an existing user ID with a different display name.
                effective_display_name = user.display_name

            # The model call and both records share one use-case transaction:
            # a generation or flush error cannot leave a half conversation.
            reply = self.llm.generate_reply(
                text,
                display_name=effective_display_name,
            )

            if user not in session:
                session.add(user)
                # Flush the parent first because these lightweight mappings do
                # not declare ORM relationships.  It remains in the same
                # transaction and is rolled back with the turn pair on error.
                session.flush()

            user_turn = ConversationTurn(
                user_id=user_id,
                role="user",
                text=text,
                source=source,
                should_remember=should_remember,
                privacy_level=privacy_level,
            )
            assistant_turn = ConversationTurn(
                user_id=user_id,
                role="assistant",
                text=reply,
                source="system",
                should_remember=should_remember,
                privacy_level=privacy_level,
            )
            session.add_all((user_turn, assistant_turn))
            session.flush()

        return ChatResult(
            user_id=user_id,
            reply=reply,
            user_turn_id=user_turn.id,
            assistant_turn_id=assistant_turn.id,
        )
