"""Shared Milvus flush coordination with retry for maintenance-heavy workloads."""

from __future__ import annotations

import fcntl
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

DEFAULT_COORDINATION_DIR = "/app/logs/milvus_flush"
DEFAULT_MIN_INTERVAL_SECONDS = 11.0
DEFAULT_MAX_RETRIES = 8
DEFAULT_RETRY_BASE_SECONDS = 5.0


def flush_with_retry(collection: Any, *, collection_name: str) -> None:
    """Flush a Milvus collection with cross-process pacing and retry."""

    max_retries = _int_env("MILVUS_FLUSH_MAX_RETRIES", DEFAULT_MAX_RETRIES)
    retry_base_seconds = _float_env("MILVUS_FLUSH_RETRY_BASE_SECONDS", DEFAULT_RETRY_BASE_SECONDS)

    for attempt in range(1, max_retries + 1):
        try:
            _flush_once(collection)
            return
        except Exception as exc:
            retryable = _is_retryable_flush_error(exc)
            if not retryable or attempt >= max_retries:
                raise AppException(
                    f"Milvus flush failed: collection={collection_name} error={type(exc).__name__}: {exc}",
                    status_code=503 if retryable else 500,
                    code=503 if retryable else 500,
                ) from exc
            sleep_seconds = retry_base_seconds * attempt
            logger.warning(
                "Milvus flush重试: collection=%s attempt=%s/%s sleep_seconds=%s error_type=%s",
                collection_name,
                attempt,
                max_retries,
                sleep_seconds,
                type(exc).__name__,
            )
            time.sleep(sleep_seconds)


def _flush_once(collection: Any) -> None:
    coordination_dir = _coordination_dir()
    coordination_dir.mkdir(parents=True, exist_ok=True)
    lock_path = coordination_dir / "flush.lock"
    state_path = coordination_dir / "flush.state"

    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        _sleep_until_allowed(state_path)
        collection.flush()
        state_path.write_text(f"{time.time():.6f}\n", encoding="utf-8")


def _sleep_until_allowed(state_path: Path) -> None:
    min_interval_seconds = _float_env("MILVUS_FLUSH_MIN_INTERVAL_SECONDS", DEFAULT_MIN_INTERVAL_SECONDS)
    if min_interval_seconds <= 0:
        return

    last_flush_at = _read_last_flush_at(state_path)
    if last_flush_at is None:
        return

    sleep_seconds = last_flush_at + min_interval_seconds - time.time()
    if sleep_seconds > 0:
        logger.info("Milvus flush节流等待: sleep_seconds=%.2f", sleep_seconds)
        time.sleep(sleep_seconds)


def _read_last_flush_at(state_path: Path) -> float | None:
    if not state_path.exists():
        return None
    try:
        return float(state_path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _coordination_dir() -> Path:
    configured = os.getenv("MILVUS_FLUSH_COORDINATION_DIR")
    if configured:
        return Path(configured)
    default_dir = Path(DEFAULT_COORDINATION_DIR)
    if default_dir.parent.exists():
        return default_dir
    return Path(tempfile.gettempdir()) / "botree-milvus-flush"


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _is_retryable_flush_error(exc: Exception) -> bool:
    message = str(exc).lower()
    retryable_tokens = (
        "rate limit exceeded",
        "retry later",
        "resource exhausted",
        "too many requests",
        "deadline exceeded",
        "temporarily unavailable",
        "timed out",
        "timeout",
        "connection reset",
        "connection refused",
        "unavailable",
    )
    if any(token in message for token in retryable_tokens):
        return True

    error_code = getattr(exc, "code", None)
    if isinstance(error_code, int) and error_code in {1, 8, 14}:
        return True

    return type(exc).__name__ in {"MilvusException", "RpcError"}
