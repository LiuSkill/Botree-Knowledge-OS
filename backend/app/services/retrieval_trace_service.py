"""
Retrieval Trace Service

负责：
1. 将 LangGraph 在线问答执行过程写入 retrieval_traces
2. 提供消息级 trace 查询和系统级审计列表
3. 保持检索审计与 ChatService 解耦
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.retrieval_trace import RetrievalTrace
from app.models.user import User
from app.repositories.retrieval_trace_repository import RetrievalTraceRepository
from app.retrieval.schemas import Evidence


class RetrievalTraceService:
    """
    检索审计服务

    职责：
    - 记录问答检索链路
    - 查询消息关联 trace
    - 供系统管理页面查看最近检索审计
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.repository = RetrievalTraceRepository(db)

    def record_chat_trace(
        self,
        user: User,
        session_id: int,
        message_id: int,
        question: str,
        chat_type: str,
        mode: str,
        project_id: int | None,
        raw: dict[str, Any],
        evidences: list[Evidence],
        trace_steps: list[dict[str, Any]],
    ) -> RetrievalTrace | None:
        """
        保存问答检索 trace。

        参数:
            user: 当前用户。
            session_id: 会话ID。
            message_id: 助手消息ID。
            question: 用户问题。
            chat_type: 问答类型。
            mode: 实际检索模式。
            project_id: 项目ID。
            raw: LangGraph 原始调试数据。
            evidences: 最终证据。
            trace_steps: 节点执行轨迹。

        返回:
            检索审计记录；关闭审计时返回 None。
        """

        if not self.settings.retrieval_trace_enabled:
            return None
        elapsed_ms = sum(int(step.get("elapsed_ms") or 0) for step in trace_steps)
        knowledge_base_id = self._resolve_trace_knowledge_base_id(evidences)
        trace = RetrievalTrace(
            user_id=user.id,
            session_id=session_id,
            message_id=message_id,
            chat_type=chat_type,
            mode=mode,
            knowledge_base_id=knowledge_base_id,
            project_id=project_id,
            question=question,
            intent=raw.get("intent"),
            sub_queries_json=json.dumps(raw.get("sub_queries", []), ensure_ascii=False),
            retriever_hits_json=json.dumps(raw.get("retriever_hits", {}), ensure_ascii=False),
            rerank_result_json=json.dumps(raw.get("rerank_details", []), ensure_ascii=False),
            citations_json=json.dumps([self._evidence_to_dict(item) for item in evidences], ensure_ascii=False),
            trace_json=json.dumps(trace_steps, ensure_ascii=False),
            elapsed_ms=elapsed_ms,
        )
        self.repository.add(trace)
        return trace

    def list_recent(self) -> list[RetrievalTrace]:
        """查询最近检索审计记录。"""

        return self.repository.list_recent()

    def get_message_trace(self, message_id: int) -> RetrievalTrace | None:
        """按助手消息 ID 查询 trace。"""

        return self.repository.get_by_message(message_id)

    def _evidence_to_dict(self, evidence: Evidence) -> dict:
        """将 Evidence 转换为 JSON 可序列化字典。"""

        return {
            "source_type": evidence.source_type,
            "knowledge_base_id": evidence.knowledge_base_id,
            "project_id": evidence.project_id,
            "document_id": evidence.document_id,
            "drawing_no": evidence.drawing_no,
            "page_number": evidence.page_number,
            "chunk_id": evidence.chunk_id,
            "file_name": evidence.file_name,
            "retriever": evidence.retriever,
            "score": evidence.score,
            "metadata": evidence.metadata,
            "assets": [
                {
                    "asset_id": asset.asset_id,
                    "asset_type": asset.asset_type,
                    "url": asset.url,
                    "mime_type": asset.mime_type,
                    "file_name": asset.file_name,
                    "file_size": asset.file_size,
                    "page_number": asset.page_number,
                    "block_id": asset.block_id,
                    "metadata": asset.metadata,
                }
                for asset in evidence.assets
            ],
        }

    def _resolve_trace_knowledge_base_id(self, evidences: list[Evidence]) -> int | None:
        """
        解析可持久化的知识库 ID。

        项目元数据检索会使用 0 作为占位 knowledge_base_id，写入 retrieval_traces
        时需要归一化为 None，避免触发知识库外键约束；若后续证据存在真实知识库，
        则优先记录首个合法知识库 ID，便于后台按知识库筛选审计轨迹。
        """

        for evidence in evidences:
            knowledge_base_id = self._positive_int_id(getattr(evidence, "knowledge_base_id", None))
            if knowledge_base_id is not None:
                return knowledge_base_id
        return None

    @staticmethod
    def _positive_int_id(value: Any) -> int | None:
        """仅保留大于 0 的整型 ID，过滤占位值和异常输入。"""

        if isinstance(value, bool):
            return None
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            return None
        return candidate if candidate > 0 else None
