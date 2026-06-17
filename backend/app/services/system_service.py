"""
System Service

负责：
1. 记录操作日志
2. 汇总工作台统计
3. 提供问答审计数据
"""

import logging

from sqlalchemy.orm import Session

from app.models.operation_log import OperationLog
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.review_repository import ReviewRepository
from app.repositories.system_repository import SystemRepository
from app.services.retrieval_trace_service import RetrievalTraceService

logger = logging.getLogger(__name__)

CATEGORY_CHART_COLORS: tuple[str, ...] = ("#4ea3f7", "#b678f4", "#ff8a1f", "#f36eae", "#2fcf72", "#64748b")


class SystemService:
    """
    系统服务

    职责：
    - 记录关键操作日志
    - 提供工作台和审计页面数据
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = SystemRepository(db)

    def record_operation(
        self,
        user: User | None,
        action: str,
        target_type: str,
        target_id: str | int | None = None,
        detail: str | None = None,
        result: str = "success",
        ip_address: str | None = None,
        auto_commit: bool = False,
    ) -> OperationLog:
        """
        记录操作日志

        参数:
            user: 当前用户，可为空
            action: 操作动作
            target_type: 操作对象类型
            target_id: 操作对象ID
            detail: 操作详情
            result: 执行结果
            ip_address: IP地址
            auto_commit: 是否立即提交事务

        返回:
            操作日志对象。
        """

        log = OperationLog(
            user_id=user.id if user else None,
            username=user.username if user else None,
            action=action,
            target_type=target_type,
            target_id=str(target_id) if target_id is not None else None,
            detail=detail,
            result=result,
            ip_address=ip_address,
        )
        self.repository.add_log(log)
        if auto_commit:
            self.db.commit()
        logger.info("操作日志: action=%s target=%s target_id=%s result=%s", action, target_type, target_id, result)
        return log

    def dashboard(self, current_user: User | None = None) -> dict:
        """
        获取工作台统计数据

        参数:
            current_user: 当前登录用户，用于查询真实登录日志。

        返回:
            工作台统计对象。
        """

        counts = self.repository.dashboard_counts()
        documents = DocumentRepository(self.db).list()
        projects = ProjectRepository(self.db).list(admin=True)[:5]
        reviews = ReviewRepository(self.db).list_tasks(status="reviewing")[:5]
        recent_questions = self.repository.list_recent_user_questions(limit=4)
        category_stats = self.repository.list_document_category_stats()
        login_logs = self.repository.list_user_login_logs(current_user.id, limit=2) if current_user else []
        counts.update(
            {
                "last_login_at": self._resolve_last_login_at(login_logs),
                "recent_documents": [
                    {
                        "id": item.id,
                        "file_name": item.file_name,
                        "file_type": item.file_type,
                        "review_status": item.review_status,
                        "index_status": item.index_status,
                        "created_at": item.created_at,
                    }
                    for item in documents[:5]
                ],
                "recent_projects": [
                    {"id": item.id, "name": item.name, "code": item.code, "progress": item.progress, "status": item.status}
                    for item in projects
                ],
                "todo_reviews": [
                    {"id": item.id, "document_id": item.document_id, "review_status": item.review_status}
                    for item in reviews
                ],
                "recent_ai_questions": [
                    {
                        "id": message.id,
                        "session_id": session.id,
                        "question": message.content,
                        "chat_type": session.chat_type,
                        "created_at": message.created_at,
                    }
                    for message, session in recent_questions
                ],
                "knowledge_category_stats": self._build_knowledge_category_stats(category_stats),
            }
        )
        return counts

    def list_logs(self) -> list[OperationLog]:
        """
        查询操作日志

        返回:
            日志列表。
        """

        return self.repository.list_logs()

    def qa_audits(self) -> list[dict]:
        """
        查询问答审计记录

        返回:
            助手消息审计数据。
        """

        chat_repo = ChatRepository(self.db)
        audits: list[dict] = []
        for message in chat_repo.list_assistant_messages():
            citations = chat_repo.list_citations(message.id)
            audits.append(
                {
                    "id": message.id,
                    "session_id": message.session_id,
                    "answer": message.content,
                    "query_scope": message.query_scope,
                    "agent_trace_json": message.agent_trace_json,
                    "citation_count": len(citations),
                    "created_at": message.created_at,
                }
            )
        return audits

    def retrieval_traces(self) -> list[dict]:
        """
        查询检索链路审计记录。

        返回:
            最近的 LangGraph 检索 trace 列表。
        """

        return [
            {
                "id": trace.id,
                "user_id": trace.user_id,
                "session_id": trace.session_id,
                "message_id": trace.message_id,
                "chat_type": trace.chat_type,
                "mode": trace.mode,
                "project_id": trace.project_id,
                "question": trace.question,
                "intent": trace.intent,
                "sub_queries_json": trace.sub_queries_json,
                "retriever_hits_json": trace.retriever_hits_json,
                "rerank_result_json": trace.rerank_result_json,
                "citations_json": trace.citations_json,
                "trace_json": trace.trace_json,
                "elapsed_ms": trace.elapsed_ms,
                "created_at": trace.created_at,
            }
            for trace in RetrievalTraceService(self.db).list_recent()
        ]

    def _resolve_last_login_at(self, login_logs: list[OperationLog]) -> str | None:
        """
        获取上次登录时间

        参数:
            login_logs: 当前用户最近登录日志

        返回:
            上一次登录时间；仅有一次登录记录时返回该记录时间。
        """

        if not login_logs:
            return None
        log = login_logs[1] if len(login_logs) > 1 else login_logs[0]
        return log.created_at.isoformat()

    def _build_knowledge_category_stats(self, category_stats: list[tuple[str, int]]) -> list[dict[str, int | str]]:
        """
        构建知识分类统计

        参数:
            category_stats: 真实分类名称和文档数量

        返回:
            包含名称、数量、百分比和颜色的分类统计。
        """

        if not category_stats:
            return []

        total_count = max(sum(count for _, count in category_stats), 1)
        return [
            {
                "name": name,
                "value": count,
                "percent": round(count / total_count * 100),
                "color": CATEGORY_CHART_COLORS[index % len(CATEGORY_CHART_COLORS)],
            }
            for index, (name, count) in enumerate(category_stats)
        ]
