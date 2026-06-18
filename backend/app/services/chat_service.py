"""
Chat Service

负责：
1. 管理问答会话与消息
2. 调用 Agent 完成知识问答
3. 保存引用来源、执行轨迹与审计数据
4. 支持同步与流式问答
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from app.agent.executor import AgentExecutor
from app.core.exceptions import AppException
from app.langgraph import RetrievalGraph
from app.models.chat import ChatCitation, ChatMessage, ChatSession
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import ChatCompletionRequest, ChatMessageFeedbackUpdate, ChatSessionCreate
from app.services.retrieval_trace_service import RetrievalTraceService
from app.services.system_service import SystemService

logger = logging.getLogger(__name__)


class ChatService:
    """问答服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repository = ChatRepository(db)

    def list_sessions(
        self,
        user: User,
        chat_type: str | None = None,
        project_id: int | None = None,
    ) -> list[ChatSession]:
        """查询当前用户会话列表。"""

        if chat_type is not None:
            self._validate_chat_type(chat_type)
        if chat_type == "project_chat" and project_id is None:
            return []
        if project_id is not None:
            from app.services.project_service import ProjectService

            ProjectService(self.db).ensure_project_access(project_id, user)
        return self.repository.list_sessions(user.id, chat_type, project_id)

    def create_session(self, payload: ChatSessionCreate, user: User) -> ChatSession:
        """创建问答会话。"""

        self._validate_chat_request(payload.chat_type, payload.project_id, user)
        session = ChatSession(
            user_id=user.id,
            title=payload.title,
            chat_type=payload.chat_type,
            mode=payload.mode,
            project_id=payload.project_id,
        )
        self.repository.add_session(session)
        SystemService(self.db).record_operation(user, "创建会话", "chat_session", session.id, session.title)
        self.db.commit()
        return session

    def list_messages(self, session_id: int, user: User) -> list[dict[str, Any]]:
        """查询会话消息。"""

        self._ensure_session_owner(session_id, user)
        messages = self.repository.list_messages(session_id)
        assistant_message_ids = [message.id for message in messages if message.role == "assistant"]
        citations_by_message_id: dict[int, list[ChatCitation]] = {}
        for citation in self.repository.list_citations_by_message_ids(assistant_message_ids):
            citations_by_message_id.setdefault(citation.message_id, []).append(citation)
        return [self._message_to_dict(message, citations_by_message_id.get(message.id, [])) for message in messages]

    def message_trace(self, message_id: int, user: User) -> dict[str, Any]:
        """查询助手消息对应的检索执行轨迹。"""

        message = self.repository.get_message(message_id)
        if not message:
            raise AppException("消息不存在", status_code=404, code=404)
        self._ensure_session_owner(message.session_id, user)
        trace = RetrievalTraceService(self.db).get_message_trace(message_id)
        if not trace:
            return {"message_id": message_id, "trace": None}
        return {
            "id": trace.id,
            "message_id": trace.message_id,
            "session_id": trace.session_id,
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

    def update_message_feedback(self, message_id: int, payload: ChatMessageFeedbackUpdate, user: User) -> dict[str, Any]:
        """更新当前用户可访问助手回答的点赞/点踩反馈。"""

        message = self.repository.get_message(message_id)
        if not message:
            raise AppException("消息不存在", status_code=404, code=404)
        self._ensure_session_owner(message.session_id, user)
        if message.role != "assistant":
            raise AppException("只能反馈助手回答", status_code=400, code=400)

        self.repository.update_message_feedback(message, payload.feedback_status)
        self.db.commit()
        logger.info(
            "问答反馈已更新: message_id=%s user_id=%s feedback_status=%s",
            message_id,
            user.id,
            payload.feedback_status or "none",
        )
        return {"message_id": message.id, "feedback_status": message.feedback_status}

    def delete_session(self, session_id: int, user: User) -> None:
        """删除会话。"""

        session = self._ensure_session_owner(session_id, user)
        self.repository.delete_session(session)
        SystemService(self.db).record_operation(user, "删除会话", "chat_session", session_id, "删除问答会话")
        self.db.commit()

    def complete(self, payload: ChatCompletionRequest, user: User) -> dict[str, Any]:
        """执行同步知识问答。"""

        self._validate_chat_request(payload.chat_type, payload.project_id, user)
        session = self._get_or_create_session(payload, user)
        self.repository.add_message(ChatMessage(session_id=session.id, user_id=user.id, role="user", content=payload.message))

        agent_result = AgentExecutor(self.db).run(payload.message, payload.chat_type, payload.mode, payload.project_id, user)
        return self._persist_agent_result(payload, user, session, agent_result)

    def complete_stream(self, payload: ChatCompletionRequest, user: User) -> Iterator[str]:
        """执行流式知识问答。"""

        self._validate_chat_request(payload.chat_type, payload.project_id, user)
        session = self._get_or_create_session(payload, user)
        self.repository.add_message(ChatMessage(session_id=session.id, user_id=user.id, role="user", content=payload.message))

        retrieval_graph = RetrievalGraph(self.db)
        initial_meta_payload = {
            "session_id": session.id,
            "chat_type": payload.chat_type,
            "mode": payload.mode,
            "query_scope": "自动判断",
            "used_retrievers": [],
            "agent_trace": [],
            "trace_steps": [],
            "citations": [],
            "raw": {},
        }

        def event_stream() -> Iterator[str]:
            answer_chunks: list[str] = []
            prepared_state: dict[str, Any] | None = None
            yield self._encode_sse("meta", initial_meta_payload)
            try:
                for event_name, event_payload in retrieval_graph.prepare_stream(
                    payload.message,
                    payload.chat_type,
                    payload.mode,
                    payload.project_id,
                    user,
                ):
                    if event_name == "trace_delta":
                        yield self._encode_sse("trace_delta", event_payload)
                        continue
                    if event_name == "prepared":
                        prepared_state = event_payload

                if prepared_state is None:
                    raise AppException("检索准备失败", status_code=502, code=502)

                meta_payload = {
                    "session_id": session.id,
                    "chat_type": prepared_state["chat_type"],
                    "mode": prepared_state["mode"],
                    "query_scope": prepared_state.get("query_scope") or "自动判断",
                    "used_retrievers": prepared_state.get("used_retrievers", []),
                    "agent_trace": prepared_state.get("trace", []),
                    "trace_steps": prepared_state.get("trace", []),
                    "citations": self._serialize_evidences(prepared_state.get("evidences", [])),
                    "raw": prepared_state.get("raw", {}),
                }
                yield self._encode_sse("meta", meta_payload)

                if prepared_state.get("direct_answer"):
                    answer = str(prepared_state.get("answer") or "").strip()
                    if not answer:
                        raise AppException("直答生成失败", status_code=502, code=502)
                    yield self._encode_sse("delta", {"content": answer})
                    agent_result = retrieval_graph.to_agent_result(prepared_state)
                    result = self._persist_agent_result(payload, user, session, agent_result)
                    yield self._encode_sse("done", result)
                    return

                answer_sequence = retrieval_graph.next_trace_sequence(prepared_state)
                yield self._encode_sse(
                    "trace_delta",
                    retrieval_graph.answer_running_trace_delta(prepared_state, answer_sequence),
                )
                answer_started_at = time.perf_counter()
                for delta in retrieval_graph.answer_generator.stream_generate(
                    payload.message,
                    prepared_state.get("evidences", []),
                    query_profile=prepared_state.get("query_profile", {}),
                ):
                    if not delta:
                        continue
                    answer_chunks.append(delta)
                    yield self._encode_sse("delta", {"content": delta})

                answer = "".join(answer_chunks).strip()
                if not answer:
                    raise AppException("LLM未返回有效内容", status_code=502, code=502)

                if retrieval_graph.answer_generator.last_model_route:
                    prepared_state.setdefault("model_routes", {})["answer"] = retrieval_graph.answer_generator.last_model_route

                agent_result = retrieval_graph.finalize_answer(
                    prepared_state,
                    answer,
                    elapsed_ms=int((time.perf_counter() - answer_started_at) * 1000),
                    trace_sequence=answer_sequence,
                )
                if agent_result.get("agent_trace"):
                    yield self._encode_sse("trace_delta", retrieval_graph.trace_delta_payload(agent_result["agent_trace"][-1]))
                result = self._persist_agent_result(payload, user, session, agent_result)
                yield self._encode_sse("done", result)
            except AppException as exc:
                self.db.rollback()
                logger.warning("知识问答流式输出失败: session_id=%s reason=%s", session.id, exc.message)
                yield self._encode_sse("error", {"message": exc.message, "code": exc.code})
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.exception("知识问答流式输出异常: session_id=%s", session.id)
                yield self._encode_sse("error", {"message": "知识问答流式输出失败，请稍后重试", "code": 500})

        return event_stream()

    def _persist_agent_result(
        self,
        payload: ChatCompletionRequest,
        user: User,
        session: ChatSession,
        agent_result: dict[str, Any],
    ) -> dict[str, Any]:
        """持久化回答、引用与检索轨迹，并返回统一响应。"""

        assistant_message = ChatMessage(
            session_id=session.id,
            user_id=None,
            role="assistant",
            content=agent_result["answer"],
            query_scope=agent_result["query_scope"],
            agent_trace_json=json.dumps(agent_result["agent_trace"], ensure_ascii=False),
        )
        self.repository.add_message(assistant_message)

        citations = self._build_chat_citations(assistant_message.id, agent_result["evidences"])
        self.repository.add_citations(citations)
        RetrievalTraceService(self.db).record_chat_trace(
            user=user,
            session_id=session.id,
            message_id=assistant_message.id,
            question=payload.message,
            chat_type=agent_result["chat_type"],
            mode=agent_result["mode"],
            project_id=payload.project_id,
            raw=agent_result.get("raw", {}),
            evidences=agent_result["evidences"],
            trace_steps=agent_result["agent_trace"],
        )
        SystemService(self.db).record_operation(
            user,
            "LLM调用",
            "chat",
            assistant_message.id,
            f"类型={agent_result['chat_type']}，模式={agent_result['mode']}，引用={len(citations)}",
        )
        self.db.commit()
        logger.info("知识问答完成: session_id=%s citations=%s", session.id, len(citations))

        return {
            "answer": agent_result["answer"],
            "session_id": session.id,
            "chat_type": agent_result["chat_type"],
            "mode": agent_result["mode"],
            "query_scope": agent_result["query_scope"],
            "used_retrievers": agent_result["used_retrievers"],
            "agent_trace": agent_result["agent_trace"],
            "trace_steps": agent_result.get("trace_steps", agent_result["agent_trace"]),
            "citations": [self._citation_to_dict(item) for item in citations],
            "feedback_status": assistant_message.feedback_status,
            "raw": {"message_id": assistant_message.id, **agent_result.get("raw", {})},
        }

    def _message_to_dict(self, message: ChatMessage, citations: list[ChatCitation]) -> dict[str, Any]:
        """序列化会话消息。"""

        return {
            "id": message.id,
            "session_id": message.session_id,
            "user_id": message.user_id,
            "role": message.role,
            "content": message.content,
            "query_scope": message.query_scope,
            "agent_trace_json": message.agent_trace_json,
            "feedback_status": message.feedback_status,
            "citations": [self._citation_to_dict(citation) for citation in citations],
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
        }

    def _citation_to_dict(self, citation: ChatCitation) -> dict[str, Any]:
        """序列化持久化的引用来源。"""

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
            "assets": self._load_assets_json(citation.assets_json),
        }

    def _serialize_evidences(self, evidences: list[Any]) -> list[dict[str, Any]]:
        """将临时证据序列化为前端可展示的引用来源。"""

        citations: list[dict[str, Any]] = []
        for evidence in evidences:
            citations.append(
                {
                    "source_type": evidence.source_type,
                    "knowledge_base_id": evidence.knowledge_base_id,
                    "project_id": evidence.project_id,
                    "document_id": evidence.document_id,
                    "chunk_id": evidence.chunk_id,
                    "drawing_no": evidence.drawing_no,
                    "file_name": evidence.file_name,
                    "page_number": evidence.page_number,
                    "content": evidence.content,
                    "assets": self._evidence_assets_to_dicts(evidence),
                }
            )
        return citations

    def _build_chat_citations(self, message_id: int, evidences: list[Any]) -> list[ChatCitation]:
        """将检索证据转换为可持久化的 ChatCitation。"""

        citations: list[ChatCitation] = []
        for evidence in evidences:
            assets = self._evidence_assets_to_dicts(evidence)
            citations.append(
                ChatCitation(
                    message_id=message_id,
                    source_type=evidence.source_type,
                    knowledge_base_id=evidence.knowledge_base_id,
                    project_id=evidence.project_id,
                    document_id=evidence.document_id,
                    chunk_id=evidence.chunk_id,
                    drawing_no=evidence.drawing_no,
                    file_name=evidence.file_name,
                    page_number=evidence.page_number,
                    content=evidence.content,
                    assets_json=json.dumps(assets, ensure_ascii=False) if assets else None,
                )
            )
        return citations

    def _evidence_assets_to_dicts(self, evidence: Any) -> list[dict[str, Any]]:
        """把 Evidence.assets 转成可持久化、可返回前端的安全元数据。"""

        assets: list[dict[str, Any]] = []
        for asset in getattr(evidence, "assets", []) or []:
            assets.append(
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
            )
        return assets

    def _load_assets_json(self, raw_value: str | None) -> list[dict[str, Any]]:
        """安全读取 citation 中保存的图片资产 JSON。"""

        if not raw_value:
            return []
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            logger.warning("引用图片资产 JSON 解析失败，已忽略")
            return []
        if not isinstance(parsed, list):
            return []
        return [item for item in parsed if isinstance(item, dict)]

    def _get_or_create_session(self, payload: ChatCompletionRequest, user: User) -> ChatSession:
        """获取或创建会话。"""

        if payload.session_id:
            session = self._ensure_session_owner(payload.session_id, user)
            if session.chat_type != payload.chat_type:
                raise AppException("会话类型与当前问答入口不一致", status_code=400, code=400)
            if payload.chat_type == "project_chat" and session.project_id != payload.project_id:
                raise AppException("项目问答会话必须绑定当前选择的项目", status_code=400, code=400)
            return session
        title = payload.message[:30] or "新的知识问答"
        session = ChatSession(
            user_id=user.id,
            title=title,
            chat_type=payload.chat_type,
            mode=payload.mode,
            project_id=payload.project_id,
        )
        self.repository.add_session(session)
        return session

    def _validate_chat_request(self, chat_type: str, project_id: int | None, user: User) -> None:
        """校验问答入口权限。"""

        self._validate_chat_type(chat_type)
        if chat_type == "project_chat":
            if project_id is None:
                raise AppException("项目问答必须选择项目", status_code=400, code=400)
            from app.services.project_service import ProjectService

            ProjectService(self.db).ensure_project_access(project_id, user)
            return
        if self._is_external_user(user):
            raise AppException("外部用户默认不能访问基础问答", status_code=403, code=403)

    def _validate_chat_type(self, chat_type: str) -> None:
        """校验问答类型枚举。"""

        if chat_type not in {"project_chat", "base_chat"}:
            raise AppException("不支持的问答类型", status_code=400, code=400)

    def _is_external_user(self, user: User) -> bool:
        """判断当前用户是否为外部用户。"""

        return any(role.code == "external" or "外部" in role.name for role in user.roles)

    def _ensure_session_owner(self, session_id: int, user: User) -> ChatSession:
        """校验会话归属。"""

        session = self.repository.get_session(session_id)
        if not session:
            raise AppException("会话不存在", status_code=404, code=404)
        if session.user_id != user.id and not any(role.code == "admin" for role in user.roles):
            raise AppException("无权访问该会话", status_code=403, code=403)
        return session

    def _encode_sse(self, event: str, payload: dict[str, Any]) -> str:
        """编码 SSE 事件。"""

        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
