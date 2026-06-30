"""RBAC permission registry and binding tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-rbac-permissions-32bytes")

from app.api.deps import has_permission  # noqa: E402
from app.core.rbac import permission_catalog  # noqa: E402
from app.models import Base, Permission, Role, User  # noqa: E402
from app.schemas.role import RoleUpdate  # noqa: E402
from app.services.auth_service import AuthService  # noqa: E402
from app.services.system_service import SystemService  # noqa: E402
from app.services.user_service import RoleService  # noqa: E402
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


def seed_permission_catalog(db: Session) -> dict[str, Permission]:
    """Seed permissions from the backend RBAC registry."""

    permissions = [Permission(**record) for record in permission_catalog()]
    db.add_all(permissions)
    db.commit()
    return {permission.code: permission for permission in permissions}


def test_rbac_api_routes_are_registered() -> None:
    """RBAC menu, action and current-permission endpoints are mounted."""

    paths = {route.path for route in app.routes}

    assert "/api/system/menus" in paths
    assert "/api/system/permissions/actions" in paths
    assert "/api/user/current-permissions" in paths


def test_system_menu_and_action_catalog_use_registered_permissions(db_session: Session) -> None:
    """Menu tree and action matrix expose real paths and permission IDs."""

    seed_permission_catalog(db_session)

    menus = SystemService(db_session).list_menus()
    actions = SystemService(db_session).list_action_permissions()
    system_menu = next(menu for menu in menus if menu["id"] == "system")
    user_menu = next(child for child in system_menu["children"] if child["id"] == "system:user")
    department_menu = next(child for child in system_menu["children"] if child["id"] == "system:department:view")
    user_group = next(group for group in actions if group["module"] == "system-user")
    department_group = next(group for group in actions if group["module"] == "system-department")
    create_action = next(action for action in user_group["actions"] if action["code"] == "system:user:create")

    assert user_menu["path"] == "/system/users"
    assert department_menu["path"] == "/system/departments"
    assert isinstance(user_menu["permission_id"], int)
    assert isinstance(department_menu["permission_id"], int)
    assert all(len(group["menu_ids"]) == 1 for group in actions)
    assert user_group["menu_ids"] == ["system:user"]
    assert department_group["menu_ids"] == ["system:department:view"]
    assert {action["code"] for action in department_group["actions"]} == {
        "system:department:create",
        "system:department:edit",
        "system:department:delete",
        "system:department:enable",
        "system:department:disable",
        "system:department:view-detail",
    }
    assert isinstance(create_action["permission_id"], int)


def test_current_permissions_filter_actions_without_bound_page(db_session: Session) -> None:
    """Button permissions do not exist independently from their bound page."""

    permissions = seed_permission_catalog(db_session)
    role = Role(name="User Operator", code="user_operator", enabled=True, permissions=[permissions["system:user:create"]])
    user = User(username="operator", password_hash="x", real_name="Operator", status="enabled", roles=[role])
    db_session.add(user)
    db_session.commit()

    current_permissions = AuthService(db_session).current_permissions(user)

    assert current_permissions["menus"] == []
    assert current_permissions["actions"] == []
    assert has_permission(user, "system:user:create") is False

    role.permissions = [permissions["system:user"]]
    db_session.commit()

    current_permissions = AuthService(db_session).current_permissions(user)

    assert current_permissions["menus"] == ["system:user"]
    assert current_permissions["actions"] == []
    assert has_permission(user, "system:user:create") is False

    role.permissions = [permissions["system:user"], permissions["system:user:create"]]
    db_session.commit()

    current_permissions = AuthService(db_session).current_permissions(user)

    assert current_permissions["menus"] == ["system:user"]
    assert current_permissions["actions"] == ["system:user:create"]
    assert has_permission(user, "system:user:create") is True


def test_role_save_prunes_unbound_action_permissions(db_session: Session) -> None:
    """Saving a role removes actions when their page permission is absent."""

    permissions = seed_permission_catalog(db_session)
    operator = User(username="admin", password_hash="x", real_name="Admin", status="enabled")
    role = Role(name="Limited Role", code="limited", enabled=True)
    db_session.add_all([operator, role])
    db_session.commit()

    updated = RoleService(db_session).update_role(
        role.id,
        RoleUpdate(permission_ids=[permissions["system:user:create"].id]),
        operator,
    )

    assert updated.permissions == []

    updated = RoleService(db_session).update_role(
        role.id,
        RoleUpdate(permission_ids=[permissions["system:user"].id]),
        operator,
    )

    assert {permission.code for permission in updated.permissions} == {"system:user"}

    updated = RoleService(db_session).update_role(
        role.id,
        RoleUpdate(permission_ids=[permissions["system:user"].id, permissions["system:user:create"].id]),
        operator,
    )

    assert {permission.code for permission in updated.permissions} == {"system:user", "system:user:create"}
