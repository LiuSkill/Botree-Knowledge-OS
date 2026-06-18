"""System management pagination and filter tests."""

from __future__ import annotations

from datetime import datetime
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, ModelConfig, OperationLog, Permission, Role, User  # noqa: E402
from app.services.model_service import ModelService  # noqa: E402
from app.services.system_service import SystemService  # noqa: E402
from app.services.user_service import RoleService, UserService  # noqa: E402


@pytest.fixture()
def db_session() -> Session:
    """Create an isolated in-memory database session."""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as session:
        yield session
    engine.dispose()


def seed_users_and_roles(db: Session) -> dict[str, Role]:
    """Seed users, roles and permissions for system management list queries."""

    permission = Permission(module="system", action="view", code="system:view")
    admin_role = Role(name="System Admin", code="admin", description="Administrator role", enabled=True)
    engineer_role = Role(name="Engineer", code="engineer", description="Quality engineer role", enabled=False)
    admin_role.permissions = [permission]
    db.add_all([admin_role, engineer_role])
    db.flush()

    db.add_all(
        [
            User(
                username="alice",
                password_hash="x",
                real_name="Alice Manager",
                email="alice@example.com",
                department="Management",
                status="enabled",
                roles=[admin_role],
            ),
            User(
                username="bob",
                password_hash="x",
                real_name="Bob Engineer",
                email="bob@example.com",
                department="Quality",
                status="disabled",
                roles=[engineer_role],
            ),
            User(
                username="carol",
                password_hash="x",
                real_name="Carol Analyst",
                email="carol@example.com",
                department="Quality",
                status="enabled",
            ),
        ]
    )
    db.commit()
    return {"admin_role": admin_role, "engineer_role": engineer_role}


def seed_model_configs(db: Session) -> None:
    """Seed model configs covering type, enabled and default filters."""

    db.add_all(
        [
            ModelConfig(
                provider="openai",
                model_name="gpt-4o",
                api_base="https://api.openai.example",
                api_key="sk-test",
                model_type="llm",
                is_default=True,
                enabled=True,
            ),
            ModelConfig(
                provider="baai",
                model_name="bge-m3",
                api_base=None,
                api_key=None,
                model_type="embedding",
                is_default=False,
                enabled=False,
            ),
            ModelConfig(
                provider="qwen",
                model_name="qwen-plus",
                api_base="https://dashscope.example",
                api_key="sk-test",
                model_type="answer_llm",
                is_default=False,
                enabled=True,
            ),
        ]
    )
    db.commit()


def seed_operation_logs(db: Session) -> None:
    """Seed operation logs with different results, targets and times."""

    db.add_all(
        [
            OperationLog(
                username="alice",
                action="upload document",
                target_type="document",
                target_id="1",
                detail="upload recycle report",
                result="success",
                created_at=datetime(2026, 6, 18, 9, 0, 0),
            ),
            OperationLog(
                username="bob",
                action="delete role",
                target_type="role",
                target_id="2",
                detail="permission denied",
                result="failed",
                created_at=datetime(2026, 6, 18, 10, 0, 0),
            ),
            OperationLog(
                username="carol",
                action="test model",
                target_type="model_config",
                target_id="3",
                detail="connectivity test",
                result="success",
                created_at=datetime(2026, 6, 19, 9, 0, 0),
            ),
        ]
    )
    db.commit()


def test_user_list_filters_and_paginates(db_session: Session) -> None:
    """Users support keyword, status, role and page parameters."""

    roles = seed_users_and_roles(db_session)

    enabled_result = UserService(db_session).list_users(status="enabled", page=1, page_size=1)
    role_result = UserService(db_session).list_users(role_id=roles["engineer_role"].id)
    keyword_result = UserService(db_session).list_users(keyword="Quality")

    assert enabled_result["total"] == 2
    assert enabled_result["page"] == 1
    assert enabled_result["page_size"] == 1
    assert len(enabled_result["items"]) == 1
    assert role_result["total"] == 1
    assert role_result["items"][0].username == "bob"
    assert {user.username for user in keyword_result["items"]} == {"bob", "carol"}


def test_role_list_filters_and_paginates(db_session: Session) -> None:
    """Roles support keyword, enabled and page parameters."""

    seed_users_and_roles(db_session)

    page_result = RoleService(db_session).list_role_page(page=1, page_size=1)
    keyword_result = RoleService(db_session).list_role_page(keyword="engineer")
    disabled_result = RoleService(db_session).list_role_page(enabled=False)

    assert page_result["total"] == 2
    assert len(page_result["items"]) == 1
    assert keyword_result["total"] == 1
    assert keyword_result["items"][0].code == "engineer"
    assert disabled_result["total"] == 1
    assert disabled_result["items"][0].enabled is False


def test_model_config_list_filters_and_paginates(db_session: Session) -> None:
    """Model configs support keyword, type, enabled and default filters."""

    seed_model_configs(db_session)

    page_result = ModelService(db_session).list_config_page(page=1, page_size=1)
    keyword_result = ModelService(db_session).list_config_page(keyword="qwen")
    embedding_result = ModelService(db_session).list_config_page(model_type="embedding")
    disabled_result = ModelService(db_session).list_config_page(enabled=False)
    default_result = ModelService(db_session).list_config_page(is_default=True)

    assert page_result["total"] == 3
    assert len(page_result["items"]) == 1
    assert keyword_result["items"][0].provider == "qwen"
    assert embedding_result["items"][0].model_name == "bge-m3"
    assert disabled_result["items"][0].enabled is False
    assert default_result["items"][0].model_name == "gpt-4o"


def test_operation_log_list_filters_and_paginates(db_session: Session) -> None:
    """Operation logs support keyword, result, target, time and page parameters."""

    seed_operation_logs(db_session)

    page_result = SystemService(db_session).list_logs(page=1, page_size=2)
    failed_result = SystemService(db_session).list_logs(result="failed")
    target_result = SystemService(db_session).list_logs(target_type="model_config")
    keyword_result = SystemService(db_session).list_logs(keyword="recycle")
    time_result = SystemService(db_session).list_logs(
        started_at=datetime(2026, 6, 18, 0, 0, 0),
        ended_at=datetime(2026, 6, 18, 23, 59, 59),
    )

    assert page_result["total"] == 3
    assert page_result["page_size"] == 2
    assert len(page_result["items"]) == 2
    assert failed_result["total"] == 1
    assert failed_result["items"][0].username == "bob"
    assert target_result["items"][0].action == "test model"
    assert keyword_result["items"][0].target_type == "document"
    assert {log.username for log in time_result["items"]} == {"alice", "bob"}
