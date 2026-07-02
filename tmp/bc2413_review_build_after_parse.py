"""
BC2413 项目资料解析收口后自动审核并构建索引的编排脚本。

用途：
    - 只监听解析阶段是否真正结束，不主动投递新的解析任务。
    - 当解析队列清空且无剩余可投递解析任务后，自动批量提交审核并通过。
    - 审核完成后按小窗口投递 full_build 索引任务，直到索引构建结束。

示例：
    python tmp\\bc2413_review_build_after_parse.py --dry-run
    python tmp\\bc2413_review_build_after_parse.py --commit
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

from app.core.database import SessionLocal
from app.core.exceptions import AppException

import bc2413_parse_only as parse_only
import bc2413_parse_review_index as pipeline


LOGGER = logging.getLogger("bc2413_review_build_after_parse")


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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="BC2413 解析完成后自动审核并构建索引")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="只输出计划，不写库、不投递任务")
    mode.add_argument("--commit", action="store_true", help="真实执行审核和索引构建")
    parser.add_argument("--project-code", default="BC2413", help="项目编号")
    parser.add_argument("--operator", default="admin", help="操作人用户名或用户ID")
    parser.add_argument("--poll-interval", type=int, default=30, help="轮询间隔秒数")
    parser.add_argument("--progress-interval", type=int, default=180, help="进度日志间隔秒数")
    parser.add_argument("--max-wait-seconds", type=int, default=0, help="最大等待秒数，0 表示不限制")
    parser.add_argument("--max-active-build", type=int, default=1, help="索引构建最大 pending/running 数")
    parser.add_argument("--enqueue-limit", type=int, default=1, help="单轮最多新投递索引任务数")
    parser.add_argument("--retry-failed-build", action="store_true", help="重新投递失败的索引任务")
    parser.add_argument("--allow-no-worker", action="store_true", help="允许没有在线 worker 时继续投递任务")
    parser.add_argument(
        "--review-comment",
        default="BC2413 项目资料解析完成后自动审核通过",
        help="批量审核意见",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=REPO_ROOT / "tmp" / "bc2413_parse_only_state.json",
        help="解析脚本的状态文件，用于识别已重试过的失败文档",
    )
    parser.add_argument(
        "--report-file",
        type=Path,
        default=REPO_ROOT / "tmp" / "bc2413_review_build_after_parse_report.jsonl",
        help="JSONL 运行报告文件",
    )
    parser.add_argument("--report-limit", type=int, default=20, help="日志中最多展示的任务ID或错误条数")
    return parser.parse_args()


def summarize_parse_wait(args: argparse.Namespace) -> dict[str, Any]:
    state = parse_only.load_state(args.state_file)
    retried_versions = set(state.get("retried_versions") or [])
    with SessionLocal() as db:
        project = pipeline.get_project(db, args.project_code)
        summary = parse_only.summarize_parse(db, project.id, retried_versions, retry_transient_failed=True)
    summary["retried_version_count"] = len(retried_versions)
    return summary


def wait_for_parse_completion(args: argparse.Namespace) -> dict[str, Any]:
    started_at = time.monotonic()
    last_emit = 0.0

    while True:
        summary = summarize_parse_wait(args)
        now = time.monotonic()

        if now - last_emit >= args.progress_interval or summary["parse_active_tasks"] == 0:
            emit("wait_parse", summary=summary)
            last_emit = now

        if args.dry_run:
            return summary
        if summary["parse_active_tasks"] == 0 and summary["parse_ready_to_enqueue"] == 0:
            return summary
        if args.max_wait_seconds and now - started_at > args.max_wait_seconds:
            raise AppException("等待解析阶段收口超时")
        time.sleep(args.poll_interval)


def main() -> int:
    args = parse_args()
    configure_logging(args.report_file)

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
                parse_wait_summary=summarize_parse_wait(args),
            )

        parse_state = wait_for_parse_completion(args)
        if args.dry_run:
            emit("dry_run_completed", parse=parse_state)
            return 0
        emit("parse_completed", summary=parse_state)

        review_state = pipeline.submit_and_approve_reviews(args)
        build_state = pipeline.wait_for_build_phase(args)
        summary = pipeline.final_summary(args.project_code)
        emit("completed", parse=parse_state, review=review_state, build=build_state, final_summary=summary)

        has_failures = (
            parse_state["parse_failed"] > 0
            or parse_state["permanent_or_exhausted_failed"] > 0
            or summary["build"]["index_failed"] > 0
            or summary["build"]["build_blocked_by_failed_task"] > 0
            or review_state["review_error_count"] > 0
            or build_state.get("build_enqueue_error_count", 0) > 0
        )
        return 2 if has_failures else 0
    except Exception as exc:  # noqa: BLE001 - 运维脚本入口统一记录失败，方便恢复后继续执行。
        LOGGER.exception("BC2413 解析后审核与索引脚本执行失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
