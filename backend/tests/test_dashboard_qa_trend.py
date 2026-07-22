"""首页近七天 AI 问答趋势测试。"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-dashboard-trend-32bytes")
os.environ.setdefault("APP_TIMEZONE", "Asia/Shanghai")

from app.models import Base, ChatMessage, ChatSession, Permission, Project, Role, User  # noqa: E402
from app.services.system_service import SystemService  # noqa: E402


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with factory() as session:
        yield session
    engine.dispose()


def _permission(code: str) -> Permission:
    module, action = code.rsplit(":", 1) if ":" in code else (code, "access")
    return Permission(module=module, action=action, code=code, description=code)


def _user(db: Session, username: str, *, admin: bool, project_access: bool = True) -> User:
    permission_codes = ["ai:base-chat", "ai:base-chat:view"]
    if project_access:
        permission_codes.extend(["ai:project-chat", "ai:project-chat:view", "project", "project:view"])
    permissions = []
    for code in permission_codes:
        permission = db.query(Permission).filter(Permission.code == code).one_or_none() or _permission(code)
        permissions.append(permission)
    role = Role(
        name=f"{username}-role",
        code="admin" if admin else f"{username}-role",
        enabled=True,
        security_level="confidential",
        data_scope="all" if admin else "own",
        permissions=permissions,
    )
    user = User(username=username, password_hash="x", real_name=username, roles=[role])
    db.add(user)
    db.flush()
    return user


def _session(db: Session, user: User, chat_type: str, project_id: int | None = None) -> ChatSession:
    session = ChatSession(user_id=user.id, title=chat_type, chat_type=chat_type, project_id=project_id)
    db.add(session)
    db.flush()
    return session


def _message(db: Session, session: ChatSession, user: User, created_at: datetime, role: str = "user") -> None:
    db.add(
        ChatMessage(
            session_id=session.id,
            user_id=user.id if role == "user" else None,
            role=role,
            content="脱敏测试消息",
            created_at=created_at.replace(tzinfo=None),
            updated_at=created_at.replace(tzinfo=None),
        )
    )


@pytest.mark.parametrize(
    ("now", "expected_start", "expected_end"),
    [
        (datetime(2026, 3, 2, 4, tzinfo=UTC), "2026-02-24", "2026-03-02"),
        (datetime(2026, 1, 2, 4, tzinfo=UTC), "2025-12-27", "2026-01-02"),
    ],
)
def test_trend_returns_seven_zero_filled_days_across_date_boundaries(
    db_session: Session, now: datetime, expected_start: str, expected_end: str
) -> None:
    user = _user(db_session, f"admin-{expected_end}", admin=True)
    db_session.commit()

    result = SystemService(db_session)._build_qa_trend(user, now=now)

    assert result["start_date"] == expected_start
    assert result["end_date"] == expected_end
    assert len(result["daily"]) == 7
    assert all(item["total_count"] == 0 for item in result["daily"])
    assert result["total"] == result["enterprise_total"] == result["project_total"] == 0


def test_trend_aggregates_types_and_uses_shanghai_day_boundaries(db_session: Session) -> None:
    admin = _user(db_session, "admin", admin=True)
    project = Project(name="项目", code="P001", security_level="internal", created_by=admin.id)
    db_session.add(project)
    db_session.flush()
    base_session = _session(db_session, admin, "base_chat")
    project_session = _session(db_session, admin, "project_chat", project.id)
    unknown_session = _session(db_session, admin, "legacy_chat")
    # 上海 7/16 00:00、7/16 23:59、7/22 23:59，以及超出范围的 7/23 00:00。
    for created_at in (datetime(2026, 7, 15, 16, tzinfo=UTC), datetime(2026, 7, 16, 15, 59, tzinfo=UTC)):
        _message(db_session, base_session, admin, created_at)
    _message(db_session, project_session, admin, datetime(2026, 7, 22, 15, 59, tzinfo=UTC))
    _message(db_session, project_session, admin, datetime(2026, 7, 22, 15, 58, tzinfo=UTC), role="assistant")
    _message(db_session, project_session, admin, datetime(2026, 7, 22, 16, tzinfo=UTC))
    _message(db_session, unknown_session, admin, datetime(2026, 7, 20, 4, tzinfo=UTC))
    db_session.commit()

    result = SystemService(db_session)._build_qa_trend(admin, now=datetime(2026, 7, 22, 8, tzinfo=UTC))
    by_date = {item["date"]: item for item in result["daily"]}

    assert by_date["2026-07-16"] == {
        "date": "2026-07-16",
        "enterprise_count": 2,
        "project_count": 0,
        "total_count": 2,
    }
    assert by_date["2026-07-22"]["project_count"] == 1
    assert result["enterprise_total"] == 2
    assert result["project_total"] == 1
    assert result["total"] == 3
    assert sum(item["total_count"] for item in result["daily"]) == result["total"]


def test_regular_user_only_sees_own_questions_in_accessible_projects(db_session: Session) -> None:
    regular = _user(db_session, "regular", admin=False)
    other = _user(db_session, "other", admin=False)
    owned_project = Project(name="本人项目", code="OWN", security_level="internal", created_by=regular.id)
    other_project = Project(name="他人项目", code="OTHER", security_level="internal", created_by=other.id)
    db_session.add_all([owned_project, other_project])
    db_session.flush()
    own_base = _session(db_session, regular, "base_chat")
    own_project = _session(db_session, regular, "project_chat", owned_project.id)
    inaccessible_project = _session(db_session, regular, "project_chat", other_project.id)
    other_base = _session(db_session, other, "base_chat")
    created_at = datetime(2026, 7, 20, 4, tzinfo=UTC)
    for session, user in (
        (own_base, regular),
        (own_project, regular),
        (inaccessible_project, regular),
        (other_base, other),
    ):
        _message(db_session, session, user, created_at)
        _message(db_session, session, user, created_at, role="assistant")
    db_session.commit()

    service = SystemService(db_session)
    result = service._build_qa_trend(regular, now=datetime(2026, 7, 22, 8, tzinfo=UTC))
    dashboard = service.dashboard(regular)

    assert result["enterprise_total"] == 1
    assert result["project_total"] == 1
    assert result["total"] == 2
    assert dashboard["project_count"] == 1
    assert dashboard["ai_answer_count"] == 2
