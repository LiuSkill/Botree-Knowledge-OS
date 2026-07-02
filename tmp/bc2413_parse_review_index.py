"""
BC2413 项目资料解析、审核、索引构建一次性编排脚本。

用法示例：
    python tmp\\bc2413_parse_review_index.py --dry-run
    python tmp\\bc2413_parse_review_index.py --commit

说明：
    - 只复用现有 Service 和 RQ Worker，不修改业务代码。
    - 可重复执行；已成功解析、已审核、已索引的文档会自动跳过。
    - 默认处理 MinerU/LibreOffice/文本解析链路支持的资料类型。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.core.redis import get_redis_connection, get_rq_queue
from app.models.document import Document, DocumentVersion
from app.models.index_task import IndexTask
from app.models.project import Project
from app.models.review import ReviewTask
from app.models.user import User
from app.services.document_service import DocumentService
from app.services.index_task_service import IndexTaskService
from app.services.review_service import ReviewService


LOGGER = logging.getLogger("bc2413_parse_review_index")

PARSABLE_FILE_TYPES = (
    "csv",
    "doc",
    "docx",
    "jpg",
    "jpeg",
    "md",
    "pdf",
    "png",
    "ppt",
    "pptx",
    "txt",
    "xls",
    "xlsx",
)
ACTIVE_TASK_STATUSES = ("pending", "running")
FAILED_TASK_STATUSES = ("failed", "canceled")
PARSE_TASK_TYPE = "mineru_parse"
BUILD_TASK_TYPE = "full_build"


@dataclass(frozen=True, slots=True)
class VersionRow:
    document_id: int
    file_name: str
    file_type: str
    version_id: int
    version_no: int
    parse_status: str
    review_status: str
    index_status: str


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


def get_project(db: Session, project_code: str) -> Project:
    project = db.scalar(select(Project).where(Project.code == project_code))
    if project is None:
        raise AppException(f"项目不存在：{project_code}", status_code=404, code=404)
    return project


def get_operator(db: Session, operator_name: str) -> User:
    identity_condition = User.username == operator_name
    if operator_name.isdigit():
        identity_condition = or_(identity_condition, User.id == int(operator_name))
    operator = db.scalar(select(User).where(identity_condition, User.is_deleted.is_(False)))
    if operator is None:
        raise AppException(f"操作人不存在或已删除：{operator_name}", status_code=404, code=404)
    return operator


def ensure_queue_ready(require_worker: bool) -> dict[str, Any]:
    queue = get_rq_queue()
    if queue is None:
        raise AppException("Redis/RQ 未配置，无法投递解析或索引任务", status_code=503, code=503)

    worker_rows: list[tuple[str, str, list[str]]] = []
    connection = get_redis_connection()
    if connection is not None:
        try:
            from rq import Worker

            worker_rows = [
                (worker.name, worker.state, [queue.name for queue in worker.queues])
                for worker in Worker.all(connection=connection)
            ]
        except Exception as exc:  # noqa: BLE001 - 运维脚本只记录 worker 探测失败，不影响队列可用性判断。
            LOGGER.warning("探测 RQ worker 失败: %s", exc)

    if require_worker and not worker_rows:
        raise AppException("当前没有在线 RQ worker，请先启动 backend/worker.py", status_code=503, code=503)

    return {
        "queue": queue.name,
        "queued_jobs": len(queue.jobs),
        "workers": worker_rows,
    }


def list_current_versions(db: Session, project_id: int, parsable_only: bool) -> list[VersionRow]:
    stmt = (
        select(
            Document.id,
            Document.file_name,
            Document.file_type,
            DocumentVersion.id,
            DocumentVersion.version_no,
            DocumentVersion.parse_status,
            DocumentVersion.review_status,
            DocumentVersion.index_status,
        )
        .join(
            DocumentVersion,
            and_(
                DocumentVersion.document_id == Document.id,
                DocumentVersion.version_no == Document.version_no,
            ),
        )
        .where(
            Document.project_id == project_id,
            Document.deleted_at.is_(None),
            Document.is_deleted.is_(False),
        )
        .order_by(Document.id)
    )
    if parsable_only:
        stmt = stmt.where(func.lower(Document.file_type).in_(PARSABLE_FILE_TYPES))

    return [
        VersionRow(
            document_id=row[0],
            file_name=row[1],
            file_type=(row[2] or "").lower(),
            version_id=row[3],
            version_no=row[4],
            parse_status=row[5],
            review_status=row[6],
            index_status=row[7],
        )
        for row in db.execute(stmt).all()
    ]


def unsupported_summary(db: Session, project_id: int) -> dict[str, Any]:
    rows = db.execute(
        select(Document.file_type, func.count(Document.id))
        .where(
            Document.project_id == project_id,
            Document.deleted_at.is_(None),
            Document.is_deleted.is_(False),
            ~func.lower(Document.file_type).in_(PARSABLE_FILE_TYPES),
        )
        .group_by(Document.file_type)
        .order_by(func.count(Document.id).desc())
    ).all()
    by_type = {str(file_type or "").lower(): count for file_type, count in rows}
    return {"unsupported_total": sum(by_type.values()), "unsupported_by_type": by_type}


def latest_tasks_by_version(db: Session, project_id: int, task_type: str) -> dict[tuple[int, int], IndexTask]:
    latest_subquery = (
        select(
            IndexTask.document_id.label("document_id"),
            IndexTask.version_no.label("version_no"),
            func.max(IndexTask.id).label("latest_id"),
        )
        .join(Document, IndexTask.document_id == Document.id)
        .where(Document.project_id == project_id, IndexTask.task_type == task_type)
        .group_by(IndexTask.document_id, IndexTask.version_no)
        .subquery()
    )
    tasks = db.scalars(
        select(IndexTask).join(latest_subquery, IndexTask.id == latest_subquery.c.latest_id)
    ).all()
    return {(task.document_id, task.version_no): task for task in tasks}


def count_active_tasks(db: Session, project_id: int, task_type: str) -> int:
    return int(
        db.scalar(
            select(func.count(IndexTask.id))
            .join(Document, IndexTask.document_id == Document.id)
            .where(
                Document.project_id == project_id,
                IndexTask.task_type == task_type,
                IndexTask.status.in_(ACTIVE_TASK_STATUSES),
            )
        )
        or 0
    )


def summarize_parse(db: Session, project_id: int) -> dict[str, Any]:
    versions = list_current_versions(db, project_id, parsable_only=True)
    task_by_key = latest_tasks_by_version(db, project_id, PARSE_TASK_TYPE)
    ready_to_enqueue = 0
    blocked_by_failed_task = 0
    latest_task_status_counts: dict[str, int] = {}

    for version in versions:
        task = task_by_key.get((version.document_id, version.version_no))
        if task is not None:
            latest_task_status_counts[task.status] = latest_task_status_counts.get(task.status, 0) + 1
        if version.parse_status in {"success", "failed"}:
            continue
        if task is not None and task.status in ACTIVE_TASK_STATUSES:
            continue
        if task is not None and task.status in FAILED_TASK_STATUSES:
            blocked_by_failed_task += 1
            continue
        ready_to_enqueue += 1

    return {
        "parsable_total": len(versions),
        "parse_success": sum(1 for version in versions if version.parse_status == "success"),
        "parse_failed": sum(1 for version in versions if version.parse_status == "failed"),
        "parse_active_tasks": count_active_tasks(db, project_id, PARSE_TASK_TYPE),
        "parse_ready_to_enqueue": ready_to_enqueue,
        "parse_blocked_by_failed_task": blocked_by_failed_task,
        "latest_parse_task_status_counts": latest_task_status_counts,
        **unsupported_summary(db, project_id),
    }


def enqueue_parse_window(
    db: Session,
    project_id: int,
    operator: User,
    max_active: int,
    retry_failed: bool,
    enqueue_limit: int | None,
) -> list[int]:
    active_count = count_active_tasks(db, project_id, PARSE_TASK_TYPE)
    slots = max(0, max_active - active_count)
    if enqueue_limit is not None:
        slots = min(slots, enqueue_limit)
    if slots <= 0:
        return []

    task_by_key = latest_tasks_by_version(db, project_id, PARSE_TASK_TYPE)
    created_task_ids: list[int] = []
    service = IndexTaskService(db)

    for version in list_current_versions(db, project_id, parsable_only=True):
        if len(created_task_ids) >= slots:
            break
        if version.parse_status == "success":
            continue
        task = task_by_key.get((version.document_id, version.version_no))
        if task is not None and task.status in ACTIVE_TASK_STATUSES:
            continue
        if (version.parse_status == "failed" or (task is not None and task.status in FAILED_TASK_STATUSES)) and not retry_failed:
            continue

        created = service.create_parse_task(
            version.document_id,
            version.version_no,
            version.version_id,
            operator,
        )
        created_task_ids.append(created.id)

    return created_task_ids


def wait_for_parse_phase(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.monotonic()
    last_emit = 0.0
    while True:
        with SessionLocal() as db:
            project = get_project(db, args.project_code)
            operator = get_operator(db, args.operator)
            created_task_ids: list[int] = []
            if args.commit:
                created_task_ids = enqueue_parse_window(
                    db,
                    project.id,
                    operator,
                    args.max_active_parse,
                    args.retry_failed_parse,
                    args.enqueue_limit,
                )
            state = summarize_parse(db, project.id)
            state["created_parse_task_ids"] = created_task_ids[: args.report_limit]
            state["created_parse_task_count"] = len(created_task_ids)

        now = time.monotonic()
        if created_task_ids or now - last_emit >= args.progress_interval or state["parse_active_tasks"] == 0:
            emit("parse_progress", **state)
            last_emit = now

        if args.dry_run:
            return state
        if state["parse_active_tasks"] == 0 and state["parse_ready_to_enqueue"] == 0:
            return state
        if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
            raise AppException("等待解析完成超时")
        time.sleep(args.poll_interval)


def get_open_review_task(db: Session, version: VersionRow) -> ReviewTask | None:
    return db.scalar(
        select(ReviewTask)
        .where(
            ReviewTask.document_id == version.document_id,
            ReviewTask.version_id == version.version_id,
            ReviewTask.review_status == "reviewing",
        )
        .order_by(ReviewTask.id.desc())
    )


def submit_and_approve_reviews(args: argparse.Namespace) -> dict[str, Any]:
    submitted = 0
    approved = 0
    already_approved = 0
    skipped_not_parsed = 0
    errors: list[dict[str, Any]] = []

    with SessionLocal() as db:
        project = get_project(db, args.project_code)
        operator = get_operator(db, args.operator)
        review_service = ReviewService(db)

        for version in list_current_versions(db, project.id, parsable_only=True):
            if version.parse_status != "success":
                skipped_not_parsed += 1
                continue
            if version.review_status == "approved":
                already_approved += 1
                continue
            try:
                task: ReviewTask | None
                if version.review_status in {"draft", "rejected"}:
                    task = review_service.submit_review(
                        version.document_id,
                        operator,
                        args.review_comment,
                        version.version_no,
                    )
                    submitted += 1
                else:
                    task = get_open_review_task(db, version)
                if task is None:
                    raise AppException("未找到待审核任务")
                review_service.approve(task.id, operator, args.review_comment)
                approved += 1
            except Exception as exc:  # noqa: BLE001 - 批处理需要记录单项失败并继续推进其他文档。
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
                        "审核处理失败 document_id=%s version_no=%s",
                        version.document_id,
                        version.version_no,
                    )

    result = {
        "submitted": submitted,
        "approved": approved,
        "already_approved": already_approved,
        "skipped_not_parsed": skipped_not_parsed,
        "review_error_count": len(errors),
        "review_errors": errors[: args.report_limit],
    }
    emit("review_completed", **result)
    return result


def summarize_build(db: Session, project_id: int) -> dict[str, Any]:
    versions = [
        version
        for version in list_current_versions(db, project_id, parsable_only=True)
        if version.parse_status == "success" and version.review_status == "approved"
    ]
    task_by_key = latest_tasks_by_version(db, project_id, BUILD_TASK_TYPE)
    ready_to_enqueue = 0
    blocked_by_failed_task = 0
    latest_task_status_counts: dict[str, int] = {}

    for version in versions:
        task = task_by_key.get((version.document_id, version.version_no))
        if task is not None:
            latest_task_status_counts[task.status] = latest_task_status_counts.get(task.status, 0) + 1
        if version.index_status == "indexed":
            continue
        if task is not None and task.status in ACTIVE_TASK_STATUSES:
            continue
        if version.index_status == "failed" or (task is not None and task.status in FAILED_TASK_STATUSES):
            blocked_by_failed_task += 1
            continue
        ready_to_enqueue += 1

    return {
        "build_target_total": len(versions),
        "index_success": sum(1 for version in versions if version.index_status == "indexed"),
        "index_failed": sum(1 for version in versions if version.index_status == "failed"),
        "build_active_tasks": count_active_tasks(db, project_id, BUILD_TASK_TYPE),
        "build_ready_to_enqueue": ready_to_enqueue,
        "build_blocked_by_failed_task": blocked_by_failed_task,
        "latest_build_task_status_counts": latest_task_status_counts,
    }


def enqueue_build_window(
    db: Session,
    project_id: int,
    operator: User,
    max_active: int,
    retry_failed: bool,
    enqueue_limit: int | None,
) -> tuple[list[int], list[dict[str, Any]]]:
    active_count = count_active_tasks(db, project_id, BUILD_TASK_TYPE)
    slots = max(0, max_active - active_count)
    if enqueue_limit is not None:
        slots = min(slots, enqueue_limit)
    if slots <= 0:
        return [], []

    task_by_key = latest_tasks_by_version(db, project_id, BUILD_TASK_TYPE)
    created_task_ids: list[int] = []
    errors: list[dict[str, Any]] = []
    document_service = DocumentService(db)

    for version in list_current_versions(db, project_id, parsable_only=True):
        if len(created_task_ids) >= slots:
            break
        if version.parse_status != "success" or version.review_status != "approved":
            continue
        if version.index_status == "indexed":
            continue
        task = task_by_key.get((version.document_id, version.version_no))
        if task is not None and task.status in ACTIVE_TASK_STATUSES:
            continue
        if (version.index_status == "failed" or (task is not None and task.status in FAILED_TASK_STATUSES)) and not retry_failed:
            continue
        try:
            created = document_service.create_index_build_task(
                version.document_id,
                operator,
                version.version_no,
            )
            created_task_ids.append(created.id)
        except Exception as exc:  # noqa: BLE001 - 批量投递时记录单项失败，避免影响其他文档。
            db.rollback()
            errors.append(
                {
                    "document_id": version.document_id,
                    "version_no": version.version_no,
                    "file_name": version.file_name,
                    "error": str(exc),
                }
            )
            if len(errors) > 20:
                break

    return created_task_ids, errors


def wait_for_build_phase(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.monotonic()
    last_emit = 0.0
    build_errors: list[dict[str, Any]] = []

    while True:
        with SessionLocal() as db:
            project = get_project(db, args.project_code)
            operator = get_operator(db, args.operator)
            created_task_ids: list[int] = []
            enqueue_errors: list[dict[str, Any]] = []
            if args.commit:
                created_task_ids, enqueue_errors = enqueue_build_window(
                    db,
                    project.id,
                    operator,
                    args.max_active_build,
                    args.retry_failed_build,
                    args.enqueue_limit,
                )
                build_errors.extend(enqueue_errors)
            state = summarize_build(db, project.id)
            state["created_build_task_ids"] = created_task_ids[: args.report_limit]
            state["created_build_task_count"] = len(created_task_ids)
            state["build_enqueue_error_count"] = len(build_errors)
            state["build_enqueue_errors"] = build_errors[: args.report_limit]

        now = time.monotonic()
        if created_task_ids or now - last_emit >= args.progress_interval or state["build_active_tasks"] == 0:
            emit("build_progress", **state)
            last_emit = now

        if args.dry_run:
            return state
        if (
            state["build_active_tasks"] == 0
            and state["build_ready_to_enqueue"] == 0
            and not build_errors
        ):
            return state
        if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
            raise AppException("等待索引构建完成超时")
        if build_errors and state["build_active_tasks"] == 0:
            return state
        time.sleep(args.poll_interval)


def final_summary(project_code: str) -> dict[str, Any]:
    with SessionLocal() as db:
        project = get_project(db, project_code)
        parse_state = summarize_parse(db, project.id)
        build_state = summarize_build(db, project.id)
        review_rows = db.execute(
            select(DocumentVersion.review_status, func.count(DocumentVersion.id))
            .join(
                Document,
                and_(
                    Document.id == DocumentVersion.document_id,
                    Document.version_no == DocumentVersion.version_no,
                ),
            )
            .where(
                Document.project_id == project.id,
                Document.deleted_at.is_(None),
                Document.is_deleted.is_(False),
                func.lower(Document.file_type).in_(PARSABLE_FILE_TYPES),
            )
            .group_by(DocumentVersion.review_status)
        ).all()
        return {
            "project_id": project.id,
            "project_code": project.code,
            "parse": parse_state,
            "build": build_state,
            "review_status_counts": {status: count for status, count in review_rows},
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BC2413 项目资料解析、审核、索引构建编排脚本")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只输出计划，不写库、不投递任务")
    mode.add_argument("--commit", action="store_true", help="真实执行解析、审核和索引构建")
    parser.add_argument("--project-code", default="BC2413", help="项目编号")
    parser.add_argument("--operator", default="admin", help="操作人用户名或用户ID")
    parser.add_argument("--poll-interval", type=int, default=30, help="轮询间隔秒数")
    parser.add_argument("--progress-interval", type=int, default=120, help="无新任务时的进度日志间隔秒数")
    parser.add_argument("--max-wait-seconds", type=int, default=0, help="最大等待秒数，0 表示不限制")
    parser.add_argument("--max-active-parse", type=int, default=25, help="解析任务最大 pending/running 数")
    parser.add_argument("--max-active-build", type=int, default=10, help="索引任务最大 pending/running 数")
    parser.add_argument("--enqueue-limit", type=int, default=None, help="单轮最多新投递任务数")
    parser.add_argument("--retry-failed-parse", action="store_true", help="重新投递失败的解析任务")
    parser.add_argument("--retry-failed-build", action="store_true", help="重新投递失败的索引任务")
    parser.add_argument("--allow-no-worker", action="store_true", help="允许没有在线 worker 时继续投递任务")
    parser.add_argument(
        "--review-comment",
        default="BC2413 项目资料批量解析完成后自动审核通过",
        help="批量审核意见",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=REPO_ROOT / "tmp" / "bc2413_parse_review_index_report.jsonl",
        help="JSONL 运行报告文件",
    )
    parser.add_argument("--report-limit", type=int, default=20, help="日志中最多展示的任务ID或错误条数")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.report_file)

    try:
        with SessionLocal() as db:
            project = get_project(db, args.project_code)
            operator = get_operator(db, args.operator)
            queue_state = ensure_queue_ready(require_worker=args.commit and not args.allow_no_worker)
            emit(
                "start",
                dry_run=args.dry_run,
                commit=args.commit,
                project_id=project.id,
                project_code=project.code,
                operator_id=operator.id,
                operator_username=operator.username,
                queue_state=queue_state,
                initial_summary=final_summary(args.project_code),
            )

        parse_state = wait_for_parse_phase(args)
        if args.dry_run:
            emit("dry_run_completed", parse=parse_state)
            return 0

        review_state = submit_and_approve_reviews(args)
        build_state = wait_for_build_phase(args)
        summary = final_summary(args.project_code)
        emit("completed", review=review_state, build=build_state, final_summary=summary)

        has_failures = (
            summary["parse"]["parse_failed"] > 0
            or summary["parse"]["parse_blocked_by_failed_task"] > 0
            or summary["build"]["index_failed"] > 0
            or summary["build"]["build_blocked_by_failed_task"] > 0
            or review_state["review_error_count"] > 0
            or build_state.get("build_enqueue_error_count", 0) > 0
        )
        return 2 if has_failures else 0
    except Exception as exc:  # noqa: BLE001 - 脚本入口统一记录失败并返回非零退出码。
        LOGGER.exception("BC2413 项目资料解析审核索引脚本执行失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
