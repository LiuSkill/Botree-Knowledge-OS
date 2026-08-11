"""问答 Trace 异步事件发布。"""

from __future__ import annotations

import logging
import time
from typing import Any

from app.core.redis import get_rq_queue

logger = logging.getLogger(__name__)


class QuestionAnswerTracePublisher:
    """以 fail-open 语义向持久化队列投递 Trace 事件。"""

    def __init__(self, queue: Any | None = None) -> None:
        self.queue = queue

    def publish(self, envelope: dict[str, Any]) -> bool:
        """投递事件；任何队列异常只记录诊断信息并返回 False。"""

        trace_id = str(envelope.get("trace_id") or "")
        event_id = str(envelope.get("event_id") or "")
        started_at = time.perf_counter()
        try:
            queue = self.queue if self.queue is not None else get_rq_queue()
            if queue is None:
                logger.warning(
                    "问答 Trace 队列不可用: trace_id=%s event_id=%s status=unavailable elapsed_ms=%s",
                    trace_id,
                    event_id,
                    int((time.perf_counter() - started_at) * 1000),
                )
                return False
            queue.enqueue(
                "app.tasks.question_answer_trace_tasks.consume_question_answer_trace_event",
                envelope,
                # RQ 2.x 的自定义 Job ID 仅允许字母、数字、下划线和短横线。
                # Trace 与事件 ID 均由系统生成，使用短横线连接仍能保证重复投递幂等。
                job_id=f"qa-trace-{trace_id}-{event_id}",
            )
            logger.info(
                "问答 Trace 事件投递完成: trace_id=%s event_id=%s status=queued elapsed_ms=%s",
                trace_id,
                event_id,
                int((time.perf_counter() - started_at) * 1000),
            )
            return True
        except Exception as exc:  # noqa: BLE001 - Trace 必须 fail-open
            logger.warning(
                "问答 Trace 事件投递失败: trace_id=%s event_id=%s status=failed elapsed_ms=%s error_type=%s",
                trace_id,
                event_id,
                int((time.perf_counter() - started_at) * 1000),
                type(exc).__name__,
            )
            return False
