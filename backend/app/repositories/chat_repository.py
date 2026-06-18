"""
Chat Repository

负责：
1. 会话、消息、引用来源数据库访问
2. 支持 AI 中心和问答审计
3. 保存 Agent 执行过程
4. 提供文档删除时的引用清理入口
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.chat import ChatCitation, ChatMessage, ChatSession


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

        stmt = select(ChatSession).where(ChatSession.user_id == user_id).order_by(ChatSession.id.desc())
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

    def delete_session(self, session: ChatSession) -> None:
        """删除会话。"""

        self.db.delete(session)
        self.db.flush()

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
