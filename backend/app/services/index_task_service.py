"""
Index Task Service

负责：
1. 创建离线索引构建和发布任务
2. 对接 RQ + Redis 后台队列
3. 保证异步任务接口只返回真实已入队的任务
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.redis import get_rq_queue
from app.models.index_task import IndexTask
from app.models.user import User
from app.repositories.index_task_repository import IndexTaskRepository

logger = logging.getLogger(__name__)


class IndexTaskService:
    """
    索引任务服务

    职责：
    - 创建任务记录
    - 将任务投递到 RQ
    - 在队列未启用时快速失败，避免异步接口伪装成同步长任务
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = IndexTaskRepository(db)

    def create_parse_task(
        self,
        document_id: int,
        version_no: int,
        version_id: int | None,
        operator: User,
    ) -> IndexTask:
        """
        创建 MinerU 异步解析任务。

        上传链路不能被后台队列阻塞；队列不可用时仅将任务标记失败并返回。
        """

        task = self.repository.add(
            IndexTask(
                document_id=document_id,
                version_id=version_id,
                version_no=version_no,
                task_type="mineru_parse",
                status="pending",
                progress=0,
                created_by=operator.id,
            )
        )
        self.db.commit()

        queue = get_rq_queue()
        if queue is None:
            task.status = "failed"
            task.progress = 100
            task.error_message = "Redis/RQ 未配置，无法自动执行 MinerU 异步解析"
            task.result_json = json.dumps({"queued": False}, ensure_ascii=False)
            self.db.commit()
            logger.error(
                "MinerU 解析任务入队失败: document_id=%s version_id=%s version_no=%s",
                document_id,
                version_id,
                version_no,
            )
            return task

        from app.tasks.index_tasks import run_parse_document_task

        self._enqueue(queue, task.id, run_parse_document_task)
        self.db.refresh(task)
        return task

    def create_build_task(self, document_id: int, version_no: int, operator: User, version_id: int | None = None) -> IndexTask:
        """
        创建完整索引构建任务。

        参数:
            document_id: 文档ID。
            version_no: 文档版本号。
            operator: 当前操作人。

        返回:
            已成功入队的索引任务记录。
        """

        queue = self._require_queue()
        task = self.repository.add(
            IndexTask(
                document_id=document_id,
                version_id=version_id,
                version_no=version_no,
                task_type="full_build",
                status="pending",
                progress=0,
                created_by=operator.id,
            )
        )
        self.db.commit()

        from app.tasks.index_tasks import run_full_index_task

        self._enqueue(queue, task.id, run_full_index_task)
        self.db.refresh(task)
        return task

    def create_publish_task(self, document_id: int, version_no: int, operator: User, version_id: int | None = None) -> IndexTask:
        """
        创建索引发布任务。

        参数:
            document_id: 文档ID。
            version_no: 文档版本号。
            operator: 当前操作人。

        返回:
            已成功入队的索引任务记录。
        """

        queue = self._require_queue()
        task = self.repository.add(
            IndexTask(
                document_id=document_id,
                version_id=version_id,
                version_no=version_no,
                task_type="index_publish",
                status="pending",
                progress=0,
                created_by=operator.id,
            )
        )
        self.db.commit()

        from app.tasks.index_tasks import run_publish_index_task

        self._enqueue(queue, task.id, run_publish_index_task)
        self.db.refresh(task)
        return task

    def list_document_tasks(self, document_id: int) -> list[IndexTask]:
        """
        查询文档索引任务列表。

        参数:
            document_id: 文档ID。

        返回:
            指定文档的索引任务列表。
        """

        return self.repository.list_by_document(document_id)

    def _require_queue(self) -> Any:
        """
        获取并校验 RQ 队列。

        返回:
            已初始化的 RQ 队列对象。
        """

        queue = get_rq_queue()
        if queue is None:
            logger.error("异步索引任务创建失败: Redis/RQ 未配置")
            raise AppException("未配置 Redis/RQ，无法创建异步索引任务，请使用 RQ Worker 模式运行系统", status_code=503, code=503)
        return queue

    def _enqueue(self, queue: Any, task_id: int, task_func: Callable[[int], dict]) -> None:
        """
        投递 RQ 任务并回写任务元数据。

        参数:
            queue: RQ 队列对象。
            task_id: 本地索引任务ID。
            task_func: RQ 执行函数。
        """

        job = queue.enqueue(task_func, task_id, job_timeout="30m")
        task = self.repository.get(task_id)
        if task:
            task.rq_job_id = job.id
            task.result_json = json.dumps({"queued": True, "job_id": job.id}, ensure_ascii=False)
            self.db.commit()
        logger.info("索引任务已入队: task_id=%s job_id=%s function=%s", task_id, job.id, task_func.__name__)
