"""问答预过滤规则变更生效前的离线召回报告门禁。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import AppException


class RuntimeRecallGateService:
    REQUIRED_BUCKETS = (
        "text",
        "visual",
        "mixed",
        "ocr_rejection",
        "local_region",
        "version",
        "duplicate",
        "timeout",
    )

    def __init__(self, enabled: bool | None = None, report_path: str | None = None) -> None:
        settings = get_settings()
        self.enabled = settings.runtime_recall_gate_enabled if enabled is None else enabled
        self.report_path = settings.runtime_recall_gate_report_path if report_path is None else report_path

    @staticmethod
    def rule_digest(rule_payload: object) -> str:
        canonical = json.dumps(rule_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def ensure_passed(self, change_type: str, rule_payload: object | None = None) -> None:
        if not self.enabled:
            return
        path = Path(self.report_path)
        if not path.is_file():
            raise AppException(f"{change_type} change is missing an offline recall gate report")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AppException("offline recall gate report is unreadable") from exc
        if not isinstance(payload, dict):
            raise AppException("offline recall gate report is invalid")
        if rule_payload is not None:
            if payload.get("change_type") != change_type:
                raise AppException("offline recall gate report does not match change type")
            if payload.get("rule_digest") != self.rule_digest(rule_payload):
                raise AppException("offline recall gate report does not match rule change")
            expires_at = self._parse_datetime(payload.get("expires_at"))
            if expires_at is None or expires_at <= datetime.now(UTC):
                raise AppException("offline recall gate report expired")
        buckets = payload.get("buckets")
        failed = [
            name
            for name in self.REQUIRED_BUCKETS
            if not isinstance(buckets, dict) or not isinstance(buckets.get(name), dict) or not buckets[name].get("passed")
        ]
        if failed:
            raise AppException(f"offline recall gate failed: {', '.join(failed)}")

    @staticmethod
    def _parse_datetime(value: object) -> datetime | None:
        if not isinstance(value, str):
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)
