"""Chat feedback tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.exceptions import AppException  # noqa: E402
from app.models import Base  # noqa: E402
from app.models.chat import ChatMessage, ChatSession  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.schemas.chat import ChatMessageFeedbackUpdate  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as session:
        yield session
    engine.dispose()


def _create_chat_fixture(db: Session) -> tuple[User, ChatMessage, ChatMessage]:
    user = User(username="feedback-user", password_hash="hashed", real_name="Feedback User")
    user.roles = [Role(name="Feedback Admin", code="admin", enabled=True)]
    db.add(user)
    db.flush()
    chat_session = ChatSession(user_id=user.id, title="feedback", chat_type="base_chat", mode="auto")
    db.add(chat_session)
    db.flush()
    user_message = ChatMessage(session_id=chat_session.id, user_id=user.id, role="user", content="原始问题")
    assistant_message = ChatMessage(session_id=chat_session.id, role="assistant", content="回答内容")
    db.add_all([user_message, assistant_message])
    db.commit()
    return user, user_message, assistant_message


def test_update_message_feedback_supports_like_dislike_and_clear(db_session: Session) -> None:
    user, _user_message, assistant_message = _create_chat_fixture(db_session)
    service = ChatService(db_session)

    like_result = service.update_message_feedback(
        assistant_message.id,
        ChatMessageFeedbackUpdate(feedback_status="like"),
        user,
    )
    assert like_result == {"message_id": assistant_message.id, "feedback_status": "like"}

    dislike_result = service.update_message_feedback(
        assistant_message.id,
        ChatMessageFeedbackUpdate(feedback_status="dislike"),
        user,
    )
    assert dislike_result == {"message_id": assistant_message.id, "feedback_status": "dislike"}

    clear_result = service.update_message_feedback(
        assistant_message.id,
        ChatMessageFeedbackUpdate(feedback_status=None),
        user,
    )
    assert clear_result == {"message_id": assistant_message.id, "feedback_status": None}


def test_update_message_feedback_rejects_user_message(db_session: Session) -> None:
    user, user_message, _assistant_message = _create_chat_fixture(db_session)

    with pytest.raises(AppException, match="只能反馈助手回答"):
        ChatService(db_session).update_message_feedback(
            user_message.id,
            ChatMessageFeedbackUpdate(feedback_status="like"),
            user,
        )


def test_update_message_feedback_rejects_other_user_session(db_session: Session) -> None:
    owner, _user_message, assistant_message = _create_chat_fixture(db_session)
    other = User(username="other-user", password_hash="hashed", real_name="Other User")
    db_session.add(other)
    db_session.commit()

    with pytest.raises(AppException, match="无权访问该会话"):
        ChatService(db_session).update_message_feedback(
            assistant_message.id,
            ChatMessageFeedbackUpdate(feedback_status="like"),
            other,
        )

    assert owner.id != other.id
