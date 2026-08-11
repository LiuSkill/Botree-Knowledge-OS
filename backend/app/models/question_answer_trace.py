"""问答 Trace 聚合与不可变事件模型。"""

from sqlalchemy import Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class QuestionAnswerTrace(TimestampMixin, Base):
    """单次用户提问对应的问答 Trace 聚合。"""

    __tablename__ = "question_answer_traces"
    __table_args__ = (
        Index("idx_question_answer_traces_status", "status"),
        Index("idx_question_answer_traces_session_id", "session_id"),
        Index("idx_question_answer_traces_user_message_id", "user_message_id"),
        Index("idx_question_answer_traces_created_at", "created_at"),
        {"comment": "问答 Trace 聚合表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, comment="公开 Trace ID")
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    session_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    user_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    assistant_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    project_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="running")
    completeness_status: Mapped[str] = mapped_column(String(30), nullable=False, default="partial")
    question: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    terminal_sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuestionAnswerTraceEvent(TimestampMixin, Base):
    """用于重建问答 Trace 的不可变事实事件。"""

    __tablename__ = "question_answer_trace_events"
    __table_args__ = (
        UniqueConstraint("trace_id", "event_id", name="uq_question_answer_trace_event"),
        Index("idx_question_answer_trace_events_trace_sequence", "trace_id", "sequence"),
        {"comment": "问答 Trace 不可变事件表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    event_id: Mapped[str] = mapped_column(String(64), nullable=False)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parent_node_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    business_stage: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[str] = mapped_column(String(40), nullable=False)
    producer: Mapped[str] = mapped_column(String(100), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text().with_variant(LONGTEXT(), "mysql"), nullable=False)
    payload_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
