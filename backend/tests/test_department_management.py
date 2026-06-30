"""Department management service tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import Session, sessionmaker
from fastapi.testclient import TestClient

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.api.deps import get_current_user  # noqa: E402
from app.core.database import get_db  # noqa: E402
from app.core.exceptions import AppException  # noqa: E402
from app.models import Base, Department, OperationLog, User  # noqa: E402
from app.repositories.department_repository import DepartmentRepository  # noqa: E402
from app.schemas.department import DepartmentCreate, DepartmentStatusUpdate, DepartmentUpdate  # noqa: E402
from app.schemas.user import UserCreate, UserUpdate  # noqa: E402
from app.services.department_service import DepartmentService  # noqa: E402
from app.services.user_service import UserService  # noqa: E402
from main import app  # noqa: E402


@pytest.fixture()
def db_session() -> Session:
    """Create an isolated in-memory database session."""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with session_factory() as session:
        yield session
    engine.dispose()


@pytest.fixture()
def api_db_session() -> Session:
    """Create a TestClient-friendly in-memory database session."""

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = session_factory()
    try:
        yield session
    finally:
        app.dependency_overrides.clear()
        session.close()
        engine.dispose()


def seed_operator(db: Session) -> User:
    """Seed the operator required by operation logging."""

    operator = User(username="admin", password_hash="x", real_name="Admin", status="enabled")
    db.add(operator)
    db.commit()
    db.refresh(operator)
    return operator


def test_department_api_requires_backend_permission(api_db_session: Session) -> None:
    """Direct API calls without department permission return 403."""

    operator = seed_operator(api_db_session)
    api_db_session.add(Department(name="Root", code="ROOT", status="enabled", sort_order=0, is_deleted=False))
    api_db_session.commit()

    def override_db() -> Session:
        return api_db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: operator

    response = TestClient(app).get("/api/system/departments/tree")

    assert response.status_code == 403


def test_department_tree_and_validation_rules(db_session: Session) -> None:
    """Departments are tree-shaped and enforce code/name/parent rules."""

    operator = seed_operator(db_session)
    service = DepartmentService(db_session)

    root = service.create_department(
        DepartmentCreate(name="Root", code="ROOT", status="enabled", sort_order=1),
        operator,
    )
    child = service.create_department(
        DepartmentCreate(name="Child", code="CHILD", parent_id=root["id"], sort_order=2),
        operator,
    )

    tree = service.list_department_tree()

    assert tree[0]["id"] == root["id"]
    assert tree[0]["children"][0]["id"] == child["id"]

    with pytest.raises(AppException):
        service.create_department(DepartmentCreate(name="Other", code="ROOT"), operator)

    with pytest.raises(AppException):
        service.create_department(DepartmentCreate(name="Child", code="CHILD-2", parent_id=root["id"]), operator)

    with pytest.raises(AppException):
        service.update_department(root["id"], DepartmentUpdate(parent_id=child["id"]), operator)


def test_department_delete_blocks_children_and_users(db_session: Session) -> None:
    """Departments cannot be deleted when children or assigned users exist."""

    operator = seed_operator(db_session)
    department_service = DepartmentService(db_session)
    user_service = UserService(db_session)

    root = department_service.create_department(DepartmentCreate(name="Root", code="ROOT"), operator)
    child = department_service.create_department(
        DepartmentCreate(name="Child", code="CHILD", parent_id=root["id"]),
        operator,
    )

    with pytest.raises(AppException):
        department_service.delete_department(root["id"], operator)

    department_service.delete_department(child["id"], operator)
    user = user_service.create_user(UserCreate(username="alice", real_name="Alice", department_id=root["id"]), operator)

    with pytest.raises(AppException):
        department_service.delete_department(root["id"], operator)

    user.department_id = None
    user.department = None
    db_session.commit()
    department_service.delete_department(root["id"], operator)

    deleted_department = DepartmentRepository(db_session).get_by_id(root["id"], include_deleted=True)
    department_log_count = db_session.query(OperationLog).filter(OperationLog.target_type == "department").count()

    assert deleted_department is not None
    assert deleted_department.is_deleted is True
    assert department_log_count >= 4


def test_disabled_department_user_binding_rules(db_session: Session) -> None:
    """Disabled departments are hidden from new bindings but existing bindings can remain."""

    operator = seed_operator(db_session)
    department_service = DepartmentService(db_session)
    user_service = UserService(db_session)

    department = department_service.create_department(DepartmentCreate(name="Root", code="ROOT"), operator)
    user = user_service.create_user(UserCreate(username="alice", real_name="Alice", department_id=department["id"]), operator)

    department_service.update_status(department["id"], DepartmentStatusUpdate(status="disabled"), operator)

    with pytest.raises(AppException):
        user_service.create_user(UserCreate(username="bob", real_name="Bob", department_id=department["id"]), operator)

    updated_user = user_service.update_user(
        user.id,
        UserUpdate(real_name="Alice Renamed", department_id=department["id"]),
        operator,
    )

    assert updated_user.department_id == department["id"]
    assert updated_user.department == "Root"
