"""
System Service

负责：
1. 记录操作日志
2. 汇总工作台统计
3. 提供问答审计数据
"""

import json
import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.chat import ChatCitation
from app.models.operation_log import OperationLog
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.review_repository import ReviewRepository
from app.repositories.system_repository import SystemRepository
from app.services.retrieval_trace_service import RetrievalTraceService
from app.utils.pagination import paginate
from app.utils.user_avatar import avatar_url_for_user

logger = logging.getLogger(__name__)

CATEGORY_CHART_COLORS: tuple[str, ...] = ("#4ea3f7", "#b678f4", "#ff8a1f", "#f36eae", "#2fcf72", "#64748b")
QA_FEEDBACK_FILTERS: set[str] = {"like", "dislike", "none"}


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

    def list_logs(
        self,
        keyword: str | None = None,
        result: str | None = None,
        target_type: str | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict:
        """
        查询操作日志

        返回:
            日志列表。
        """

        return paginate(
            self.repository.list_logs(
                keyword=keyword,
                result=result,
                target_type=target_type,
                started_at=started_at,
                ended_at=ended_at,
            ),
            page,
            page_size,
        )

    def qa_audit_sessions(
        self,
        user_id: int | None = None,
        project_id: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """
        查询用户会话维度的问答审计记录。

        会话时间以最近一次助手回答时间为准；无回答会话回退到会话创建时间，便于管理员发现空会话。
        """

        result = ChatRepository(self.db).list_qa_audit_sessions(
            user_id=user_id,
            project_id=project_id,
            started_at=started_at,
            ended_at=ended_at,
            page=page,
            page_size=page_size,
        )
        return {
            **result,
            "items": [self._qa_audit_session_to_dict(item) for item in result["items"]],
        }

    def qa_audits(
        self,
        user_id: int | None = None,
        project_id: int | None = None,
        started_at: datetime | None = None,
        ended_at: datetime | None = None,
        feedback_status: str | None = None,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        """
        查询问答审计记录。

        返回:
            按助手回答分页的审计明细。
        """

        self._validate_feedback_filter(feedback_status)
        chat_repo = ChatRepository(self.db)
        result = chat_repo.list_qa_audit_details(
            user_id=user_id,
            project_id=project_id,
            started_at=started_at,
            ended_at=ended_at,
            feedback_status=feedback_status,
            page=page,
            page_size=page_size,
        )
        message_ids = [row[0].id for row in result["items"]]
        citations_by_message_id: dict[int, list[ChatCitation]] = {}
        for citation in chat_repo.list_citations_by_message_ids(message_ids):
            citations_by_message_id.setdefault(citation.message_id, []).append(citation)
        return {
            **result,
            "items": [
                self._qa_audit_detail_to_dict(row, chat_repo, citations_by_message_id.get(row[0].id, []))
                for row in result["items"]
            ],
        }

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

    def _qa_audit_session_to_dict(self, item: dict[str, Any]) -> dict[str, Any]:
        """序列化会话维度的问答审计摘要。"""

        session = item["session"]
        user = item["user"]
        project = item.get("project")
        return {
            "id": session.id,
            "session_id": session.id,
            "title": session.title,
            "user_id": session.user_id,
            "username": user.username,
            "real_name": user.real_name,
            "avatar_url": avatar_url_for_user(user),
            "avatar_updated_at": user.avatar_updated_at,
            "chat_type": session.chat_type,
            "mode": session.mode,
            "project_id": session.project_id,
            "project_name": project.name if project else None,
            "project_code": project.code if project else None,
            "question_count": item["question_count"],
            "answer_count": item["answer_count"],
            "citation_count": item["citation_count"],
            "latest_question": item["latest_question"],
            "latest_answer": item["latest_answer"],
            "latest_qa_at": item["latest_qa_at"],
            "created_at": session.created_at,
            "updated_at": session.updated_at,
        }

    def _qa_audit_detail_to_dict(
        self,
        row: Any,
        chat_repo: ChatRepository,
        citations: list[ChatCitation],
    ) -> dict[str, Any]:
        """序列化单条问答明细，并补齐 trace 缺失时的问题文本。"""

        message, session, user, project, trace, citation_count = row
        question = trace.question if trace and trace.question else chat_repo.get_previous_user_question(session.id, message.id)
        return {
            "id": message.id,
            "message_id": message.id,
            "session_id": session.id,
            "session_title": session.title,
            "user_id": session.user_id,
            "username": user.username,
            "real_name": user.real_name,
            "avatar_url": avatar_url_for_user(user),
            "avatar_updated_at": user.avatar_updated_at,
            "chat_type": session.chat_type,
            "mode": session.mode,
            "project_id": session.project_id,
            "project_name": project.name if project else None,
            "project_code": project.code if project else None,
            "question": question,
            "answer": message.content,
            "query_scope": message.query_scope,
            "agent_trace_json": message.agent_trace_json,
            "citation_count": int(citation_count or 0),
            "citations": [self._citation_to_dict(citation) for citation in citations],
            "retrievers": self._extract_retrievers(trace.retriever_hits_json if trace else None),
            "intent": trace.intent if trace else None,
            "elapsed_ms": trace.elapsed_ms if trace else None,
            "feedback_status": message.feedback_status,
            "answered_at": message.created_at,
            "created_at": message.created_at,
            "updated_at": message.updated_at,
        }

    def _citation_to_dict(self, citation: ChatCitation) -> dict[str, Any]:
        """序列化问答引用来源，字段与聊天消息接口保持一致。"""

        return {
            "source_type": citation.source_type,
            "knowledge_base_id": citation.knowledge_base_id,
            "project_id": citation.project_id,
            "document_id": citation.document_id,
            "chunk_id": citation.chunk_id,
            "drawing_no": citation.drawing_no,
            "file_name": citation.file_name,
            "page_number": citation.page_number,
            "content": citation.content,
            "assets": self._load_citation_assets(citation.assets_json),
        }

    def _load_citation_assets(self, raw_value: str | None) -> list[dict[str, Any]]:
        """安全读取引用图片资产 JSON，坏数据不影响审计列表加载。"""

        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            logger.warning("问答审计引用图片资产 JSON 解析失败，已忽略")
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    def _validate_feedback_filter(self, feedback_status: str | None) -> None:
        """校验问答反馈筛选参数。"""

        if feedback_status is None:
            return
        if feedback_status not in QA_FEEDBACK_FILTERS:
            raise AppException("不支持的问答反馈筛选", status_code=400, code=400)

    def _extract_retrievers(self, retriever_hits_json: str | None) -> list[str]:
        """从检索命中 JSON 中提取实际执行过的检索器。"""

        if not retriever_hits_json:
            return []
        try:
            parsed = json.loads(retriever_hits_json)
        except json.JSONDecodeError:
            logger.warning("问答审计检索器 JSON 解析失败，已返回空列表")
            return []
        if not isinstance(parsed, dict):
            return []
        hit_retrievers = [str(name) for name, count in parsed.items() if self._safe_int(count) > 0]
        return hit_retrievers or [str(name) for name in parsed]

    def _safe_int(self, value: Any) -> int:
        """将检索命中数安全转为整数。"""

        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

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
