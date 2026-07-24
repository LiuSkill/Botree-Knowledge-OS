"""
Chat Models

负责：
1. 智能体会话、消息、引用来源建模
2. 保存 Agent 执行过程
3. 支撑问答审计和来源追溯
"""

from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class ChatSession(TimestampMixin, Base):
    """
    智能体会话表

    职责：
    - 保存用户问答会话
    - 记录问答类型、问答模式和项目上下文
    """

    __tablename__ = "chat_sessions"
    __table_args__ = {"comment": "智能体会话表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False, comment="用户ID，关联users.id")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="会话标题")
    chat_type: Mapped[str] = mapped_column(String(30), default="base_chat", index=True, nullable=False, comment="问答类型：project_chat/base_chat")
    mode: Mapped[str] = mapped_column(String(30), default="auto", nullable=False, comment="问答模式：auto/base_only/project_only/hybrid")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="项目ID，项目问答关联projects.id")
    is_pinned: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否置顶")
    is_favorite: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="是否收藏")
    conversation_state: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="会话状态，如等待通用知识确认")
    pending_general_question: Mapped[str | None] = mapped_column(Text, nullable=True, comment="等待确认的原始基础问答问题")
    pending_chat_type: Mapped[str | None] = mapped_column(String(30), nullable=True, comment="等待确认的问题类型")
    pending_answer_policy: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="等待确认的问题答案策略")
    pending_evidence_status: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="等待确认的问题证据状态")
    pending_created_at: Mapped[Any | None] = mapped_column(DateTime, nullable=True, comment="等待确认状态创建时间")
    memory_state_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"),
        nullable=True,
        comment="会话级短期记忆快照JSON",
    )
    memory_state_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False, comment="短期记忆结构版本")
    memory_updated_at: Mapped[Any | None] = mapped_column(DateTime, nullable=True, comment="短期记忆最近更新时间")
    memory_rebuild_needed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, comment="短期记忆是否需要重建")


class ChatMessage(TimestampMixin, Base):
    """
    智能体消息表

    职责：
    - 保存用户消息和助手回答
    - 保存 query_scope、用户可见进度与审计用 agent_trace_json
    """

    __tablename__ = "chat_messages"
    __table_args__ = {"comment": "智能体消息表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), index=True, nullable=False, comment="会话ID，关联chat_sessions.id")
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True, comment="用户ID，助手消息可为空")
    role: Mapped[str] = mapped_column(String(30), nullable=False, comment="消息角色：user/assistant")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="消息内容")
    query_scope: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="查询范围说明")
    agent_trace_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"),
        nullable=True,
        comment="Agent执行过程JSON",
    )
    progress_json: Mapped[str | None] = mapped_column(
        Text().with_variant(LONGTEXT(), "mysql"),
        nullable=True,
        comment="用户可见处理进度JSON",
    )
    feedback_status: Mapped[str | None] = mapped_column(
        String(20),
        nullable=True,
        comment="回答反馈状态：like/dislike",
    )


class ChatCitation(TimestampMixin, Base):
    """
    智能体引用来源表

    职责：
    - 保存 AI 回答引用的文档和 Chunk
    - 保留 project_id、document_id、page_number、chunk_id 等可追溯字段
    """

    __tablename__ = "chat_citations"
    __table_args__ = {"comment": "智能体引用来源表"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, comment="主键ID")
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), index=True, nullable=False, comment="助手消息ID，关联chat_messages.id")
    source_type: Mapped[str] = mapped_column(String(30), nullable=False, comment="来源类型：base/project")
    knowledge_base_id: Mapped[int] = mapped_column(ForeignKey("knowledge_bases.id"), nullable=False, comment="知识库ID，关联knowledge_bases.id")
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, comment="项目ID，项目知识关联projects.id")
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False, comment="文档ID，关联documents.id")
    chunk_id: Mapped[int] = mapped_column(ForeignKey("document_chunks.id"), nullable=False, comment="Chunk ID，关联document_chunks.id")
    drawing_no: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="图纸编号")
    file_name: Mapped[str] = mapped_column(String(255), nullable=False, comment="来源文件名")
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="来源页码")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="引用片段内容")
    assets_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="引用关联图片资产JSON")
