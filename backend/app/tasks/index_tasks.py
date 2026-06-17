"""
Index Background Tasks

负责：
1. 执行 RQ 离线索引构建任务
2. 更新 index_tasks 状态、进度、结果和错误
3. 复用 Service 层业务逻辑，避免任务函数直接实现业务流程
"""

from __future__ import annotations

import json
import logging

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.user import User
from app.repositories.index_task_repository import IndexTaskRepository
from app.services.document_service import DocumentService
from app.services.index_pipeline_service import IndexPipelineService
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)


def run_parse_document_task(task_id: int) -> dict:
    """执行 MinerU 异步解析任务。"""

    with SessionLocal() as db:
        repository = IndexTaskRepository(db)
        task = repository.get(task_id)
        if not task:
            raise ValueError(f"IndexTask not found: {task_id}")
        task.status = "running"
        task.progress = 10
        task.started_at = now_utc()
        db.commit()
        try:
            operator = db.get(User, task.created_by) if task.created_by else None
            if operator is None:
                raise ValueError("解析任务缺少创建人，无法执行权限校验")
            result = DocumentService(db).parse_document_version(task.document_id, task.version_no, operator)
            task.status = "success"
            task.progress = 100
            task.finished_at = now_utc()
            task.error_message = None
            task.result_json = json.dumps(result, ensure_ascii=False)
            db.commit()
            logger.info(
                "MinerU 解析任务完成: task_id=%s document_id=%s version_no=%s",
                task.id,
                task.document_id,
                task.version_no,
            )
            return result
        except Exception as exc:
            db.rollback()
            task = repository.get(task_id)
            if task:
                task.status = "failed"
                task.progress = 100
                task.finished_at = now_utc()
                task.error_message = str(exc)[:2000]
                db.commit()
            logger.exception("MinerU 解析任务失败: task_id=%s", task_id)
            raise


def run_full_index_task(task_id: int) -> dict:
    """
    执行完整索引构建任务。

    参数:
        task_id: index_tasks.id。

    返回:
        任务执行结果。
    """

    with SessionLocal() as db:
        repository = IndexTaskRepository(db)
        task = repository.get(task_id)
        if not task:
            raise ValueError(f"IndexTask not found: {task_id}")
        task.status = "running"
        task.progress = 5
        task.started_at = now_utc()
        db.commit()
        try:
            operator = db.get(User, task.created_by) if task.created_by else None
            if operator is None:
                raise ValueError("索引任务缺少创建人，无法执行权限校验")
            result = DocumentService(db).build_document_index(task.document_id, operator, task.version_no, active_task_id=task.id)
            task.status = "success"
            task.progress = 100
            task.finished_at = now_utc()
            task.error_message = None
            task.result_json = json.dumps(result, ensure_ascii=False)
            db.commit()
            logger.info("完整索引任务完成: task_id=%s document_id=%s", task.id, task.document_id)
            return result
        except Exception as exc:
            db.rollback()
            task = repository.get(task_id)
            if task:
                task.status = "failed"
                task.progress = 100
                task.finished_at = now_utc()
                task.error_message = str(exc)[:2000]
                db.commit()
            logger.exception("完整索引任务失败: task_id=%s", task_id)
            raise


def run_publish_index_task(task_id: int) -> dict:
    """
    执行索引发布任务。

    参数:
        task_id: index_tasks.id。

    返回:
        发布结果。
    """

    with SessionLocal() as db:
        repository = IndexTaskRepository(db)
        task = repository.get(task_id)
        if not task:
            raise ValueError(f"IndexTask not found: {task_id}")
        task.status = "running"
        task.progress = 20
        task.started_at = now_utc()
        db.commit()
        try:
            document = DocumentService(db).repository.get(task.document_id)
            if not document:
                raise ValueError(f"Document not found: {task.document_id}")
            result = IndexPipelineService(db).publish_all(document)
            document.index_status = "indexed"
            task.status = "success"
            task.progress = 100
            task.finished_at = now_utc()
            task.error_message = None
            task.result_json = json.dumps(result, ensure_ascii=False)
            db.commit()
            logger.info("索引发布任务完成: task_id=%s document_id=%s", task.id, task.document_id)
            return result
        except Exception as exc:
            db.rollback()
            task = repository.get(task_id)
            if task:
                task.status = "failed"
                task.progress = 100
                task.finished_at = now_utc()
                task.error_message = str(exc)[:2000]
                db.commit()
            logger.exception("索引发布任务失败: task_id=%s", task_id)
            raise
