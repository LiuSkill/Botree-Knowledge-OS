"""
BC2413 已解析文档审核与索引构建并行推进脚本。

用途：
    - 和 tmp/bc2413_parse_review_index.py 的解析阶段并行运行。
    - 周期性把已解析成功的版本提交审核并自动通过。
    - 按小窗口投递 full_build 索引任务，避免一次性压垮队列。

示例：
    python tmp\\bc2413_review_build_parallel.py --commit --max-active-build 1 --enqueue-limit 1
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

from sqlalchemy import func, select

import bc2413_parse_review_index as pipeline
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.models.document import Document, DocumentVersion
from app.models.index_task import IndexTask


LOGGER = logging.getLogger("bc2413_review_build_parallel")


def configure_logging(report_file: Path | None) -> None:
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


def review_counts(project_id: int) -> dict[str, int]:
    with SessionLocal() as db:
        rows = db.execute(
            select(DocumentVersion.review_status, func.count(DocumentVersion.id))
            .join(Document, DocumentVersion.document_id == Document.id)
            .where(
                Document.project_id == project_id,
                Document.deleted_at.is_(None),
                Document.is_deleted.is_(False),
                DocumentVersion.version_no == Document.version_no,
                func.lower(Document.file_type).in_(pipeline.PARSABLE_FILE_TYPES),
            )
            .group_by(DocumentVersion.review_status)
        ).all()
    return {str(status): int(count) for status, count in rows}


def active_task_counts(project_id: int) -> dict[str, int]:
    with SessionLocal() as db:
        rows = db.execute(
            select(IndexTask.task_type, IndexTask.status, func.count(IndexTask.id))
            .join(Document, IndexTask.document_id == Document.id)
            .where(Document.project_id == project_id)
            .group_by(IndexTask.task_type, IndexTask.status)
        ).all()
    return {f"{task_type}:{status}": int(count) for task_type, status, count in rows}


def has_remaining_work(summary: dict[str, Any], build_state: dict[str, Any]) -> bool:
    parse_state = summary["parse"]
    return any(
        (
            parse_state["parse_active_tasks"] > 0,
            parse_state["parse_ready_to_enqueue"] > 0,
            build_state["build_active_tasks"] > 0,
            build_state["build_ready_to_enqueue"] > 0,
        )
    )


def run_review_and_build_once(args: argparse.Namespace) -> dict[str, Any]:
    if args.commit:
        review_state = pipeline.submit_and_approve_reviews(args)
    else:
        review_state = {"dry_run": True}

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
        build_state = pipeline.summarize_build(db, project.id)
        build_state["created_build_task_ids"] = created_task_ids[: args.report_limit]
        build_state["created_build_task_count"] = len(created_task_ids)
        build_state["build_enqueue_error_count"] = len(build_errors)
        build_state["build_enqueue_errors"] = build_errors[: args.report_limit]

    return {"review": review_state, "build": build_state}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BC2413 已解析文档审核与索引构建并行推进脚本")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只输出计划，不写库、不投递任务")
    mode.add_argument("--commit", action="store_true", help="真实执行审核和索引构建")
    parser.add_argument("--project-code", default="BC2413", help="项目编号")
    parser.add_argument("--operator", default="admin", help="操作人用户名或用户ID")
    parser.add_argument("--poll-interval", type=int, default=60, help="轮询间隔秒数")
    parser.add_argument("--progress-interval", type=int, default=180, help="进度日志间隔秒数")
    parser.add_argument("--max-wait-seconds", type=int, default=0, help="最大等待秒数，0 表示不限制")
    parser.add_argument("--max-active-build", type=int, default=1, help="索引构建最大 pending/running 数")
    parser.add_argument("--enqueue-limit", type=int, default=1, help="单轮最多新投递索引任务数")
    parser.add_argument("--retry-failed-build", action="store_true", help="重新投递失败的索引任务")
    parser.add_argument("--allow-no-worker", action="store_true", help="允许没有在线 worker 时继续投递任务")
    parser.add_argument(
        "--review-comment",
        default="BC2413 项目资料解析成功后自动审核通过并构建索引",
        help="批量审核意见",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=REPO_ROOT / "tmp" / "bc2413_review_build_parallel_report.jsonl",
        help="JSONL 运行报告文件",
    )
    parser.add_argument("--report-limit", type=int, default=20, help="日志中最多展示的任务ID或错误条数")
    return parser.parse_args()


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
                review_counts=review_counts(project.id),
                task_counts=active_task_counts(project.id),
            )

        while True:
            state = run_review_and_build_once(args)
            summary = pipeline.final_summary(args.project_code)
            with SessionLocal() as db:
                project = pipeline.get_project(db, args.project_code)
                review_state = review_counts(project.id)
                task_state = active_task_counts(project.id)

            now = time.monotonic()
            should_emit = (
                state["build"].get("created_build_task_count", 0) > 0
                or now - last_emit >= args.progress_interval
                or not has_remaining_work(summary, state["build"])
            )
            if should_emit:
                emit(
                    "progress",
                    review=state["review"],
                    build=state["build"],
                    summary=summary,
                    review_counts=review_state,
                    task_counts=task_state,
                )
                last_emit = now

            if args.dry_run:
                emit("dry_run_completed", summary=summary)
                return 0
            if not has_remaining_work(summary, state["build"]):
                emit("completed", summary=summary, review_counts=review_state, task_counts=task_state)
                return 0
            if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
                raise AppException("等待审核与索引构建并行推进超时")
            time.sleep(args.poll_interval)
    except Exception as exc:  # noqa: BLE001 - 运维脚本入口统一记录失败，方便恢复后继续执行。
        LOGGER.exception("BC2413 审核与索引并行推进失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
