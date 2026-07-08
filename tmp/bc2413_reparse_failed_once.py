"""
BC2413 失败文档单次重跑脚本。

用途：
1. 仅针对当前处于失败态或最新解析任务失败/取消的文档重新投递解析任务。
2. 每个文档在本轮最多再尝试一次；成功则收口，失败则保留失败态交由人工处理。
3. 默认按 1 个 running + 1 个 pending 的节奏连续喂任务，避免队列断档。
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


LOGGER = logging.getLogger("bc2413_reparse_failed_once")


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
        return {"attempted_versions": []}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        LOGGER.warning("状态文件格式异常，重新初始化: path=%s", path)
        return {"attempted_versions": []}


def save_state(path: Path, state: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def version_key(document_id: int, version_no: int) -> str:
    return f"{document_id}:{version_no}"


def is_failed_candidate(version: pipeline.VersionRow, task: IndexTask | None) -> bool:
    if version.parse_status == "failed":
        return True
    return task is not None and task.status in pipeline.FAILED_TASK_STATUSES


def summarize_failed_reparse(db: Any, project_id: int, attempted_versions: set[str]) -> dict[str, Any]:
    versions = pipeline.list_current_versions(db, project_id, parsable_only=True)
    task_by_key = pipeline.latest_tasks_by_version(db, project_id, pipeline.PARSE_TASK_TYPE)
    target_total = 0
    ready_to_enqueue = 0
    attempted_unresolved = 0
    active_candidates = 0
    latest_task_status_counts: dict[str, int] = {}

    for version in versions:
        task = task_by_key.get((version.document_id, version.version_no))
        if task is not None:
            latest_task_status_counts[task.status] = latest_task_status_counts.get(task.status, 0) + 1
        if not is_failed_candidate(version, task):
            continue
        target_total += 1
        if task is not None and task.status in pipeline.ACTIVE_TASK_STATUSES:
            active_candidates += 1
            continue
        key = version_key(version.document_id, version.version_no)
        if key in attempted_versions:
            attempted_unresolved += 1
        else:
            ready_to_enqueue += 1

    return {
        "failed_target_total": target_total,
        "failed_reparse_success_delta": sum(1 for version in versions if version.parse_status == "success"),
        "failed_reparse_active_candidates": active_candidates,
        "failed_reparse_ready_to_enqueue": ready_to_enqueue,
        "failed_reparse_attempted_unresolved": attempted_unresolved,
        "parse_active_tasks": pipeline.count_active_tasks(db, project_id, pipeline.PARSE_TASK_TYPE),
        "latest_parse_task_status_counts": latest_task_status_counts,
        **pipeline.unsupported_summary(db, project_id),
    }


def enqueue_failed_reparse_window(
    db: Any,
    project_id: int,
    operator: Any,
    attempted_versions: set[str],
    state_path: Path,
    state: dict[str, Any],
    max_active: int,
    enqueue_limit: int | None,
) -> list[int]:
    active_count = pipeline.count_active_tasks(db, project_id, pipeline.PARSE_TASK_TYPE)
    slots = max(0, max_active - active_count)
    if enqueue_limit is not None:
        slots = min(slots, enqueue_limit)
    if slots <= 0:
        return []

    task_by_key = pipeline.latest_tasks_by_version(db, project_id, pipeline.PARSE_TASK_TYPE)
    service = IndexTaskService(db)
    created_task_ids: list[int] = []

    for version in pipeline.list_current_versions(db, project_id, parsable_only=True):
        if len(created_task_ids) >= slots:
            break

        task = task_by_key.get((version.document_id, version.version_no))
        if not is_failed_candidate(version, task):
            continue
        if task is not None and task.status in pipeline.ACTIVE_TASK_STATUSES:
            continue

        key = version_key(version.document_id, version.version_no)
        if key in attempted_versions:
            continue

        created = service.create_parse_task(
            version.document_id,
            version.version_no,
            version.version_id,
            operator,
        )
        created_task_ids.append(created.id)
        attempted_versions.add(key)
        state["attempted_versions"] = sorted(attempted_versions)
        save_state(state_path, state)

    return created_task_ids


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BC2413 失败文档单次重跑脚本")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只输出计划，不写库、不投递任务")
    mode.add_argument("--commit", action="store_true", help="真实投递失败文档重跑任务")
    parser.add_argument("--project-code", default="BC2413", help="项目编号")
    parser.add_argument("--operator", default="admin", help="操作人用户名或用户 ID")
    parser.add_argument("--poll-interval", type=int, default=15, help="轮询间隔秒数")
    parser.add_argument("--progress-interval", type=int, default=120, help="进度日志间隔秒数")
    parser.add_argument("--max-wait-seconds", type=int, default=0, help="最大等待秒数，0 表示不限制")
    parser.add_argument("--max-active-parse", type=int, default=2, help="解析任务最大 pending/running 数")
    parser.add_argument("--enqueue-limit", type=int, default=2, help="单轮最多新投递解析任务数")
    parser.add_argument("--allow-no-worker", action="store_true", help="允许没有在线 worker 时继续投递任务")
    parser.add_argument(
        "--state-file",
        type=Path,
        default=TMP_ROOT / "bc2413_reparse_failed_once_state.json",
        help="记录本轮已经重跑过的失败文档，避免无限循环",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=TMP_ROOT / "bc2413_reparse_failed_once_report.jsonl",
        help="JSONL 运行报告文件",
    )
    parser.add_argument("--report-limit", type=int, default=20, help="日志中最多展示的任务 ID")
    parser.add_argument("--reset-state", action="store_true", help="开始前清空本轮状态文件，重新完整重跑失败文档")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    configure_logging(args.report_file)
    started_at = time.monotonic()
    last_emit = 0.0

    if args.reset_state and args.state_file.exists():
        args.state_file.unlink()

    state = load_state(args.state_file)
    attempted_versions = set(state.get("attempted_versions") or [])

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
                attempted_version_count=len(attempted_versions),
                initial_summary=summarize_failed_reparse(db, project.id, attempted_versions),
            )

        while True:
            with SessionLocal() as db:
                project = pipeline.get_project(db, args.project_code)
                operator = pipeline.get_operator(db, args.operator)
                created_task_ids: list[int] = []
                if args.commit:
                    created_task_ids = enqueue_failed_reparse_window(
                        db,
                        project.id,
                        operator,
                        attempted_versions,
                        args.state_file,
                        state,
                        args.max_active_parse,
                        args.enqueue_limit,
                    )
                summary = summarize_failed_reparse(db, project.id, attempted_versions)
                summary["created_parse_task_ids"] = created_task_ids[: args.report_limit]
                summary["created_parse_task_count"] = len(created_task_ids)
                summary["attempted_version_count"] = len(attempted_versions)

            now = time.monotonic()
            if created_task_ids or now - last_emit >= args.progress_interval or summary["parse_active_tasks"] == 0:
                emit("reparse_progress", **summary)
                last_emit = now

            if args.dry_run:
                emit("dry_run_completed", summary=summary)
                return 0
            if summary["parse_active_tasks"] == 0 and summary["failed_reparse_ready_to_enqueue"] == 0:
                emit("completed", summary=summary)
                return 0
            if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
                raise AppException("等待失败文档单次重跑完成超时")
            time.sleep(args.poll_interval)
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("BC2413 失败文档单次重跑脚本执行失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
