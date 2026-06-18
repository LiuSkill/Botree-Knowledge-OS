"""
Chat Session Tests

负责：
1. 验证项目问答会话列表按所选项目隔离
2. 验证未选择项目时不聚合返回所有项目问答会话
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, ChatSession  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.repositories.chat_repository import ChatRepository  # noqa: E402
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
