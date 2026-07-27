import json
from datetime import UTC, datetime, timedelta

import pytest

from app.core.exceptions import AppException
from app.services.runtime_recall_gate_service import RuntimeRecallGateService


def test_runtime_gate_rejects_any_failed_critical_bucket(tmp_path) -> None:
    report = tmp_path / "recall.json"
    report.write_text(json.dumps({"buckets": {"text": {"passed": True}, "visual": {"passed": False}}}), encoding="utf-8")

    with pytest.raises(AppException, match="visual"):
        RuntimeRecallGateService(enabled=True, report_path=str(report)).ensure_passed("permission")


def test_runtime_gate_accepts_segmented_report_when_every_bucket_passes(tmp_path) -> None:
    report = tmp_path / "recall.json"
    buckets = {name: {"passed": True} for name in RuntimeRecallGateService.REQUIRED_BUCKETS}
    report.write_text(json.dumps({"buckets": buckets}), encoding="utf-8")

    RuntimeRecallGateService(enabled=True, report_path=str(report)).ensure_passed("status")


def test_runtime_gate_rejects_stale_report_bound_to_rule_change(tmp_path) -> None:
    report = tmp_path / "recall.json"
    buckets = {name: {"passed": True} for name in RuntimeRecallGateService.REQUIRED_BUCKETS}
    report.write_text(
        json.dumps(
            {
                "change_type": "permission",
                "rule_digest": RuntimeRecallGateService.rule_digest({"role": "reader"}),
                "expires_at": (datetime.now(UTC) - timedelta(seconds=1)).isoformat(),
                "buckets": buckets,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(AppException, match="expired"):
        RuntimeRecallGateService(enabled=True, report_path=str(report)).ensure_passed(
            "permission", {"role": "reader"}
        )
