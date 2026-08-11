"""问答 Trace 数据访问。"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.question_answer_trace import QuestionAnswerTrace, QuestionAnswerTraceEvent


class QuestionAnswerTraceRepository:
    """维护不可变事件和可重建聚合。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def add_event(self, event: QuestionAnswerTraceEvent) -> bool:
        """写入事件；已存在的幂等事件返回 False。"""

        existing = self.db.scalar(
            select(QuestionAnswerTraceEvent.id).where(
                QuestionAnswerTraceEvent.trace_id == event.trace_id,
                QuestionAnswerTraceEvent.event_id == event.event_id,
            )
        )
        if existing is not None:
            return False
        try:
            with self.db.begin_nested():
                self.db.add(event)
                self.db.flush()
        except IntegrityError:
            return False
        return True

    def get_trace(self, trace_id: str) -> QuestionAnswerTrace | None:
        return self.db.scalar(select(QuestionAnswerTrace).where(QuestionAnswerTrace.trace_id == trace_id))

    def get_by_assistant_message_id(self, message_id: int) -> QuestionAnswerTrace | None:
        """按助手消息关联新 Trace；历史问答返回 None。"""

        return self.db.scalar(
            select(QuestionAnswerTrace).where(QuestionAnswerTrace.assistant_message_id == message_id)
        )

    def add_trace(self, trace: QuestionAnswerTrace) -> QuestionAnswerTrace:
        self.db.add(trace)
        self.db.flush()
        return trace

    def replace_trace(self, trace_id: str, replacement: QuestionAnswerTrace) -> QuestionAnswerTrace:
        """替换可重建聚合；事件事实保持不变。"""

        existing = self.get_trace(trace_id)
        if existing is not None:
            self.db.delete(existing)
            self.db.flush()
        self.db.add(replacement)
        self.db.flush()
        return replacement

    def list_sequences(self, trace_id: str) -> list[int]:
        """返回 Trace 已持久化的事件序号。"""

        return list(
            self.db.scalars(
                select(QuestionAnswerTraceEvent.sequence)
                .where(QuestionAnswerTraceEvent.trace_id == trace_id)
                .order_by(QuestionAnswerTraceEvent.sequence)
            ).all()
        )

    def list_events(
        self,
        trace_id: str,
        *,
        offset: int = 0,
        limit: int | None = None,
        business_stage: str | None = None,
    ) -> list[QuestionAnswerTraceEvent]:
        """按执行序号返回不可变事件。"""

        statement = select(QuestionAnswerTraceEvent).where(QuestionAnswerTraceEvent.trace_id == trace_id)
        if business_stage is not None:
            statement = statement.where(QuestionAnswerTraceEvent.business_stage == business_stage)
        statement = statement.order_by(QuestionAnswerTraceEvent.sequence, QuestionAnswerTraceEvent.id)
        if offset > 0:
            statement = statement.offset(offset)
        if limit is not None:
            statement = statement.limit(limit)
        return list(self.db.scalars(statement).all())

    def count_events(self, trace_id: str, *, business_stage: str | None = None) -> int:
        """返回 Trace 在可选业务阶段过滤后的事件总数。"""

        statement = select(func.count(QuestionAnswerTraceEvent.id)).where(
            QuestionAnswerTraceEvent.trace_id == trace_id
        )
        if business_stage is not None:
            statement = statement.where(QuestionAnswerTraceEvent.business_stage == business_stage)
        return int(self.db.scalar(statement) or 0)

    def list_event_summaries(
        self,
        trace_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
        business_stage: str | None = None,
    ) -> list[dict[str, object]]:
        """只读取事件元数据，概览查询不得加载大载荷列。"""

        columns = (
            QuestionAnswerTraceEvent.schema_version,
            QuestionAnswerTraceEvent.event_id,
            QuestionAnswerTraceEvent.trace_id,
            QuestionAnswerTraceEvent.node_id,
            QuestionAnswerTraceEvent.parent_node_id,
            QuestionAnswerTraceEvent.business_stage,
            QuestionAnswerTraceEvent.event_type,
            QuestionAnswerTraceEvent.sequence,
            QuestionAnswerTraceEvent.occurred_at,
            QuestionAnswerTraceEvent.producer,
            QuestionAnswerTraceEvent.payload_ref,
            QuestionAnswerTraceEvent.checksum,
        )
        statement = select(*columns).where(QuestionAnswerTraceEvent.trace_id == trace_id)
        if business_stage is not None:
            statement = statement.where(QuestionAnswerTraceEvent.business_stage == business_stage)
        statement = statement.order_by(QuestionAnswerTraceEvent.sequence, QuestionAnswerTraceEvent.id)
        statement = statement.offset(max(offset, 0)).limit(limit)
        return [dict(row._mapping) for row in self.db.execute(statement).all()]

    def stage_summaries(self, trace_id: str) -> list[dict[str, object]]:
        """由数据库聚合阶段和状态，避免为概览反序列化事件载荷。"""

        rows = self.db.execute(
            select(
                QuestionAnswerTraceEvent.business_stage,
                QuestionAnswerTraceEvent.event_type,
                func.count(QuestionAnswerTraceEvent.id),
            )
            .where(QuestionAnswerTraceEvent.trace_id == trace_id)
            .group_by(QuestionAnswerTraceEvent.business_stage, QuestionAnswerTraceEvent.event_type)
        ).all()
        stages: dict[str, dict[str, object]] = {}
        for stage, event_type, count in rows:
            item = stages.setdefault(str(stage), {"stage": stage, "event_count": 0, "statuses": [], "elapsed_ms": 0})
            item["event_count"] = int(item["event_count"]) + int(count)
            statuses = item["statuses"]
            if isinstance(statuses, list):
                statuses.append(event_type)
        return list(stages.values())

    def get_event(self, trace_id: str, event_id: str) -> QuestionAnswerTraceEvent | None:
        """按 Trace 与事件 ID 读取单个不可变事件。"""

        return self.db.scalar(
            select(QuestionAnswerTraceEvent).where(
                QuestionAnswerTraceEvent.trace_id == trace_id,
                QuestionAnswerTraceEvent.event_id == event_id,
            )
        )

    def delete_trace(self, trace_id: str) -> int:
        """显式清理 Trace 事件与聚合，不触碰聊天业务数据。"""

        events = self.list_events(trace_id)
        for event in events:
            self.db.delete(event)
        trace = self.get_trace(trace_id)
        if trace is not None:
            self.db.delete(trace)
        self.db.flush()
        return len(events)

    def aggregate_status_counts(self) -> dict[str, int]:
        """返回 Trace 状态与完整性计数，供运维指标使用。"""

        rows = self.db.execute(
            select(
                QuestionAnswerTrace.status,
                QuestionAnswerTrace.completeness_status,
                func.count(QuestionAnswerTrace.id),
            ).group_by(QuestionAnswerTrace.status, QuestionAnswerTrace.completeness_status)
        ).all()
        return {f"{status}:{completeness}": int(count) for status, completeness, count in rows}
