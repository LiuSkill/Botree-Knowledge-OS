"""Security level helpers."""

from __future__ import annotations

from typing import Any, Literal

from app.core.exceptions import AppException

SecurityLevel = Literal["public", "internal", "confidential"]

SECURITY_LEVEL_PUBLIC: SecurityLevel = "public"
SECURITY_LEVEL_INTERNAL: SecurityLevel = "internal"
SECURITY_LEVEL_CONFIDENTIAL: SecurityLevel = "confidential"

SECURITY_LEVEL_ORDER: dict[str, int] = {
    SECURITY_LEVEL_PUBLIC: 0,
    SECURITY_LEVEL_INTERNAL: 1,
    SECURITY_LEVEL_CONFIDENTIAL: 2,
}

SECURITY_LEVEL_LABELS: dict[str, str] = {
    SECURITY_LEVEL_PUBLIC: "公开",
    SECURITY_LEVEL_INTERNAL: "内部",
    SECURITY_LEVEL_CONFIDENTIAL: "秘密",
}

SECURITY_LEVEL_CHOICES: tuple[str, ...] = tuple(SECURITY_LEVEL_ORDER.keys())
DEFAULT_SECURITY_LEVEL: SecurityLevel = SECURITY_LEVEL_INTERNAL


def normalize_security_level(value: Any, *, default: str | None = None) -> str:
    """Normalize a security level and reject invalid values."""

    raw = str(value or "").strip().lower()
    if not raw:
        if default is not None:
            return default
        raise AppException("密级不能为空", status_code=400, code=400)
    if raw not in SECURITY_LEVEL_ORDER:
        raise AppException("密级非法，仅支持 public/internal/confidential", status_code=400, code=400)
    return raw


def security_level_rank(value: Any, *, default: str = DEFAULT_SECURITY_LEVEL) -> int:
    """Return the comparable rank of a security level."""

    normalized = normalize_security_level(value, default=default)
    return SECURITY_LEVEL_ORDER[normalized]


def max_security_level(levels: list[Any] | tuple[Any, ...], *, default: str = SECURITY_LEVEL_PUBLIC) -> str:
    """Return the highest level from a list of levels."""

    normalized_levels = [normalize_security_level(level, default=default) for level in levels if level is not None]
    if not normalized_levels:
        return default
    return max(normalized_levels, key=lambda item: SECURITY_LEVEL_ORDER[item])


def allowed_security_levels(max_level: Any) -> list[str]:
    """Return all levels allowed by the given max level."""

    max_rank = security_level_rank(max_level, default=SECURITY_LEVEL_PUBLIC)
    return [level for level, rank in SECURITY_LEVEL_ORDER.items() if rank <= max_rank]


def can_access_security_level(user_level: Any, target_level: Any) -> bool:
    """Check whether the user level covers the target level."""

    return security_level_rank(user_level, default=SECURITY_LEVEL_PUBLIC) >= security_level_rank(
        target_level,
        default=SECURITY_LEVEL_PUBLIC,
    )


def user_max_security_level(user: Any | None) -> str:
    """Derive the max level from enabled roles only."""

    if user is None:
        return SECURITY_LEVEL_PUBLIC
    role_levels = [
        getattr(role, "security_level", None)
        for role in (getattr(user, "roles", None) or [])
        if bool(getattr(role, "enabled", False))
    ]
    return max_security_level(role_levels, default=SECURITY_LEVEL_PUBLIC)


def ensure_security_level_access(user: Any | None, target_level: Any, *, message: str = "无权访问该密级内容") -> None:
    """Raise if the user cannot access the target level."""

    if not can_access_security_level(user_max_security_level(user), target_level):
        raise AppException(message, status_code=403, code=403)
