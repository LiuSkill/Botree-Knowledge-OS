"""
BC2413 解析连续执行 supervisor。

职责：
1. 接管并启动单 worker + 解析投递脚本，维持“1 个 running + 1 个 pending”的连续队列。
2. 不重试失败文档；失败文档直接标记为人工处理，继续推进后续文档。
3. 监控 MinerU 超时/404/Read timed out 等卡死信号，必要时中止当前任务并重启 worker。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import subprocess
import sys
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
TMP_ROOT = REPO_ROOT / "tmp"
BACKEND_ROOT = REPO_ROOT / "backend"
sys.path.insert(0, str(TMP_ROOT))
sys.path.insert(0, str(BACKEND_ROOT))

import bc2413_parse_only as parse_only
import bc2413_parse_review_index as pipeline
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.models.document import Document, DocumentVersion
from app.models.index_task import IndexTask
from app.models.user import User
from app.services.system_service import SystemService
from app.utils.time_utils import now_utc


LOGGER = logging.getLogger("bc2413_parse_supervisor")
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
PARSE_TASK_TYPE = pipeline.PARSE_TASK_TYPE

READ_TIMEOUT_TOKEN = "Read timed out"
TASK_NOT_FOUND_TOKEN = "Task not found"
TASK_404_TOKEN = 'status_code=404 body={"detail":"Task not found"}'
MINERU_TIMEOUT_TOKEN = "MinerU解析任务超时"
TASK_ID_PATTERN = re.compile(r"task_id=([0-9a-fA-F-]{36})")


@dataclass(slots=True)
class ManagedProcess:
    name: str
    command: list[str]
    cwd: Path
    stdout_path: Path
    stderr_path: Path
    process: subprocess.Popen[str] | None = None


@dataclass(slots=True)
class RunningTask:
    task_id: int
    document_id: int
    version_id: int | None
    version_no: int
    file_name: str
    started_at: Any


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
    parser = argparse.ArgumentParser(description="BC2413 连续解析 supervisor")
    parser.add_argument("--project-code", default="BC2413", help="项目编号")
    parser.add_argument("--operator", default="admin", help="操作人用户名或 ID")
    parser.add_argument("--poll-interval", type=int, default=15, help="supervisor 巡检间隔秒数")
    parser.add_argument("--progress-interval", type=int, default=180, help="supervisor 进度日志间隔秒数")
    parser.add_argument("--worker-hard-timeout-seconds", type=int, default=360, help="单文档运行超出该阈值直接转人工")
    parser.add_argument("--read-timeout-threshold", type=int, default=3, help="同一文档连续 Read timed out 次数达到后转人工")
    parser.add_argument("--task-not-found-threshold", type=int, default=2, help="同一文档连续 Task not found 次数达到后转人工")
    parser.add_argument("--worker-stdout", type=Path, default=TMP_ROOT / "bc2413_worker_live.out.log", help="worker stdout 日志")
    parser.add_argument("--worker-stderr", type=Path, default=TMP_ROOT / "bc2413_worker_live.err.log", help="worker stderr 日志")
    parser.add_argument("--parse-stdout", type=Path, default=TMP_ROOT / "bc2413_parse_only_live.out.log", help="解析投递脚本 stdout 日志")
    parser.add_argument("--parse-stderr", type=Path, default=TMP_ROOT / "bc2413_parse_only_live.err.log", help="解析投递脚本 stderr 日志")
    parser.add_argument(
        "--report-file",
        type=Path,
        default=TMP_ROOT / "bc2413_parse_supervisor_report.jsonl",
        help="supervisor JSONL 运行报告",
    )
    parser.add_argument("--state-file", type=Path, default=TMP_ROOT / "bc2413_parse_only_state.json", help="沿用解析脚本状态文件")
    return parser.parse_args()


def powershell_json(command: str) -> list[dict[str, Any]]:
    completed = subprocess.run(
        ["powershell", "-NoProfile", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=30,
        check=False,
    )
    stdout = completed.stdout.strip()
    if completed.returncode != 0 or not stdout:
        return []
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return []
    if isinstance(payload, dict):
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def list_existing_takeover_processes() -> list[dict[str, Any]]:
    current_pid = os.getpid()
    command = rf"""
