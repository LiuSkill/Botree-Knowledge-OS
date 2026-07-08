"""
BC2413 review-approval and index-build watcher.

Purpose:
1. Approve only documents that are already in reviewing status.
2. Enqueue full_build tasks for approved parsed documents.
3. Never submit draft/rejected documents to review.
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


LOGGER = logging.getLogger("bc2413_approve_build_reviewing_only")


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
    parser = argparse.ArgumentParser(description="BC2413 approve reviewing documents and build index")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Only report candidates")
    mode.add_argument("--commit", action="store_true", help="Approve reviewing documents and enqueue full_build")
    parser.add_argument("--project-code", default="BC2413", help="Project code")
    parser.add_argument("--operator", default="admin", help="Operator username or user id")
    parser.add_argument("--poll-interval", type=int, default=60, help="Watch interval in seconds")
    parser.add_argument("--progress-interval", type=int, default=180, help="Progress log interval in seconds")
    parser.add_argument("--max-wait-seconds", type=int, default=0, help="0 means no limit")
    parser.add_argument("--max-active-build", type=int, default=1, help="Max pending/running full_build tasks")
    parser.add_argument("--enqueue-limit", type=int, default=1, help="Max full_build tasks to enqueue per round")
    parser.add_argument("--retry-failed-build", action="store_true", help="Retry failed full_build tasks")
    parser.add_argument("--allow-no-worker", action="store_true", help="Allow enqueue when no RQ worker is online")
    parser.add_argument(
        "--review-comment",
        default="BC2413 项目资料已提交审核，批量自动审核通过并构建索引",
        help="Batch review approval comment",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=TMP_ROOT / "bc2413_approve_build_reviewing_only_report.jsonl",
        help="JSONL report file",
    )
    parser.add_argument("--report-limit", type=int, default=20, help="Max ids/errors shown in one log event")
    return parser.parse_args()


def approve_reviewing_once(args: argparse.Namespace) -> dict[str, Any]:
    approved_ids: list[int] = []
    errors: list[dict[str, Any]] = []
    candidates = 0
    already_approved = 0
    skipped_not_parsed = 0
    skipped_draft_or_rejected = 0
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
            if version.review_status in {"draft", "rejected"}:
                skipped_draft_or_rejected += 1
                continue
            if version.review_status != "reviewing":
                skipped_other_status += 1
                continue

            candidates += 1
            if args.dry_run:
                continue
            try:
                task = pipeline.get_open_review_task(db, version)
                if task is None:
                    raise AppException("未找到待审核任务")
                review_service.approve(task.id, operator, args.review_comment)
                approved_ids.append(version.document_id)
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
                        "BC2413 review approve failed: document_id=%s version_no=%s",
                        version.document_id,
                        version.version_no,
                    )

    return {
        "reviewing_candidates": candidates,
        "approved": len(approved_ids),
        "approved_document_ids": approved_ids[: args.report_limit],
        "already_approved": already_approved,
        "skipped_not_parsed": skipped_not_parsed,
        "skipped_draft_or_rejected": skipped_draft_or_rejected,
        "skipped_other_status": skipped_other_status,
        "review_error_count": len(errors),
        "review_errors": errors[: args.report_limit],
    }


def enqueue_build_once(args: argparse.Namespace) -> dict[str, Any]:
    build_errors: list[dict[str, Any]] = []
    created_task_ids: list[int] = []

    with SessionLocal() as db:
        project = pipeline.get_project(db, args.project_code)
        operator = pipeline.get_operator(db, args.operator)
        if args.commit:
            created_task_ids, build_errors = pipeline.enqueue_build_window(
                db,
                project.id,
                operator,
                args.max_active_build,
                args.retry_failed_build,
                args.enqueue_limit,
            )
        state = pipeline.summarize_build(db, project.id)
        state["created_build_task_ids"] = created_task_ids[: args.report_limit]
        state["created_build_task_count"] = len(created_task_ids)
        state["build_enqueue_error_count"] = len(build_errors)
        state["build_enqueue_errors"] = build_errors[: args.report_limit]
        return state


def has_remaining_work(review_state: dict[str, Any], build_state: dict[str, Any]) -> bool:
    return any(
        (
            review_state["reviewing_candidates"] > review_state["approved"],
            build_state["build_active_tasks"] > 0,
            build_state["build_ready_to_enqueue"] > 0,
        )
    )


def main() -> int:
    args = parse_args()
    configure_logging(args.report_file)
    started_at = time.monotonic()
    last_emit = 0.0

    try:
        with SessionLocal() as db:
            project = pipeline.get_project(db, args.project_code)
            operator = pipeline.get_operator(db, args.operator)
            queue_state = pipeline.ensure_queue_ready(require_worker=args.commit and not args.allow_no_worker)
            emit(
                "start",
                dry_run=args.dry_run,
                commit=args.commit,
                project_id=project.id,
                project_code=project.code,
                operator_id=operator.id,
                operator_username=operator.username,
                queue_state=queue_state,
                initial_summary=pipeline.final_summary(args.project_code),
            )

        while True:
            review_state = approve_reviewing_once(args)
            build_state = enqueue_build_once(args)
            summary = pipeline.final_summary(args.project_code)
            now = time.monotonic()

            should_emit = (
                review_state["approved"] > 0
                or build_state["created_build_task_count"] > 0
                or now - last_emit >= args.progress_interval
                or not has_remaining_work(review_state, build_state)
            )
            if should_emit:
                emit("progress", review=review_state, build=build_state, summary=summary)
                last_emit = now

            if args.dry_run:
                emit("dry_run_completed", review=review_state, build=build_state, summary=summary)
                return 0
            if not has_remaining_work(review_state, build_state):
                emit("completed", review=review_state, build=build_state, summary=summary)
                return 0
            if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
                raise AppException("等待审核通过与索引构建超时")
            time.sleep(args.poll_interval)
    except Exception as exc:  # noqa: BLE001 - operational script entrypoint logs fatal error for recovery.
        LOGGER.exception("BC2413 approve/build watcher failed: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
