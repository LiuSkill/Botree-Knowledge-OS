"""Project data-scope helpers for RBAC roles."""

from __future__ import annotations

from typing import Any, Literal

from app.core.exceptions import AppException

DataScope = Literal["all", "department", "own", "public_only"]

DATA_SCOPE_ALL: DataScope = "all"
DATA_SCOPE_DEPARTMENT: DataScope = "department"
DATA_SCOPE_OWN: DataScope = "own"
DATA_SCOPE_PUBLIC_ONLY: DataScope = "public_only"

DATA_SCOPE_CHOICES: tuple[str, ...] = (
    DATA_SCOPE_ALL,
    DATA_SCOPE_DEPARTMENT,
    DATA_SCOPE_OWN,
    DATA_SCOPE_PUBLIC_ONLY,
)
DEFAULT_DATA_SCOPE: DataScope = DATA_SCOPE_OWN


def normalize_data_scope(value: Any, *, default: str | None = DEFAULT_DATA_SCOPE) -> str:
    """Normalize and validate a role project data scope."""

    raw = str(value or "").strip().lower()
    if not raw:
        if default is not None:
            return default
        raise AppException("角色数据范围不能为空", status_code=400, code=400)
    if raw not in DATA_SCOPE_CHOICES:
        raise AppException("角色数据范围非法，仅支持 all/department/own/public_only", status_code=400, code=400)
    return raw


def enabled_role_data_scopes(user: Any | None) -> set[str]:
    """Return normalized data scopes from enabled roles."""

    if user is None:
        return set()
    scopes: set[str] = set()
    for role in getattr(user, "roles", None) or []:
        if not bool(getattr(role, "enabled", False)):
            continue
        scopes.add(normalize_data_scope(getattr(role, "data_scope", None), default=DEFAULT_DATA_SCOPE))
    return scopes
