"""问答 Trace 异步消费任务。"""

from __future__ import annotations

import logging
from typing import Any

from app.core.database import SessionLocal
from app.services.question_answer_trace_service import QuestionAnswerTraceService

logger = logging.getLogger(__name__)


def consume_question_answer_trace_event(envelope: dict[str, Any]) -> dict[str, Any]:
    """在独立事务中幂等消费一条 Trace 事件。"""

    trace_id = str(envelope.get("trace_id") or "")
    event_id = str(envelope.get("event_id") or "")
    with SessionLocal() as db:
        try:
            consumed = QuestionAnswerTraceService(db).consume(envelope)
            db.commit()
            logger.info(
                "问答 Trace 事件消费完成: trace_id=%s event_id=%s consumed=%s",
                trace_id,
                event_id,
                consumed,
            )
            return {"trace_id": trace_id, "event_id": event_id, "consumed": consumed}
        except Exception:
            db.rollback()
            logger.exception("问答 Trace 事件消费失败: trace_id=%s event_id=%s", trace_id, event_id)
            raise