$procs = Get-CimInstance Win32_Process | Where-Object {{
    $_.Name -eq 'python.exe' -and $_.ProcessId -ne {current_pid} -and (
        $_.CommandLine -like '*\backend\worker.py*' -or
        $_.CommandLine -like '*\tmp\bc2413_parse_only.py*' -or
        $_.CommandLine -like '*\tmp\bc2413_parse_supervisor.py*'
    )
}} | Select-Object ProcessId, CommandLine
if ($procs) {{ $procs | ConvertTo-Json -Compress }} else {{ '' }}
"""
    return powershell_json(command)


def kill_pid(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, text=True, check=False, timeout=30)


def stop_existing_takeover_processes() -> None:
    for row in list_existing_takeover_processes():
        pid = int(row.get("ProcessId", 0) or 0)
        if pid:
            kill_pid(pid)
            emit("takeover_stop_process", pid=pid, command_line=row.get("CommandLine"))


def spawn_process(spec: ManagedProcess) -> subprocess.Popen[str]:
    spec.stdout_path.parent.mkdir(parents=True, exist_ok=True)
    spec.stderr_path.parent.mkdir(parents=True, exist_ok=True)
    stdout_handle = spec.stdout_path.open("a", encoding="utf-8")
    stderr_handle = spec.stderr_path.open("a", encoding="utf-8")
    try:
        process = subprocess.Popen(
            spec.command,
            cwd=str(spec.cwd),
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            creationflags=CREATE_NO_WINDOW,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()
    spec.process = process
    emit("process_started", name=spec.name, pid=process.pid, command=spec.command)
    return process


def ensure_process_running(spec: ManagedProcess) -> None:
    if spec.process is None or spec.process.poll() is not None:
        previous_return_code = None if spec.process is None else spec.process.returncode
        emit("process_restart", name=spec.name, previous_return_code=previous_return_code)
        spawn_process(spec)


def stop_managed_process(spec: ManagedProcess) -> None:
    if spec.process is None:
        return
    if spec.process.poll() is None:
        kill_pid(spec.process.pid)
    spec.process = None


def get_project_and_operator(db: Session, project_code: str, operator_name: str) -> tuple[Any, User]:
    project = pipeline.get_project(db, project_code)
    operator = pipeline.get_operator(db, operator_name)
    return project, operator


def list_active_parse_tasks(db: Session, project_id: int) -> list[RunningTask]:
    rows = db.execute(
        select(
            IndexTask.id,
            IndexTask.document_id,
            IndexTask.version_id,
            IndexTask.version_no,
            Document.file_name,
            IndexTask.started_at,
        )
        .join(Document, Document.id == IndexTask.document_id)
        .where(
            Document.project_id == project_id,
            IndexTask.task_type == PARSE_TASK_TYPE,
            IndexTask.status == "running",
        )
        .order_by(IndexTask.started_at.asc(), IndexTask.id.asc())
    ).all()
    return [
        RunningTask(
            task_id=row[0],
            document_id=row[1],
            version_id=row[2],
            version_no=row[3],
            file_name=row[4],
            started_at=row[5],
        )
        for row in rows
    ]


def reset_active_parse_tasks(db: Session, project_id: int, operator: User, reason: str) -> int:
    rows = db.execute(
        select(IndexTask, Document, DocumentVersion)
        .join(Document, Document.id == IndexTask.document_id)
        .join(
            DocumentVersion,
            and_(
                DocumentVersion.document_id == IndexTask.document_id,
                DocumentVersion.version_no == IndexTask.version_no,
            ),
        )
        .where(
            Document.project_id == project_id,
            IndexTask.task_type == PARSE_TASK_TYPE,
            IndexTask.status.in_(("pending", "running")),
        )
    ).all()
    if not rows:
        return 0

    finished_at = now_utc()
    changed = 0
    system_service = SystemService(db)
    for task, document, version in rows:
        changed += 1
        if task.status == "running":
            task.status = "failed"
            task.error_message = reason[:2000]
            version.parse_status = "failed"
            if document.version_no == version.version_no:
                document.parse_status = "failed"
        else:
            task.status = "canceled"
            task.error_message = reason[:2000]
            if version.parse_status == "parsing":
                version.parse_status = "unparsed"
            if document.parse_status == "parsing":
                document.parse_status = "unparsed"
        task.progress = 100
        task.finished_at = finished_at
        task.result_json = json.dumps(
            {
                "reason": reason,
                "managed_by": "bc2413_parse_supervisor",
                "finished_at": finished_at.isoformat(),
            },
            ensure_ascii=False,
        )
        system_service.record_operation(
            operator,
            "解析队列接管",
            "document",
            document.id,
            reason,
            result="success",
        )
    db.commit()
    return changed


def read_tail_lines(path: Path, max_lines: int = 600) -> list[str]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        return list(deque(handle, maxlen=max_lines))


def inspect_running_task_log(worker_log: Path, running_task: RunningTask) -> dict[str, Any]:
    lines = read_tail_lines(worker_log)
    if not lines:
        return {
            "document_id": running_task.document_id,
            "read_timeout_count": 0,
            "task_not_found_count": 0,
            "hard_timeout_seen": False,
            "mineru_task_id": None,
            "last_block_line": None,
        }

    start_index = -1
    document_token = f"document_id={running_task.document_id}"
    for index, line in enumerate(lines):
        if "MinerU 解析开始" in line and document_token in line:
            start_index = index
    block = lines[start_index:] if start_index >= 0 else lines[-120:]

    mineru_task_id = None
    read_timeout_count = 0
    task_not_found_count = 0
    hard_timeout_seen = False
    for line in block:
        match = TASK_ID_PATTERN.search(line)
        if match:
            mineru_task_id = match.group(1)
        if READ_TIMEOUT_TOKEN in line:
            read_timeout_count += 1
        if TASK_NOT_FOUND_TOKEN in line or TASK_404_TOKEN in line:
            task_not_found_count += 1
        if MINERU_TIMEOUT_TOKEN in line:
            hard_timeout_seen = True

    last_block_line = block[-1].strip() if block else None
    return {
        "document_id": running_task.document_id,
        "read_timeout_count": read_timeout_count,
        "task_not_found_count": task_not_found_count,
        "hard_timeout_seen": hard_timeout_seen,
        "mineru_task_id": mineru_task_id,
        "last_block_line": last_block_line,
    }


def build_abort_reason(
    running_task: RunningTask,
    log_state: dict[str, Any],
    hard_timeout_seconds: int,
    read_timeout_threshold: int,
    task_not_found_threshold: int,
) -> str | None:
    started_at = running_task.started_at
    age_seconds = None
    if started_at is not None:
        age_seconds = int((now_utc() - started_at).total_seconds())

    if log_state["hard_timeout_seen"]:
        return (
            f"MinerU 任务超时，已转人工处理：document_id={running_task.document_id} "
            f"file={running_task.file_name} mineru_task_id={log_state.get('mineru_task_id')}"
        )
    if log_state["task_not_found_count"] >= task_not_found_threshold:
        return (
            f"MinerU 状态轮询连续返回 Task not found，已转人工处理：document_id={running_task.document_id} "
            f"file={running_task.file_name} mineru_task_id={log_state.get('mineru_task_id')}"
        )
    if log_state["read_timeout_count"] >= read_timeout_threshold:
        return (
            f"MinerU 状态轮询连续 Read timed out，已转人工处理：document_id={running_task.document_id} "
            f"file={running_task.file_name} mineru_task_id={log_state.get('mineru_task_id')}"
        )
    if age_seconds is not None and age_seconds >= hard_timeout_seconds:
        return (
            f"单文档运行超过 supervisor 阈值 {hard_timeout_seconds}s，已转人工处理：document_id={running_task.document_id} "
            f"file={running_task.file_name} mineru_task_id={log_state.get('mineru_task_id')}"
        )
    return None


def fail_running_task(db: Session, project_id: int, operator: User, running_task: RunningTask, reason: str) -> None:
    task = db.get(IndexTask, running_task.task_id)
    document = db.get(Document, running_task.document_id)
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == running_task.document_id,
            DocumentVersion.version_no == running_task.version_no,
        )
    )
    if task is None or document is None or version is None:
        raise AppException(f"无法定位待转人工任务：task_id={running_task.task_id}")

    finished_at = now_utc()
    task.status = "failed"
    task.progress = 100
    task.finished_at = finished_at
    task.error_message = reason[:2000]
    task.result_json = json.dumps(
        {
            "reason": reason,
            "managed_by": "bc2413_parse_supervisor",
            "finished_at": finished_at.isoformat(),
            "project_id": project_id,
        },
        ensure_ascii=False,
    )
    version.parse_status = "failed"
    if document.version_no == version.version_no:
        document.parse_status = "failed"
    SystemService(db).record_operation(
        operator,
        "解析失败转人工",
        "document",
        document.id,
        reason,
        result="success",
        project_id=project_id,
    )
    db.commit()


def summarize_project(project_code: str) -> dict[str, Any]:
    with SessionLocal() as db:
        project = pipeline.get_project(db, project_code)
        return parse_only.summarize_parse(db, project.id, set(), retry_transient_failed=False)


def normalize_blocked_versions_to_failed(db: Session, project_id: int, operator: User) -> int:
    """
    将“最新解析任务已失败/取消，但文档状态尚未落成 failed”的版本统一转成人工处理。
    这样 no-retry 模式下统计口径会稳定，不会留下既不可继续投递、又不是 failed 的灰色状态。
    """

    task_by_key = pipeline.latest_tasks_by_version(db, project_id, PARSE_TASK_TYPE)
    changed = 0
    system_service = SystemService(db)
    for version in pipeline.list_current_versions(db, project_id, parsable_only=True):
        if version.parse_status in {"success", "failed"}:
            continue
        task = task_by_key.get((version.document_id, version.version_no))
        if task is None or task.status not in pipeline.FAILED_TASK_STATUSES:
            continue
        document = db.get(Document, version.document_id)
        current_version = db.scalar(
            select(DocumentVersion).where(
                DocumentVersion.document_id == version.document_id,
                DocumentVersion.version_no == version.version_no,
            )
        )
        if document is None or current_version is None:
            continue
        current_version.parse_status = "failed"
        if document.version_no == current_version.version_no:
            document.parse_status = "failed"
        system_service.record_operation(
            operator,
            "解析失败转人工",
            "document",
            document.id,
            "supervisor 发现该文档最新解析任务已失败/取消，自动转入人工处理。",
            result="success",
            project_id=project_id,
        )
        changed += 1
    if changed:
        db.commit()
    return changed


def build_process_specs(args: argparse.Namespace) -> tuple[ManagedProcess, ManagedProcess]:
    python_exe = Path(sys.executable)
    worker_spec = ManagedProcess(
        name="worker",
        command=[str(python_exe), str(BACKEND_ROOT / "worker.py")],
        cwd=BACKEND_ROOT,
        stdout_path=args.worker_stdout,
        stderr_path=args.worker_stderr,
    )
    parse_spec = ManagedProcess(
        name="parse_only",
        command=[
            str(python_exe),
            str(TMP_ROOT / "bc2413_parse_only.py"),
            "--commit",
            "--project-code",
            args.project_code,
            "--operator",
            args.operator,
            "--poll-interval",
            "15",
            "--progress-interval",
            "180",
            "--max-active-parse",
            "2",
            "--enqueue-limit",
            "2",
            "--state-file",
            str(args.state_file),
            "--report-file",
            str(TMP_ROOT / "bc2413_parse_only_report.jsonl"),
        ],
        cwd=REPO_ROOT,
        stdout_path=args.parse_stdout,
        stderr_path=args.parse_stderr,
    )
    return worker_spec, parse_spec


def main() -> int:
    args = parse_args()
    configure_logging(args.report_file)
    last_emit = 0.0

    stop_existing_takeover_processes()

    with SessionLocal() as db:
        project, operator = get_project_and_operator(db, args.project_code, args.operator)
        reset_count = reset_active_parse_tasks(
            db,
            project.id,
            operator,
            "supervisor 接管现场，清理旧的 pending/running 解析任务，后续失败文档转人工，不再自动重试。",
        )
        normalized_count = normalize_blocked_versions_to_failed(db, project.id, operator)
        emit("takeover_reset", project_id=project.id, reset_count=reset_count)
        emit("normalize_blocked_failed", project_id=project.id, normalized_count=normalized_count)

    worker_spec, parse_spec = build_process_specs(args)
    spawn_process(worker_spec)
    spawn_process(parse_spec)

    try:
        while True:
            ensure_process_running(worker_spec)
            ensure_process_running(parse_spec)

            with SessionLocal() as db:
                project, operator = get_project_and_operator(db, args.project_code, args.operator)
                normalized_count = normalize_blocked_versions_to_failed(db, project.id, operator)
                if normalized_count:
                    emit("normalize_blocked_failed", project_id=project.id, normalized_count=normalized_count)
                running_tasks = list_active_parse_tasks(db, project.id)

                if running_tasks:
                    running_task = running_tasks[0]
                    log_state = inspect_running_task_log(args.worker_stderr, running_task)
                    abort_reason = build_abort_reason(
                        running_task,
                        log_state,
                        args.worker_hard_timeout_seconds,
                        args.read_timeout_threshold,
                        args.task_not_found_threshold,
                    )
                    if abort_reason:
                        emit(
                            "abort_running_task",
                            task_id=running_task.task_id,
                            document_id=running_task.document_id,
                            file_name=running_task.file_name,
                            reason=abort_reason,
                            log_state=log_state,
                        )
                        stop_managed_process(worker_spec)
                        fail_running_task(db, project.id, operator, running_task, abort_reason)
                        spawn_process(worker_spec)

            now = time.monotonic()
            summary = summarize_project(args.project_code)
            if summary["parse_active_tasks"] == 0 and summary["parse_ready_to_enqueue"] == 0:
                emit("completed", summary=summary)
                stop_managed_process(parse_spec)
                stop_managed_process(worker_spec)
                return 0
            if now - last_emit >= args.progress_interval:
                emit("supervisor_progress", summary=summary)
                last_emit = now

            time.sleep(args.poll_interval)
    except KeyboardInterrupt:
        emit("stopped", reason="keyboard_interrupt")
        return 0
    except Exception as exc:  # noqa: BLE001
        LOGGER.exception("BC2413 解析 supervisor 执行失败: %s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
