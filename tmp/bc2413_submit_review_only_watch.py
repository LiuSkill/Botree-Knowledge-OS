"""
BC2413 parsed document review-submit watcher.

Purpose:
1. Submit parsed-success documents to review.
2. Keep watching while parsing continues.
3. Do not approve reviews and do not enqueue index builds.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = REPO_ROOT / "tmp"
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(TMP_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

import bc2413_parse_review_index as pipeline
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.services.review_service import ReviewService


LOGGER = logging.getLogger("bc2413_submit_review_only_watch")
SUBMITTABLE_REVIEW_STATUSES = {"draft", "rejected"}


def configure_logging(report_file: Path | None) -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if report_file is not None:
        report_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(report_file, encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
        force=True,
    )


def emit(event: str, **payload: Any) -> None:
    LOGGER.info(json.dumps({"event": event, **payload}, ensure_ascii=False, default=str))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BC2413 parsed document review-submit watcher")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Only report submit candidates")
    mode.add_argument("--commit", action="store_true", help="Submit parsed-success documents to review")
    parser.add_argument("--project-code", default="BC2413", help="Project code")
    parser.add_argument("--operator", default="admin", help="Operator username or user id")
    parser.add_argument("--poll-interval", type=int, default=60, help="Watch interval in seconds")
    parser.add_argument("--progress-interval", type=int, default=180, help="Progress log interval in seconds")
    parser.add_argument("--max-wait-seconds", type=int, default=0, help="0 means no limit")
    parser.add_argument("--watch", action="store_true", help="Keep watching after one pass")
    parser.add_argument(
        "--review-comment",
        default="BC2413 项目资料解析成功后自动提交审核",
        help="Batch review submit comment",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=TMP_ROOT / "bc2413_submit_review_only_report.jsonl",
        help="JSONL report file",
    )
    parser.add_argument("--report-limit", type=int, default=20, help="Max ids/errors shown in one log event")
    return parser.parse_args()


def submit_once(args: argparse.Namespace) -> dict[str, Any]:
    submitted_ids: list[int] = []
    errors: list[dict[str, Any]] = []
    eligible = 0
    already_reviewing = 0
    already_approved = 0
    skipped_not_parsed = 0
    skipped_other_status = 0

    with SessionLocal() as db:
        project = pipeline.get_project(db, args.project_code)
        operator = pipeline.get_operator(db, args.operator)
        review_service = ReviewService(db)

        for version in pipeline.list_current_versions(db, project.id, parsable_only=True):
            if version.parse_status != "success":
                skipped_not_parsed += 1
                continue
            if version.review_status == "approved":
                already_approved += 1
                continue
            if version.review_status == "reviewing":
                already_reviewing += 1
                continue
            if version.review_status not in SUBMITTABLE_REVIEW_STATUSES:
                skipped_other_status += 1
                continue

            eligible += 1
            if args.dry_run:
                continue
            try:
                review_service.submit_review(
                    version.document_id,
                    operator,
                    args.review_comment,
                    version.version_no,
                )
                submitted_ids.append(version.document_id)
            except Exception as exc:  # noqa: BLE001 - batch operation records single-item failure and continues.
                db.rollback()
                errors.append(
                    {
                        "document_id": version.document_id,
                        "version_no": version.version_no,
                        "file_name": version.file_name,
                        "error": str(exc),
                    }
                )
                if len(errors) <= args.report_limit:
                    LOGGER.exception(
                        "BC2413 review submit failed: document_id=%s version_no=%s",
                        version.document_id,
                        version.version_no,
                    )

    return {
        "eligible": eligible,
        "submitted": len(submitted_ids),
        "submitted_document_ids": submitted_ids[: args.report_limit],
        "already_reviewing": already_reviewing,
        "already_approved": already_approved,
        "skipped_not_parsed": skipped_not_parsed,
        "skipped_other_status": skipped_other_status,
        "error_count": len(errors),
        "errors": errors[: args.report_limit],
    }


def main() -> int:
    args = parse_args()
    configure_logging(args.report_file)
    started_at = time.monotonic()
    last_emit = 0.0

    try:
        with SessionLocal() as db:
            project = pipeline.get_project(db, args.project_code)
            operator = pipeline.get_operator(db, args.operator)
            emit(
                "start",
                dry_run=args.dry_run,
                commit=args.commit,
                watch=args.watch,
                project_id=project.id,
                project_code=project.code,
                operator_id=operator.id,
                operator_username=operator.username,
                initial_summary=pipeline.final_summary(args.project_code),
            )

        while True:
            state = submit_once(args)
            now = time.monotonic()
            if state["submitted"] or state["eligible"] or now - last_emit >= args.progress_interval:
                emit("progress", **state, summary=pipeline.final_summary(args.project_code))
                last_emit = now

            if args.dry_run or not args.watch:
                emit("completed", final_state=state, final_summary=pipeline.final_summary(args.project_code))
                return 0 if state["error_count"] == 0 else 2
            if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
                raise AppException("等待自动提交审核超时")
            time.sleep(args.poll_interval)
    except Exception as exc:  # noqa: BLE001 - operational script entrypoint logs fatal error for recovery.
        LOGGER.exception("BC2413 review-submit watcher failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
