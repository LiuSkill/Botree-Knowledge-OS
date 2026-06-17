"""
Retrieval Trace Model

负责：
1. 保存在线问答检索链路审计数据
2. 记录多路召回、重排、证据判断和回答耗时
3. 支撑系统管理中的检索诊断和问答追溯
"""

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class RetrievalTrace(TimestampMixin, Base):
    """
    检索审计表

    职责：
    - 保存一次问答对应的 LangGraph 状态摘要
    - 记录各检索器命中数量、重排分数和最终 citation
    - 为管理员诊断召回质量提供数据基础
    """

    __tablename__ = "retrieval_traces"
    __table_args__ = (
        Index("idx_retrieval_traces_user_id", "user_id"),
        Index("idx_retrieval_traces_message_id", "message_id"),
        Index("idx_retrieval_traces_knowledge_base_id", "knowledge_base_id"),
        Index("idx_retrieval_traces_project_id", "project_id"),
        Index("idx_retrieval_traces_created_at", "created_at"),
        {"comment": "检索链路审计表"},
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="提问用户ID，关联users.id")
    session_id: Mapped[int | None] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True, comment="会话ID，关联chat_sessions.id")
    message_id: Mapped[int | None] = mapped_column(ForeignKey("chat_messages.id"), nullable=True, comment="助手消息ID，关联chat_messages.id")
    chat_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="问答类型：project_chat/base_chat")
    mode: Mapped[str] = mapped_column(String(30), nullable=False, comment="实际检索模式")
    knowledge_base_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=True, comment="知识库ID，关联knowledge_bases.id")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="项目ID，关联projects.id")
    question: Mapped[str] = mapped_column(Text, nullable=False, comment="用户问题")
    intent: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="Qwen识别的问题意图")
    sub_queries_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="查询拆解JSON")
    retriever_hits_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="各检索器命中数量JSON")
    rerank_result_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="重排结果JSON")
    citations_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="最终引用JSON")
    trace_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="LangGraph执行轨迹JSON")
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False, comment="总耗时毫秒")
