"""
BC2413 项目资料解析专用脚本。

用途：
    - 只推进 MinerU 解析任务，不提交审核、不构建索引。
    - 支持把显存/服务异常导致的失败文档按状态文件最多重试一次。

示例：
    python tmp\\bc2413_parse_only.py --commit --max-active-parse 1 --enqueue-limit 1 --retry-transient-failed
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
from app.models.index_task import IndexTask
from app.services.index_task_service import IndexTaskService


LOGGER = logging.getLogger("bc2413_parse_only")

TRANSIENT_FAILURE_KEYWORDS = (
    "Engine core initialization failed",
    "EngineCore encountered an issue",
    "Task not found",
    "MinerU解析任务超时",
    "MinerU解析响应页面为空",
    "MinerU任务提交失败",
    "Connection",
    "Data too long for column",
)

PERMANENT_FAILURE_KEYWORDS: tuple[str, ...] = ()


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


def load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"retried_versions": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("解析重试状态文件格式异常，重新创建: path=%s", path)
        return {"retried_versions": []}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def version_key(document_id: int, version_no: int) -> str:
    return f"{document_id}:{version_no}"


def is_transient_parse_failure(task: IndexTask | None) -> bool:
    if task is None:
        return False
    message = task.error_message or ""
    if any(keyword in message for keyword in PERMANENT_FAILURE_KEYWORDS):
        return False
    return any(keyword in message for keyword in TRANSIENT_FAILURE_KEYWORDS)


def summarize_parse(db: Any, project_id: int, retried_versions: set[str], retry_transient_failed: bool) -> dict[str, Any]:
    versions = pipeline.list_current_versions(db, project_id, parsable_only=True)
    task_by_key = pipeline.latest_tasks_by_version(db, project_id, pipeline.PARSE_TASK_TYPE)
    ready_to_enqueue = 0
    retriable_failed = 0
    permanent_failed = 0
    latest_task_status_counts: dict[str, int] = {}

    for version in versions:
        task = task_by_key.get((version.document_id, version.version_no))
        if task is not None:
            latest_task_status_counts[task.status] = latest_task_status_counts.get(task.status, 0) + 1
        if version.parse_status == "success":
            continue
        if task is not None and task.status in pipeline.ACTIVE_TASK_STATUSES:
            continue
        if version.parse_status == "failed":
            key = version_key(version.document_id, version.version_no)
            if retry_transient_failed and key not in retried_versions and is_transient_parse_failure(task):
                retriable_failed += 1
                ready_to_enqueue += 1
            else:
                permanent_failed += 1
            continue
        if task is not None and task.status in pipeline.FAILED_TASK_STATUSES:
            permanent_failed += 1
            continue
        ready_to_enqueue += 1

    return {
        "parsable_total": len(versions),
        "parse_success": sum(1 for version in versions if version.parse_status == "success"),
        "parse_failed": sum(1 for version in versions if version.parse_status == "failed"),
        "parse_active_tasks": pipeline.count_active_tasks(db, project_id, pipeline.PARSE_TASK_TYPE),
        "parse_ready_to_enqueue": ready_to_enqueue,
        "retriable_failed_remaining": retriable_failed,
        "permanent_or_exhausted_failed": permanent_failed,
        "latest_parse_task_status_counts": latest_task_status_counts,
        **pipeline.unsupported_summary(db, project_id),
    }


def enqueue_parse_window(
    db: Any,
    project_id: int,
    operator: Any,
    max_active: int,
    enqueue_limit: int | None,
    retry_transient_failed: bool,
    state_path: Path,
    state: dict[str, Any],
) -> list[int]:
    active_count = pipeline.count_active_tasks(db, project_id, pipeline.PARSE_TASK_TYPE)
    slots = max(0, max_active - active_count)
    if enqueue_limit is not None:
        slots = min(slots, enqueue_limit)
    if slots <= 0:
        return []

    retried_versions = set(state.get("retried_versions") or [])
    task_by_key = pipeline.latest_tasks_by_version(db, project_id, pipeline.PARSE_TASK_TYPE)
    service = IndexTaskService(db)
    created_task_ids: list[int] = []

    versions = pipeline.list_current_versions(db, project_id, parsable_only=True)
    ordered_versions = [
        *(version for version in versions if version.parse_status != "failed"),
        *(version for version in versions if version.parse_status == "failed"),
    ]

    for version in ordered_versions:
        if len(created_task_ids) >= slots:
            break
        if version.parse_status == "success":
            continue

        key = version_key(version.document_id, version.version_no)
        task = task_by_key.get((version.document_id, version.version_no))
        if task is not None and task.status in pipeline.ACTIVE_TASK_STATUSES:
            continue

        if version.parse_status == "failed":
            if not retry_transient_failed or key in retried_versions or not is_transient_parse_failure(task):
                continue
            retried_versions.add(key)
            state["retried_versions"] = sorted(retried_versions)
            save_state(state_path, state)
        elif task is not None and task.status in pipeline.FAILED_TASK_STATUSES:
            continue

        created = service.create_parse_task(
            version.document_id,
            version.version_no,
            version.version_id,
            operator,
        )
        created_task_ids.append(created.id)

    return created_task_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BC2413 项目资料解析专用脚本")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只输出计划，不写库、不投递任务")
    mode.add_argument("--commit", action="store_true", help="真实投递解析任务")
    parser.add_argument("--project-code", default="BC2413", help="项目编号")
    parser.add_argument("--operator", default="admin", help="操作人用户名或用户ID")
    parser.add_argument("--poll-interval", type=int, default=45, help="轮询间隔秒数")
    parser.add_argument("--progress-interval", type=int, default=180, help="进度日志间隔秒数")
    parser.add_argument("--max-wait-seconds", type=int, default=0, help="最大等待秒数，0 表示不限制")
    parser.add_argument("--max-active-parse", type=int, default=1, help="解析任务最大 pending/running 数")
    parser.add_argument("--enqueue-limit", type=int, default=1, help="单轮最多新投递解析任务数")
    parser.add_argument("--retry-transient-failed", action="store_true", help="对显存/引擎/超时类失败最多重试一次")
    parser.add_argument("--allow-no-worker", action="store_true", help="允许没有在线 worker 时继续投递任务")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=REPO_ROOT / "tmp" / "bc2413_parse_only_state.json",
        help="记录本轮已重试失败文档，避免无限重试",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=REPO_ROOT / "tmp" / "bc2413_parse_only_report.jsonl",
        help="JSONL 运行报告文件",
    )
    parser.add_argument("--report-limit", type=int, default=20, help="日志中最多展示的任务ID")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.report_file)
    started_at = time.monotonic()
    last_emit = 0.0
    state = load_state(args.state_file)

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
                retry_transient_failed=args.retry_transient_failed,
                retried_version_count=len(state.get("retried_versions") or []),
                initial_summary=summarize_parse(
                    db,
                    project.id,
                    set(state.get("retried_versions") or []),
                    args.retry_transient_failed,
                ),
            )

        while True:
            with SessionLocal() as db:
                project = pipeline.get_project(db, args.project_code)
                operator = pipeline.get_operator(db, args.operator)
                created_task_ids: list[int] = []
                if args.commit:
                    created_task_ids = enqueue_parse_window(
                        db,
                        project.id,
                        operator,
                        args.max_active_parse,
                        args.enqueue_limit,
                        args.retry_transient_failed,
                        args.state_file,
                        state,
                    )
                summary = summarize_parse(
                    db,
                    project.id,
                    set(state.get("retried_versions") or []),
                    args.retry_transient_failed,
                )
                summary["created_parse_task_ids"] = created_task_ids[: args.report_limit]
                summary["created_parse_task_count"] = len(created_task_ids)
                summary["retried_version_count"] = len(state.get("retried_versions") or [])

            now = time.monotonic()
            if created_task_ids or now - last_emit >= args.progress_interval or summary["parse_active_tasks"] == 0:
                emit("parse_progress", **summary)
                last_emit = now

            if args.dry_run:
                emit("dry_run_completed", summary=summary)
                return 0
            if summary["parse_active_tasks"] == 0 and summary["parse_ready_to_enqueue"] == 0:
                emit("completed", summary=summary)
                return 0
            if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
                raise AppException("等待解析完成超时")
            time.sleep(args.poll_interval)
    except Exception as exc:  # noqa: BLE001 - 运维脚本入口统一记录失败，方便恢复后继续执行。
        LOGGER.exception("BC2413 解析专用脚本执行失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
