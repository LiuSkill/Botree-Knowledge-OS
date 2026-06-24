"""
Chat Session Tests

负责：
1. 验证项目问答会话列表按所选项目隔离
2. 验证未选择项目时不聚合返回所有项目问答会话
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, ChatCitation, ChatMessage, ChatSession, RetrievalTrace  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.repositories.chat_repository import ChatRepository  # noqa: E402
from app.schemas.chat import ChatSessionUpdate  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402


def make_session() -> Session:
    """创建独立内存数据库会话。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def make_admin_user() -> User:
    """创建具备项目访问权限的测试用户。"""

    user = User(id=1, username="admin", password_hash="x", real_name="Admin")
    user.roles = [Role(id=1, name="Admin", code="admin", enabled=True)]
    return user


def seed_chat_sessions(db: Session) -> None:
    """写入同一用户跨项目会话和他人会话，用于验证隔离边界。"""

    db.add_all(
        [
            ChatSession(user_id=1, title="项目10旧会话", chat_type="project_chat", mode="auto", project_id=10),
            ChatSession(user_id=1, title="项目20会话", chat_type="project_chat", mode="auto", project_id=20),
            ChatSession(user_id=1, title="基础问答会话", chat_type="base_chat", mode="auto", project_id=None),
            ChatSession(user_id=2, title="他人项目10会话", chat_type="project_chat", mode="auto", project_id=10),
            ChatSession(user_id=1, title="项目10新会话", chat_type="project_chat", mode="auto", project_id=10),
        ]
    )
    db.commit()


def test_chat_repository_filters_project_sessions_by_project_id() -> None:
    """同一用户的项目问答会话应按 project_id 过滤。"""

    db = make_session()
    try:
        seed_chat_sessions(db)

        sessions = ChatRepository(db).list_sessions(user_id=1, chat_type="project_chat", project_id=10)

        assert [session.title for session in sessions] == ["项目10新会话", "项目10旧会话"]
    finally:
        db.close()


def test_project_chat_session_list_requires_selected_project() -> None:
    """未选择项目时，项目问答会话列表不返回跨项目聚合结果。"""

    db = make_session()
    try:
        seed_chat_sessions(db)

        sessions = ChatService(db).list_sessions(make_admin_user(), chat_type="project_chat")

        assert sessions == []
    finally:
        db.close()


def test_chat_service_lists_only_selected_project_sessions() -> None:
    """Service 层在校验项目权限后仅返回所选项目会话。"""

    db = make_session()
    try:
        seed_chat_sessions(db)

        sessions = ChatService(db).list_sessions(make_admin_user(), chat_type="project_chat", project_id=20)

        assert [session.title for session in sessions] == ["项目20会话"]
    finally:
        db.close()


def test_chat_service_updates_session_display_state_and_orders_pinned_first() -> None:
    """会话置顶、收藏和重命名应持久化，列表展示时置顶优先。"""

    db = make_session()
    try:
        first_session = ChatSession(user_id=1, title="first", chat_type="base_chat", mode="auto")
        second_session = ChatSession(user_id=1, title="second", chat_type="base_chat", mode="auto")
        db.add_all([first_session, second_session])
        db.commit()

        updated = ChatService(db).update_session(
            first_session.id,
            ChatSessionUpdate(title="renamed", is_pinned=True, is_favorite=True),
            make_admin_user(),
        )
        sessions = ChatRepository(db).list_sessions(user_id=1, chat_type="base_chat")

        assert updated.title == "renamed"
        assert updated.is_pinned is True
        assert updated.is_favorite is True
        assert sessions[0].id == first_session.id
    finally:
        db.close()


def test_chat_service_delete_session_clears_messages_citations_and_traces() -> None:
    """删除会话时应先清理消息、引用和检索审计，避免外键约束阻塞。"""

    db = make_session()
    try:
        chat_session = ChatSession(user_id=1, title="待删除会话", chat_type="base_chat", mode="auto")
        db.add(chat_session)
        db.flush()

        user_message = ChatMessage(session_id=chat_session.id, user_id=1, role="user", content="问题")
        assistant_message = ChatMessage(session_id=chat_session.id, role="assistant", content="回答")
        db.add_all([user_message, assistant_message])
        db.flush()

        db.add(
            ChatCitation(
                message_id=assistant_message.id,
                source_type="base",
                knowledge_base_id=1,
                document_id=1,
                chunk_id=1,
                file_name="source.pdf",
                content="引用内容",
            )
        )
        db.add_all(
            [
                RetrievalTrace(
                    user_id=1,
                    session_id=chat_session.id,
                    message_id=assistant_message.id,
                    chat_type="base_chat",
                    mode="auto",
                    question="问题",
                ),
                RetrievalTrace(
                    user_id=1,
                    session_id=chat_session.id,
                    message_id=None,
                    chat_type="base_chat",
                    mode="auto",
                    question="未绑定消息的轨迹",
                ),
            ]
        )
        db.commit()

        ChatService(db).delete_session(chat_session.id, make_admin_user())

        assert db.get(ChatSession, chat_session.id) is None
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 0
        assert db.scalar(select(func.count()).select_from(ChatCitation)) == 0
        assert db.scalar(select(func.count()).select_from(RetrievalTrace)) == 0
    finally:
        db.close()
