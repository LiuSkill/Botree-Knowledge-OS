from __future__ import annotations

import sys
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.config import Settings


def test_cors_allow_origins_rejects_wildcard() -> None:
    with pytest.raises(ValueError):
        Settings(
            _env_file=None,
            JWT_SECRET_KEY="x" * 32,
            CORS_ALLOW_ORIGINS="*",
        )


def test_cors_allow_origins_list_parses_comma_separated_values() -> None:
    settings = Settings(
        _env_file=None,
        JWT_SECRET_KEY="x" * 32,
        CORS_ALLOW_ORIGINS="http://a.example,http://b.example",
    )

    assert settings.cors_allow_origins_list == ["http://a.example", "http://b.example"]


def test_effective_database_url_rejects_missing_database_when_sqlite_fallback_disabled() -> None:
    settings = Settings(
        _env_file=None,
        JWT_SECRET_KEY="x" * 32,
        ALLOW_SQLITE_FALLBACK=False,
    )

    with pytest.raises(ValueError):
        _ = settings.effective_database_url
