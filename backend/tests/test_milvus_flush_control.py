from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.exceptions import AppException  # noqa: E402
from app.knowledge.indexing.milvus_flush_control import flush_with_retry  # noqa: E402


class FakeMilvusException(Exception):
    def __init__(self, message: str, code: int = 8) -> None:
        self.code = code
        super().__init__(message)


class FakeCollection:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.flush_calls = 0

    def flush(self) -> None:
        self.flush_calls += 1
        if self.flush_calls <= self.failures:
            raise FakeMilvusException(
                "request is rejected by grpc RateLimiter middleware, please retry later: rate limit exceeded[rate=0.1]"
            )


def test_flush_with_retry_retries_rate_limited_flush() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        sleep_calls: list[float] = []
        with patch.dict(
            "os.environ",
            {
                "MILVUS_FLUSH_COORDINATION_DIR": tmp_dir,
                "MILVUS_FLUSH_MIN_INTERVAL_SECONDS": "0",
                "MILVUS_FLUSH_MAX_RETRIES": "3",
            },
            clear=False,
        ):
            with patch("app.knowledge.indexing.milvus_flush_control.time.sleep", side_effect=sleep_calls.append):
                collection = FakeCollection(failures=1)
                flush_with_retry(collection, collection_name="unit_test_collection")

        assert collection.flush_calls == 2
        assert sleep_calls == [5.0]


def test_flush_with_retry_raises_retryable_app_exception_after_exhaustion() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        with patch.dict(
            "os.environ",
            {
                "MILVUS_FLUSH_COORDINATION_DIR": tmp_dir,
                "MILVUS_FLUSH_MIN_INTERVAL_SECONDS": "0",
                "MILVUS_FLUSH_MAX_RETRIES": "2",
            },
            clear=False,
        ):
            with patch("app.knowledge.indexing.milvus_flush_control.time.sleep", return_value=None):
                collection = FakeCollection(failures=3)
                try:
                    flush_with_retry(collection, collection_name="unit_test_collection")
                    raise AssertionError("expected AppException")
                except AppException as exc:
                    assert exc.code == 503
                assert collection.flush_calls == 2
