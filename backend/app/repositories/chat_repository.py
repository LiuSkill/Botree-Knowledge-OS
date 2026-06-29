"""
Chat Repository

负责：
1. 会话、消息、引用来源数据库访问
2. 支持 AI 中心和问答审计
3. 保存 Agent 执行过程
4. 提供文档删除时的引用清理入口
"""

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from app.models.chat import ChatCitation, ChatMessage, ChatSession
from app.models.project import Project
from app.models.retrieval_trace import RetrievalTrace
from app.models.user import User


def _normalize_page(page: int, page_size: int) -> tuple[int, int, int]:
    """统一分页边界，避免审计接口一次拉取过多数据。"""

    safe_page = max(page, 1)
    safe_size = max(min(page_size, 100), 1)
    offset = (safe_page - 1) * safe_size
    return safe_page, safe_size, offset


class ChatRepository:
    """
    问答仓储

    职责：
    - 管理会话与消息
    - 保存引用来源
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list_sessions(
        self,
        user_id: int,
        chat_type: str | None = None,
        project_id: int | None = None,
    ) -> list[ChatSession]:
        """查询用户会话。"""

        stmt = (
            select(ChatSession)
            .where(ChatSession.user_id == user_id)
            .order_by(ChatSession.is_pinned.desc(), ChatSession.updated_at.desc(), ChatSession.id.desc())
        )
        if chat_type:
            stmt = stmt.where(ChatSession.chat_type == chat_type)
        if project_id is not None:
            stmt = stmt.where(ChatSession.project_id == project_id)
        return list(self.db.scalars(stmt).all())

    def get_session(self, session_id: int) -> ChatSession | None:
        """按 ID 查询会话。"""

        return self.db.get(ChatSession, session_id)

    def add_session(self, session: ChatSession) -> ChatSession:
        """新增会话。"""

        self.db.add(session)
        self.db.flush()
        return session

    def update_session(self, session: ChatSession) -> ChatSession:
        """保存会话展示属性变更。"""

        self.db.add(session)
        self.db.flush()
        return session

    def delete_session(self, session: ChatSession) -> dict[str, int]:
        """
        删除会话及其问答明细。

        chat_messages、chat_citations 和 retrieval_traces 都通过外键依赖会话或消息，
        因此必须按子表到父表的顺序显式清理，避免 MySQL 外键约束阻止删除。
        """

        message_ids = list(
            self.db.scalars(select(ChatMessage.id).where(ChatMessage.session_id == session.id)).all()
        )
        deleted_citations = 0
        if message_ids:
            citation_result = self.db.execute(
                delete(ChatCitation).where(ChatCitation.message_id.in_(message_ids))
            )
            deleted_citations = int(citation_result.rowcount or 0)

        trace_condition = RetrievalTrace.session_id == session.id
        if message_ids:
            trace_condition = or_(trace_condition, RetrievalTrace.message_id.in_(message_ids))
        trace_result = self.db.execute(delete(RetrievalTrace).where(trace_condition))

        message_result = self.db.execute(
            delete(ChatMessage).where(ChatMessage.session_id == session.id)
        )
        self.db.delete(session)
        self.db.flush()
        return {
            "messages": int(message_result.rowcount or 0),
            "citations": deleted_citations,
            "retrieval_traces": int(trace_result.rowcount or 0),
        }

    def add_message(self, message: ChatMessage) -> ChatMessage:
        """新增消息。"""

        self.db.add(message)
        self.db.flush()
        return message

    def get_message(self, message_id: int) -> ChatMessage | None:
        """按 ID 查询消息。"""

        return self.db.get(ChatMessage, message_id)

    def update_message_feedback(self, message: ChatMessage, feedback_status: str | None) -> ChatMessage:
        """更新助手回答的反馈状态。"""

        message.feedback_status = feedback_status
        self.db.flush()
        return message

    def list_messages(self, session_id: int) -> list[ChatMessage]:
        """查询会话消息。"""

        return list(
            self.db.scalars(select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.id)).all()
        )

    def add_citations(self, citations: list[ChatCitation]) -> list[ChatCitation]:
        """批量新增引用来源。"""

        for citation in citations:
            self.db.add(citation)
        self.db.flush()
        return citations

    def list_citations(self, message_id: int) -> list[ChatCitation]:
        """查询消息引用来源。"""

        return list(
            self.db.scalars(select(ChatCitation).where(ChatCitation.message_id == message_id).order_by(ChatCitation.id)).all()
        )

    def list_citations_by_message_ids(self, message_ids: list[int]) -> list[ChatCitation]:
        """批量查询多条助手消息的引用来源。"""

        if not message_ids:
            return []
        return list(
            self.db.scalars(
                select(ChatCitation)
                .where(ChatCitation.message_id.in_(message_ids))
                .order_by(ChatCitation.message_id, ChatCitation.id)
            ).all()
        )

    def list_assistant_messages(self) -> list[ChatMessage]:
        """查询助手消息，用于问答审计。"""

        return list(self.db.scalars(select(ChatMessage).where(ChatMessage.role == "assistant").order_by(ChatMessage.id.desc())).all())

    def count_project_answers(self, project_id: int) -> int:
        """统计项目问答已产生的助手回答数，作为项目详情页的问答次数。"""

        stmt = (
            select(func.count(ChatMessage.id))
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatSession.project_id == project_id,
                ChatSession.chat_type == "project_chat",
                ChatMessage.role == "assistant",
            )
        )
        return int(self.db.scalar(stmt) or 0)

    def list_qa_audit_details(
        self,
        user_id: int | None = None,
        project_id: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        feedback_status: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """按助手回答分页查询问答审计明细。"""

        safe_page, safe_size, offset = _normalize_page(page, page_size)
        citation_count_subquery = (
            select(ChatCitation.message_id, func.count(ChatCitation.id).label("citation_count"))
            .group_by(ChatCitation.message_id)
            .subquery()
        )
        latest_trace_subquery = (
            select(RetrievalTrace.message_id, func.max(RetrievalTrace.id).label("trace_id"))
            .where(RetrievalTrace.message_id.is_not(None))
            .group_by(RetrievalTrace.message_id)
            .subquery()
        )
        stmt = (
            select(
                ChatMessage,
                ChatSession,
                User,
                Project,
                RetrievalTrace,
                func.coalesce(citation_count_subquery.c.citation_count, 0).label("citation_count"),
            )
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .join(User, User.id == ChatSession.user_id)
            .outerjoin(Project, Project.id == ChatSession.project_id)
            .outerjoin(citation_count_subquery, citation_count_subquery.c.message_id == ChatMessage.id)
            .outerjoin(latest_trace_subquery, latest_trace_subquery.c.message_id == ChatMessage.id)
            .outerjoin(RetrievalTrace, RetrievalTrace.id == latest_trace_subquery.c.trace_id)
            .where(ChatMessage.role == "assistant")
        )
        if user_id is not None:
            stmt = stmt.where(ChatSession.user_id == user_id)
        if project_id is not None:
            stmt = stmt.where(ChatSession.project_id == project_id)
        if started_at is not None:
            stmt = stmt.where(ChatMessage.created_at >= started_at)
        if ended_at is not None:
            stmt = stmt.where(ChatMessage.created_at <= ended_at)
        if feedback_status == "none":
            stmt = stmt.where(ChatMessage.feedback_status.is_(None))
        elif feedback_status:
            stmt = stmt.where(ChatMessage.feedback_status == feedback_status)

        total = int(self.db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
        rows = list(
            self.db.execute(
                stmt.order_by(ChatMessage.created_at.desc(), ChatMessage.id.desc()).offset(offset).limit(safe_size)
            ).all()
        )
        return {"items": rows, "total": total, "page": safe_page, "page_size": safe_size}

    def list_qa_audit_sessions(
        self,
        user_id: int | None = None,
        project_id: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """按会话聚合查询问答审计记录。"""

        safe_page, safe_size, offset = _normalize_page(page, page_size)
        stmt = (
            select(ChatSession, User, Project)
            .join(User, User.id == ChatSession.user_id)
            .outerjoin(Project, Project.id == ChatSession.project_id)
        )
        if user_id is not None:
            stmt = stmt.where(ChatSession.user_id == user_id)
        if project_id is not None:
            stmt = stmt.where(ChatSession.project_id == project_id)

        session_rows = list(self.db.execute(stmt).all())
        session_ids = [row[0].id for row in session_rows]
        citation_counts = self._list_session_citation_counts(session_ids)
        messages_by_session = self._list_messages_by_session(session_ids)

        items: list[dict[str, Any]] = []
        for session, user, project in session_rows:
            summary = self._build_session_audit_summary(session, messages_by_session.get(session.id, []), citation_counts)
            audit_time = summary["latest_qa_at"] or session.created_at
            if started_at is not None and audit_time < started_at:
                continue
            if ended_at is not None and audit_time > ended_at:
                continue
            items.append(
                {
                    "session": session,
                    "user": user,
                    "project": project,
                    **summary,
                    "latest_qa_at": audit_time,
                }
            )

        items.sort(key=lambda item: (item["latest_qa_at"], item["session"].id), reverse=True)
        total = len(items)
        return {"items": items[offset : offset + safe_size], "total": total, "page": safe_page, "page_size": safe_size}

    def get_previous_user_question(self, session_id: int, before_message_id: int) -> str | None:
        """查询指定助手消息之前最近的一条用户问题。"""

        stmt = (
            select(ChatMessage.content)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == "user",
                ChatMessage.id < before_message_id,
            )
            .order_by(ChatMessage.id.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def _list_session_citation_counts(self, session_ids: list[int]) -> dict[int, int]:
        """统计每个会话下的引用数量。"""

        if not session_ids:
            return {}
        stmt = (
            select(ChatMessage.session_id, func.count(ChatCitation.id))
            .join(ChatCitation, ChatCitation.message_id == ChatMessage.id)
            .where(ChatMessage.session_id.in_(session_ids), ChatMessage.role == "assistant")
            .group_by(ChatMessage.session_id)
        )
        return {int(session_id): int(count) for session_id, count in self.db.execute(stmt).all()}

    def _list_messages_by_session(self, session_ids: list[int]) -> dict[int, list[ChatMessage]]:
        """批量查询会话消息并按会话归组。"""

        messages_by_session: dict[int, list[ChatMessage]] = {}
        if not session_ids:
            return messages_by_session
        stmt = (
            select(ChatMessage)
            .where(ChatMessage.session_id.in_(session_ids))
            .order_by(ChatMessage.session_id, ChatMessage.id)
        )
        for message in self.db.scalars(stmt).all():
            messages_by_session.setdefault(message.session_id, []).append(message)
        return messages_by_session

    def _build_session_audit_summary(
        self,
        session: ChatSession,
        messages: list[ChatMessage],
        citation_counts: dict[int, int],
    ) -> dict[str, Any]:
        """根据会话消息构建会话审计摘要。"""

        question_count = 0
        answer_count = 0
        latest_question: str | None = None
        latest_answer: str | None = None
        latest_qa_at: datetime | None = None
        pending_question: str | None = None
        for message in messages:
            if message.role == "user":
                question_count += 1
                pending_question = message.content
                continue
            if message.role != "assistant":
                continue
            answer_count += 1
            if latest_qa_at is None or message.created_at >= latest_qa_at:
                latest_qa_at = message.created_at
                latest_answer = message.content
                latest_question = pending_question
        return {
            "question_count": question_count,
            "answer_count": answer_count,
            "citation_count": citation_counts.get(session.id, 0),
            "latest_question": latest_question,
            "latest_answer": latest_answer,
            "latest_qa_at": latest_qa_at,
        }

    def list_citation_message_ids_by_document(self, document_id: int) -> list[int]:
        """
        查询引用了指定文档的助手消息ID。

        参数:
            document_id: 文档ID。

        返回:
            助手消息ID列表。
        """

        return list(
            self.db.scalars(
                select(ChatCitation.message_id).where(ChatCitation.document_id == document_id).distinct().order_by(ChatCitation.message_id)
            ).all()
        )

    def clear_citations_by_document(self, document_id: int) -> int:
        """
        物理删除引用了指定文档的 citation 记录。

        参数:
            document_id: 文档ID。

        返回:
            删除的 citation 数量。
        """

        result = self.db.execute(delete(ChatCitation).where(ChatCitation.document_id == document_id))
        self.db.flush()
        return int(result.rowcount or 0)
