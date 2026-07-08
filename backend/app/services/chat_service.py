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
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agent.executor import AgentExecutor
from app.core.exceptions import AppException
from app.core.rbac import has_permission
from app.langgraph import RetrievalGraph
from app.langgraph.retrieval_graph import (
    ANSWER_CONTEXT_TOP_K,
    DEFAULT_RETRIEVER_TOP_K,
    FUSED_EVIDENCE_TOP_K,
    GENERAL_ANSWER_PREFIX,
    RERANKED_EVIDENCE_TOP_K,
)
from app.models.chat import ChatCitation, ChatMessage, ChatSession
from app.models.document import Document
from app.models.knowledge_category import KnowledgeCategory
from app.models.user import User
from app.repositories.chat_repository import ChatRepository
from app.schemas.chat import ChatCompletionRequest, ChatMessageFeedbackUpdate, ChatSessionCreate, ChatSessionUpdate
from app.services.qwen_orchestration_service import QwenOrchestrationService
from app.services.retrieval_trace_service import RetrievalTraceService
from app.services.system_service import SystemService

logger = logging.getLogger(__name__)

AWAITING_GENERAL_CONFIRM = "AWAITING_GENERAL_CONFIRM"
NORMAL_CONVERSATION_STATE = "NORMAL"

VISIBLE_PROGRESS_TITLES = {
    "understanding": "正在理解你的问题",
    "planning": "正在规划资料检索方式",
    "retrieving": "正在检索相关资料",
    "filtering": "正在筛选可用依据",
    "answering": "正在整理回答内容",
}
VISIBLE_PROGRESS_DETAILS = {
    "understanding": {
        "pending": "等待开始理解问题",
        "running": "正在确认问题意图和回答范围",
        "success": "已确认问题意图和回答范围",
        "failed": "问题理解遇到波动，正在继续处理",
    },
    "planning": {
        "pending": "等待生成资料查找思路",
        "running": "正在选择适合的资料查找方式",
        "success": "已确定资料检索路径",
        "failed": "资料检索规划遇到波动，正在继续处理",
    },
    "retrieving": {
        "pending": "等待开始查找资料",
        "running": "正在查找可能相关的资料",
        "success": "已完成相关资料查找",
        "failed": "资料检索遇到问题，正在尝试继续处理",
    },
    "filtering": {
        "pending": "等待筛选可用依据",
        "running": "正在判断资料是否可以支持回答",
        "success": "已筛选可用于回答的依据",
        "failed": "依据筛选遇到问题，正在继续处理",
    },
    "answering": {
        "pending": "等待整理回答内容",
        "running": "正在基于可用依据组织回答",
        "success": "已完成回答整理",
        "failed": "回答整理遇到问题，正在继续处理",
    },
}
VISIBLE_PROGRESS_STAGE_ORDER = ("understanding", "planning", "retrieving", "filtering", "answering")
VISIBLE_PROGRESS_STAGE_INDEX = {stage: index for index, stage in enumerate(VISIBLE_PROGRESS_STAGE_ORDER)}
VISIBLE_PROGRESS_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "understanding",
        (
            "问答模式策略",
            "问答策略",
            "通用回答确认状态",
            "确认状态",
            "快速意图门控",
            "用户意图识别",
            "意图识别",
            "答案策略路由",
            "答案策略",
            "chat_policy",
            "confirm_state",
            "pre_intent_gate",
            "intent",
            "answer_policy_router",
        ),
    ),
    (
        "planning",
        (
            "任务拆解",
            "查询拆解",
            "查询画像生成",
            "查询画像",
            "问题理解生成",
            "问题理解",
            "策略解析",
            "数据检索规划",
            "检索规划",
            "query_decompose",
            "query_profile",
            "question_understanding",
            "policy_resolution",
            "planner",
        ),
    ),
    (
        "retrieving",
        (
            "检索执行",
            "向量检索",
            "关键词检索",
            "页级检索",
            "图谱检索",
            "精准检索",
            "精确检索",
            "项目资料检索",
            "内部知识检索",
            "检索召回与数据组装",
            "补充检索",
            "视觉图纸阅读",
            "retrieval",
            "retry_retrieval",
            "visual_reading",
            "visual_evidence",
        ),
    ),
    (
        "filtering",
        (
            "证据判断",
            "证据筛选",
            "资料聚合",
            "证据状态",
            "答案门控",
            "答案策略门控",
            "evidence_judge",
            "evidence_decision",
            "answer_policy_gate",
            "rerank",
            "context build",
        ),
    ),
    ("answering", ("回答生成", "LLM生成", "answer", "answer_generator", "direct_answer")),
)
RETRIEVAL_EMPTY_PATTERNS = ("未命中有效资料", "未找到足够的相关资料")
PROJECT_REFUSAL_PATTERNS = ("当前项目资料中未检索到", "当前项目资料中未找到")


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
            self._ensure_chat_action_permission(user, chat_type, "view")
        elif not (
            self._has_chat_action_permission(user, "base_chat", "view")
            or self._has_chat_action_permission(user, "project_chat", "view")
        ):
            raise AppException("No permission for chat sessions", status_code=403, code=403)
        if chat_type == "project_chat" and project_id is None:
            return []
        if project_id is not None:
            from app.services.project_access_service import ProjectAccessService
            from app.services.project_service import ProjectService

            if not ProjectAccessService(self.db).is_admin(user):
                ProjectService(self.db).ensure_project_access(project_id, user)
        return self.repository.list_sessions(user.id, chat_type, project_id)

    def create_session(self, payload: ChatSessionCreate, user: User) -> ChatSession:
        """创建问答会话。"""

        self._ensure_chat_action_permission(user, payload.chat_type, "create-session")
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

        session = self._ensure_session_owner(session_id, user)
        self._ensure_chat_action_permission(user, session.chat_type, "view")
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
        session = self._ensure_session_owner(message.session_id, user)
        self._ensure_chat_action_permission(user, session.chat_type, "view")
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
        session = self._ensure_session_owner(message.session_id, user)
        self._ensure_chat_action_permission(user, session.chat_type, "feedback")
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
        self._ensure_chat_action_permission(user, session.chat_type, "delete-session")
        cleanup_counts = self.repository.delete_session(session)
        SystemService(self.db).record_operation(user, "删除会话", "chat_session", session_id, "删除问答会话")
        self.db.commit()
        logger.info(
            "问答会话已删除: session_id=%s user_id=%s messages=%s citations=%s retrieval_traces=%s",
            session_id,
            user.id,
            cleanup_counts["messages"],
            cleanup_counts["citations"],
            cleanup_counts["retrieval_traces"],
        )

    def update_session(self, session_id: int, payload: ChatSessionUpdate, user: User) -> ChatSession:
        """更新会话展示属性。"""

        session = self._ensure_session_owner(session_id, user)
        self._ensure_chat_action_permission(user, session.chat_type, "manage-session")
        update_data = payload.model_dump(exclude_unset=True)
        if "title" in update_data and update_data["title"] is not None:
            title = str(update_data["title"]).strip()
            if not title:
                raise AppException("会话标题不能为空", status_code=400, code=400)
            session.title = title
        if "is_pinned" in update_data and update_data["is_pinned"] is not None:
            session.is_pinned = bool(update_data["is_pinned"])
        if "is_favorite" in update_data and update_data["is_favorite"] is not None:
            session.is_favorite = bool(update_data["is_favorite"])

        self.repository.update_session(session)
        SystemService(self.db).record_operation(user, "更新会话", "chat_session", session_id, session.title)
        self.db.commit()
        return session

    def complete(self, payload: ChatCompletionRequest, user: User) -> dict[str, Any]:
        """执行同步知识问答。"""

        self._ensure_chat_action_permission(user, payload.chat_type, "send-message")
        self._validate_chat_request(payload.chat_type, payload.project_id, user)
        session = self._get_or_create_session(payload, user)
        self.repository.add_message(ChatMessage(session_id=session.id, user_id=user.id, role="user", content=payload.message))

        pending_result = self._try_handle_general_confirmation(payload, user, session)
        if pending_result is not None:
            return pending_result

        agent_result = AgentExecutor(self.db).run(payload.message, payload.chat_type, payload.mode, payload.project_id, user)
        return self._persist_agent_result(payload, user, session, agent_result)

    def complete_stream(self, payload: ChatCompletionRequest, user: User) -> Iterator[str]:
        """执行流式知识问答。"""

        self._ensure_chat_action_permission(user, payload.chat_type, "send-message")
        self._validate_chat_request(payload.chat_type, payload.project_id, user)
        session = self._get_or_create_session(payload, user)
        self.repository.add_message(ChatMessage(session_id=session.id, user_id=user.id, role="user", content=payload.message))

        confirmation_decision = self._resolve_general_confirmation_decision(payload, session)
        initial_meta_payload = {
            "session_id": session.id,
            "chat_type": payload.chat_type,
            "mode": payload.mode,
            "query_scope": "自动判断",
            "used_retrievers": [],
            "agent_trace": [],
            "trace_steps": [],
            "progress_events": [],
            "citations": [],
            "raw": {},
        }

        def event_stream() -> Iterator[str]:
            answer_chunks: list[str] = []
            prepared_state: dict[str, Any] | None = None
            emitted_progress: dict[str, str] = {}
            yield self._encode_sse("meta", initial_meta_payload)
            try:
                if confirmation_decision is not None:
                    yield from self._stream_general_confirmation(payload, user, session, confirmation_decision, emitted_progress)
                    return

                retrieval_graph = RetrievalGraph(self.db)
                for event_name, event_payload in retrieval_graph.prepare_stream(
                    payload.message,
                    payload.chat_type,
                    payload.mode,
                    payload.project_id,
                    user,
                ):
                    if event_name == "trace_delta":
                        progress_event = self._progress_event_from_trace(event_payload)
                        if progress_event is not None and self._should_emit_progress(progress_event, emitted_progress):
                            yield self._encode_sse("progress", progress_event)
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
                    "used_retrievers": [],
                    "agent_trace": [],
                    "trace_steps": [],
                    "progress_events": self._build_visible_progress_events(prepared_state.get("trace", []), completed=False),
                    "citations": self._serialize_evidences(prepared_state.get("evidences", [])),
                    "raw": {},
                }
                yield self._encode_sse("meta", meta_payload)

                if prepared_state.get("direct_answer") or prepared_state.get("raw", {}).get("terminal_without_answer_generation"):
                    answer = str(prepared_state.get("answer") or "").strip()
                    if not answer:
                        raise AppException("回答生成失败", status_code=502, code=502)
                    if not self._has_progress_stage(prepared_state.get("trace", []), "answering"):
                        answer_sequence = retrieval_graph.next_trace_sequence(prepared_state)
                        answer_progress = self._progress_event_from_trace(
                            retrieval_graph.answer_running_trace_delta(prepared_state, answer_sequence)
                        )
                        if answer_progress is not None and self._should_emit_progress(answer_progress, emitted_progress):
                            yield self._encode_sse("progress", answer_progress)
                    yield self._encode_sse("delta", {"content": answer})
                    agent_result = retrieval_graph.to_agent_result(prepared_state)
                    result = self._persist_agent_result(payload, user, session, agent_result)
                    yield self._encode_sse("done", self._sanitize_stream_result(result))
                    return

                answer_sequence = retrieval_graph.next_trace_sequence(prepared_state)
                answer_progress = self._progress_event_from_trace(
                    retrieval_graph.answer_running_trace_delta(prepared_state, answer_sequence)
                )
                if answer_progress is not None and self._should_emit_progress(answer_progress, emitted_progress):
                    yield self._encode_sse("progress", answer_progress)
                answer_started_at = time.perf_counter()
                for delta in retrieval_graph.answer_generator.stream_generate(
                    payload.message,
                    prepared_state.get("evidences", []),
                    query_profile=prepared_state.get("query_profile", {}),
                    action=str(prepared_state.get("answer_policy_action") or "normal_answer"),
                    evidence_evaluation=prepared_state.get("evidence_evaluation", {}),
                    user=user,
                    request_id=prepared_state.get("raw", {}).get("run_id"),
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
                    final_progress = self._progress_event_from_trace(
                        retrieval_graph.trace_delta_payload(agent_result["agent_trace"][-1])
                    )
                    if final_progress is not None and self._should_emit_progress(final_progress, emitted_progress):
                        yield self._encode_sse("progress", final_progress)
                result = self._persist_agent_result(payload, user, session, agent_result)
                yield self._encode_sse("done", self._sanitize_stream_result(result))
            except AppException as exc:
                self.db.rollback()
                logger.warning("知识问答流式输出失败: session_id=%s reason=%s", session.id, exc.message)
                yield self._encode_sse("error", {"message": exc.message, "code": exc.code})
            except Exception as exc:  # noqa: BLE001
                self.db.rollback()
                logger.exception("知识问答流式输出异常: session_id=%s", session.id)
                yield self._encode_sse("error", {"message": "知识问答流式输出失败，请稍后重试", "code": 500})

        return event_stream()

    def _stream_general_confirmation(
        self,
        payload: ChatCompletionRequest,
        user: User,
        session: ChatSession,
        decision: tuple[str, str],
        emitted_progress: dict[str, str],
    ) -> Iterator[str]:
        """流式处理用户确认使用通用知识回答，先推送进度再执行耗时生成。"""

        decision_type, pending_question = decision
        if decision_type == "confirm":
            answer_progress = self._manual_progress_event("answering", "running", sequence=1, compact=True)
            if self._should_emit_progress(answer_progress, emitted_progress):
                yield self._encode_sse("progress", answer_progress)
            answer = self._build_confirmed_general_answer(pending_question)
            logger.info(
                "BaseChat通用回答确认命中: session_id=%s decision=CONFIRM pending_question_exists=%s",
                getattr(session, "id", None),
                bool(pending_question),
            )
            self._clear_general_confirmation(session)
            agent_result = self._build_general_confirmation_result(payload, answer, answer_type="general_llm", direct_llm_used=True)
        else:
            logger.info("BaseChat通用回答确认拒绝: session_id=%s decision=REJECT", getattr(session, "id", None))
            self._clear_general_confirmation(session)
            agent_result = self._build_general_confirmation_result(payload, "已取消通用知识回答。", answer_type="cancelled", refused=True)

        result = self._persist_agent_result(payload, user, session, agent_result)
        for progress_event in result.get("progress_events", []):
            if self._should_emit_progress(progress_event, emitted_progress):
                yield self._encode_sse("progress", progress_event)
        yield self._encode_sse("delta", {"content": result["answer"]})
        yield self._encode_sse("done", self._sanitize_stream_result(result))

    def _progress_event_from_trace(self, trace_item: dict[str, Any]) -> dict[str, Any] | None:
        """
        将内部 trace item 转换成普通用户可见进度。

        业务规则：
        - 只输出固定 stage/title/status/detail/sequence 字段。
        - 不透出耗时、节点实现、检索器名称、策略 code 或 raw payload。
        """

        stage = self._progress_stage_from_trace(trace_item)
        if stage is None:
            return None
        status = self._progress_status(trace_item.get("status"))
        source_text = self._trace_source_text(trace_item)
        return {
            "visible": True,
            "stage": stage,
            "title": self._progress_title(stage, status, source_text),
            "status": status,
            "detail": self._progress_detail(stage, status, source_text),
            "sequence": trace_item.get("sequence"),
        }

    def _build_visible_progress_events(self, trace_steps: list[dict[str, Any]], *, completed: bool) -> list[dict[str, Any]]:
        """从完整内部 trace 生成去重后的用户可见进度列表。"""

        events = [event for step in trace_steps if (event := self._progress_event_from_trace(step)) is not None]
        if completed and events and not any(event["stage"] == "answering" for event in events):
            events.append(
                {
                    "visible": True,
                    "stage": "answering",
                    "title": VISIBLE_PROGRESS_TITLES["answering"],
                    "status": "success",
                    "detail": self._progress_detail("answering", "success", ""),
                    "sequence": None,
                }
            )
        normalized = self._normalize_progress_events(events)
        return self._mark_progress_complete(normalized) if completed else normalized

    def _sanitize_stream_result(self, result: dict[str, Any]) -> dict[str, Any]:
        """普通用户流式完成事件只返回答案、引用和清洗后的进度。"""

        safe_result = dict(result)
        custom_progress_events = safe_result.get("progress_events")
        progress_events = (
            custom_progress_events
            if isinstance(custom_progress_events, list)
            else self._build_visible_progress_events(
                safe_result.get("agent_trace", []),
                completed=True,
            )
        )
        safe_result["progress_events"] = progress_events
        safe_result["agent_trace"] = []
        safe_result["trace_steps"] = []
        safe_result["trace"] = []
        safe_result["used_retrievers"] = []
        for debug_key in (
            "answer_type",
            "intent_type",
            "answer_policy",
            "evidence_status",
            "need_user_confirm",
            "pending_action",
            "sources",
        ):
            safe_result.pop(debug_key, None)
        raw = safe_result.get("raw") if isinstance(safe_result.get("raw"), dict) else {}
        safe_result["raw"] = {"message_id": raw.get("message_id")}
        return safe_result

    def _should_emit_progress(self, event: dict[str, Any], emitted_progress: dict[str, str]) -> bool:
        stage = str(event.get("stage") or "")
        signature = f"{event.get('status')}::{event.get('title')}::{event.get('detail')}"
        if emitted_progress.get(stage) == signature:
            return False
        emitted_progress[stage] = signature
        return True

    def _manual_progress_event(
        self,
        stage: str,
        status: str,
        *,
        sequence: int | None = None,
        compact: bool = False,
    ) -> dict[str, Any]:
        """构造无内部 trace 依赖的用户可见进度事件。"""

        event = {
            "visible": True,
            "stage": stage,
            "title": VISIBLE_PROGRESS_TITLES[stage],
            "status": status,
            "detail": self._progress_detail(stage, status, ""),
            "sequence": sequence,
        }
        if compact:
            event["compact"] = True
        return event

    def _has_progress_stage(self, trace_steps: list[dict[str, Any]], stage: str) -> bool:
        """判断 trace 是否已经包含指定的用户可见阶段，避免直接回答重复回退进度。"""

        return any(self._progress_stage_from_trace(step) == stage for step in trace_steps)

    def _progress_stage_from_trace(self, trace_item: dict[str, Any]) -> str | None:
        explicit_stage = trace_item.get("stage")
        if explicit_stage in VISIBLE_PROGRESS_TITLES:
            return str(explicit_stage)
        source_text = self._trace_source_text(trace_item).lower()
        for stage, keywords in VISIBLE_PROGRESS_KEYWORDS:
            if any(keyword.lower() in source_text for keyword in keywords):
                return stage
        return None

    def _progress_status(self, raw_status: Any) -> str:
        status = str(raw_status or "success")
        if status in {"pending", "running", "success", "failed"}:
            return status
        return "success"

    def _progress_title(self, stage: str, status: str, source_text: str) -> str:
        if stage == "retrieving" and status == "failed":
            return "资料检索遇到问题，正在尝试继续处理"
        if stage == "retrieving" and any(pattern in source_text for pattern in RETRIEVAL_EMPTY_PATTERNS):
            return "未找到足够的相关资料"
        return VISIBLE_PROGRESS_TITLES[stage]

    def _progress_detail(self, stage: str, status: str, source_text: str) -> str:
        """生成普通用户可读的阶段结论，避免把内部策略和检索实现透出到前端。"""

        if stage == "retrieving" and status == "failed":
            return "已切换为继续处理，尽量保留可用信息"
        if stage == "retrieving" and any(pattern in source_text for pattern in RETRIEVAL_EMPTY_PATTERNS):
            return "未找到足够相关资料，后续会基于可确认内容作答"
        if any(pattern in source_text for pattern in PROJECT_REFUSAL_PATTERNS):
            return "当前项目资料中未找到可以支持回答的内容"
        return VISIBLE_PROGRESS_DETAILS[stage][status]

    def _trace_source_text(self, trace_item: dict[str, Any]) -> str:
        return "\n".join(
            str(trace_item.get(key) or "")
            for key in ("step", "implementation", "display_text", "result")
            if trace_item.get(key) is not None
        )

    def _normalize_progress_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_stage: dict[str, dict[str, Any]] = {}
        for event in events:
            stage = str(event.get("stage") or "")
            if stage not in VISIBLE_PROGRESS_TITLES:
                continue
            status = self._progress_status(event.get("status"))
            by_stage[stage] = {
                "visible": True,
                "stage": stage,
                "title": self._progress_title(stage, status, str(event.get("title") or "")),
                "status": status,
                "detail": self._progress_detail(stage, status, str(event.get("title") or event.get("detail") or "")),
                "sequence": event.get("sequence"),
            }
        return [by_stage[stage] for stage in VISIBLE_PROGRESS_STAGE_ORDER if stage in by_stage]

    def _mark_progress_complete(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []
        latest_index = max(VISIBLE_PROGRESS_STAGE_INDEX[str(event["stage"])] for event in events)
        by_stage = {str(event["stage"]): event for event in events}
        completed_events: list[dict[str, Any]] = []
        for stage in VISIBLE_PROGRESS_STAGE_ORDER[: latest_index + 1]:
            completed_events.append(
                {
                    "visible": True,
                    "stage": stage,
                    "title": VISIBLE_PROGRESS_TITLES[stage],
                    "status": "success",
                    "detail": self._progress_detail(
                        stage,
                        "success",
                        str(by_stage.get(stage, {}).get("title") or by_stage.get(stage, {}).get("detail") or ""),
                    ),
                    "sequence": by_stage.get(stage, {}).get("sequence"),
                }
            )
        return completed_events

    def _try_handle_general_confirmation(
        self,
        payload: ChatCompletionRequest,
        user: User,
        session: ChatSession,
    ) -> dict[str, Any] | None:
        """处理 base_chat 等待用户确认通用回答的会话状态。"""

        decision = self._resolve_general_confirmation_decision(payload, session)
        if decision is None:
            return None

        decision_type, pending_question = decision
        if decision_type == "confirm":
            answer = self._build_confirmed_general_answer(pending_question)
            logger.info(
                "BaseChat通用回答确认命中: session_id=%s decision=CONFIRM pending_question_exists=%s",
                getattr(session, "id", None),
                bool(pending_question),
            )
            self._clear_general_confirmation(session)
            return self._persist_agent_result(
                payload,
                user,
                session,
                self._build_general_confirmation_result(payload, answer, answer_type="general_llm", direct_llm_used=True),
            )

        logger.info("BaseChat通用回答确认拒绝: session_id=%s decision=REJECT", getattr(session, "id", None))
        self._clear_general_confirmation(session)
        return self._persist_agent_result(
            payload,
            user,
            session,
            self._build_general_confirmation_result(payload, "已取消通用知识回答。", answer_type="cancelled", refused=True),
        )

    def _resolve_general_confirmation_decision(
        self,
        payload: ChatCompletionRequest,
        session: ChatSession,
    ) -> tuple[str, str] | None:
        """识别确认态会话的用户决定；非确认回复会清理挂起状态并走新问题流程。"""

        if (
            session.conversation_state != AWAITING_GENERAL_CONFIRM
            or session.pending_chat_type != "base_chat"
            or not session.pending_general_question
        ):
            return None

        normalized = payload.message.strip().lower().replace(" ", "")
        confirm_words = {
            "是",
            "可以",
            "需要",
            "继续",
            "用",
            "用通用知识",
            "用通用知识回答",
            "用基模回答",
            "帮我回答",
            "继续回答",
            "可以用通用知识回答",
            "好的",
            "好",
            "请回答",
            "确认",
        }
        reject_words = {"否", "不用", "不需要", "取消", "算了", "不要", "先不用"}
        pending_question = session.pending_general_question

        if normalized in confirm_words or any(word in normalized for word in confirm_words if len(word) >= 2):
            return "confirm", pending_question

        if normalized in reject_words or any(word in normalized for word in reject_words if len(word) >= 2):
            return "reject", pending_question

        logger.info("BaseChat确认阶段识别为新问题: session_id=%s clear_pending=true", getattr(session, "id", None))
        self._clear_general_confirmation(session)
        return None

    def _build_confirmed_general_answer(self, question: str) -> str:
        """生成用户确认后的通用知识回答。"""

        return f"{GENERAL_ANSWER_PREFIX}\n{QwenOrchestrationService(self.db).answer_general_question(question)}"

    def _clear_general_confirmation(self, session: ChatSession) -> None:
        session.conversation_state = NORMAL_CONVERSATION_STATE
        session.pending_general_question = None
        session.pending_chat_type = None
        session.pending_answer_policy = None
        session.pending_evidence_status = None
        session.pending_created_at = None
        self.repository.update_session(session)

    def _build_general_confirmation_result(
        self,
        payload: ChatCompletionRequest,
        answer: str,
        *,
        answer_type: str,
        direct_llm_used: bool = False,
        refused: bool = False,
    ) -> dict[str, Any]:
        trace = [
            {
                "sequence": 1,
                "step": "通用回答确认状态",
                "implementation": "chat_session",
                "status": "success",
                "details": {"pending_general_question_used": direct_llm_used, "refused": refused},
            }
        ]
        progress_events = (
            [self._manual_progress_event("answering", "success", sequence=1, compact=True)]
            if direct_llm_used
            else []
        )
        return {
            "answer": answer,
            "chat_type": payload.chat_type,
            "mode": payload.mode,
            "answer_type": answer_type,
            "intent_type": "confirm_general_answer" if direct_llm_used else "reject_general_answer",
            "answer_policy": "GENERAL_ALLOWED" if direct_llm_used else "KB_FIRST",
            "evidence_status": "EMPTY",
            "need_user_confirm": False,
            "pending_action": None,
            "query_scope": "通用知识",
            "used_retrievers": [],
            "agent_trace": trace,
            "trace_steps": trace,
            "progress_events": progress_events,
            "evidences": [],
            "raw": {
                "candidate_k": DEFAULT_RETRIEVER_TOP_K,
                "rerank_top_k": FUSED_EVIDENCE_TOP_K,
                "eval_top_k": RERANKED_EVIDENCE_TOP_K,
                "answer_top_k": ANSWER_CONTEXT_TOP_K,
                "reranker_used": False,
                "direct_llm_used": direct_llm_used,
                "kb_grounded": False,
                "refused": refused,
                "need_general_confirm": False,
            },
        }

    def _persist_agent_result(
        self,
        payload: ChatCompletionRequest,
        user: User,
        session: ChatSession,
        agent_result: dict[str, Any],
    ) -> dict[str, Any]:
        """持久化回答、引用与检索轨迹，并返回统一响应。"""

        custom_progress_events = agent_result.get("progress_events")
        progress_events = (
            custom_progress_events
            if isinstance(custom_progress_events, list)
            else self._build_visible_progress_events(agent_result["agent_trace"], completed=True)
        )
        assistant_message = ChatMessage(
            session_id=session.id,
            user_id=None,
            role="assistant",
            content=agent_result["answer"],
            query_scope=agent_result["query_scope"],
            agent_trace_json=json.dumps(agent_result["agent_trace"], ensure_ascii=False),
            progress_json=json.dumps(progress_events, ensure_ascii=False),
        )
        self.repository.add_message(assistant_message)

        citations = self._build_chat_citations(assistant_message.id, agent_result["evidences"])
        self.repository.add_citations(citations)
        if agent_result.get("need_user_confirm") and agent_result.get("pending_action") in {
            "confirm_general_answer",
            "general_answer_confirm",
        }:
            session.conversation_state = AWAITING_GENERAL_CONFIRM
            session.pending_general_question = payload.message
            session.pending_chat_type = "base_chat"
            session.pending_answer_policy = str(agent_result.get("answer_policy") or "KB_FIRST")
            session.pending_evidence_status = str(agent_result.get("evidence_status") or "")
            session.pending_created_at = datetime.utcnow()
            self.repository.update_session(session)
            logger.info(
                "基础问答证据不足等待确认: session_id=%s evidence_status=%s pending_general_question_exists=%s",
                session.id,
                session.pending_evidence_status,
                bool(session.pending_general_question),
            )
        elif session.conversation_state == AWAITING_GENERAL_CONFIRM and not agent_result.get("need_user_confirm"):
            self._clear_general_confirmation(session)
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
        audit_action = "项目问答" if agent_result["chat_type"] == "project_chat" else "基础问答"
        SystemService(self.db).record_operation(
            user,
            audit_action,
            "chat_message",
            assistant_message.id,
            json.dumps(
                {
                    "session_id": session.id,
                    "chat_type": agent_result["chat_type"],
                    "mode": agent_result["mode"],
                    "citation_count": len(citations),
                    "evidence_count": len(agent_result["evidences"]),
                    "answer_policy": agent_result.get("answer_policy"),
                    "evidence_status": agent_result.get("evidence_status"),
                },
                ensure_ascii=False,
            ),
            project_id=payload.project_id,
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

        citation_dicts = [self._citation_to_dict(item) for item in citations]
        trace_steps = agent_result.get("trace_steps", agent_result["agent_trace"])
        return {
            "answer": agent_result["answer"],
            "session_id": session.id,
            "chat_type": agent_result["chat_type"],
            "mode": agent_result["mode"],
            "answer_type": agent_result.get("answer_type"),
            "intent_type": agent_result.get("intent_type"),
            "answer_policy": agent_result.get("answer_policy"),
            "evidence_status": agent_result.get("evidence_status"),
            "query_scope": agent_result["query_scope"],
            "used_retrievers": agent_result["used_retrievers"],
            "agent_trace": agent_result["agent_trace"],
            "trace_steps": trace_steps,
            "trace": trace_steps,
            "progress_events": progress_events,
            "citations": citation_dicts,
            "sources": citation_dicts,
            "need_user_confirm": bool(agent_result.get("need_user_confirm")),
            "pending_action": agent_result.get("pending_action"),
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
            "agent_trace_json": None,
            "progress_json": self._message_progress_json(message),
            "feedback_status": message.feedback_status,
            "citations": [self._citation_to_dict(citation) for citation in citations],
            "created_at": message.created_at.isoformat() if message.created_at else None,
            "updated_at": message.updated_at.isoformat() if message.updated_at else None,
        }

    def _message_progress_json(self, message: ChatMessage) -> str | None:
        """读取普通聊天页可用进度；旧消息缺少 progress_json 时现场从审计 trace 派生。"""

        if message.progress_json:
            return message.progress_json
        if not message.agent_trace_json:
            return None
        try:
            parsed = json.loads(message.agent_trace_json)
        except json.JSONDecodeError:
            logger.warning("助手消息进度派生失败: message_id=%s reason=invalid_trace_json", message.id)
            return None
        if not isinstance(parsed, list):
            return None
        progress_events = self._build_visible_progress_events(parsed, completed=True)
        return json.dumps(progress_events, ensure_ascii=False) if progress_events else None

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
            **self._citation_directory_metadata(citation),
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
                    "directory_id": (evidence.metadata or {}).get("directory_id"),
                    "directory": self._evidence_directory_name(evidence),
                    "directory_name": self._evidence_directory_name(evidence),
                    "page_number": evidence.page_number,
                    "content": evidence.content,
                    "assets": self._evidence_assets_to_dicts(evidence),
                }
            )
        return citations

    def _evidence_directory_name(self, evidence: Any) -> str | None:
        metadata = getattr(evidence, "metadata", None) or {}
        return metadata.get("directory_name") or metadata.get("directory_code")

    def _citation_directory_metadata(self, citation: ChatCitation) -> dict[str, Any]:
        document = self.db.get(Document, citation.document_id)
        directory_id = None
        if document is not None:
            directory_id = getattr(document, "directory_id", None) or getattr(document, "category_id", None)
        if directory_id is None:
            return {"directory_id": None, "directory": None, "directory_name": None}
        category = self.db.get(KnowledgeCategory, directory_id)
        directory_name = category.name if category is not None else None
        return {"directory_id": directory_id, "directory": directory_name, "directory_name": directory_name}

    def _citation_required_source_ids(self, evidence: Any) -> tuple[int, int, int] | None:
        """校验引用是否能追溯到真实知识库、文档和 chunk。"""

        metadata = getattr(evidence, "metadata", None) or {}
        if metadata.get("metadata_only"):
            return None
        knowledge_base_id = self._positive_int_id(getattr(evidence, "knowledge_base_id", None))
        document_id = self._positive_int_id(getattr(evidence, "document_id", None))
        chunk_id = self._positive_int_id(getattr(evidence, "chunk_id", None))
        if knowledge_base_id is None or document_id is None or chunk_id is None:
            return None
        return knowledge_base_id, document_id, chunk_id

    @staticmethod
    def _positive_int_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            candidate = int(value)
        except (TypeError, ValueError):
            return None
        return candidate if candidate > 0 else None

    def _build_chat_citations(self, message_id: int, evidences: list[Any]) -> list[ChatCitation]:
        """将检索证据转换为可持久化的 ChatCitation。"""

        citations: list[ChatCitation] = []
        for evidence in evidences:
            source_ids = self._citation_required_source_ids(evidence)
            if source_ids is None:
                logger.info(
                    "跳过不可持久化引用: message_id=%s source_type=%s retriever=%s project_id=%s "
                    "knowledge_base_id=%s document_id=%s chunk_id=%s metadata_only=%s",
                    message_id,
                    getattr(evidence, "source_type", None),
                    getattr(evidence, "retriever", None),
                    getattr(evidence, "project_id", None),
                    getattr(evidence, "knowledge_base_id", None),
                    getattr(evidence, "document_id", None),
                    getattr(evidence, "chunk_id", None),
                    bool((getattr(evidence, "metadata", None) or {}).get("metadata_only")),
                )
                continue
            knowledge_base_id, document_id, chunk_id = source_ids
            assets = self._evidence_assets_to_dicts(evidence)
            citations.append(
                ChatCitation(
                    message_id=message_id,
                    source_type=evidence.source_type,
                    knowledge_base_id=knowledge_base_id,
                    project_id=evidence.project_id,
                    document_id=document_id,
                    chunk_id=chunk_id,
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
        self._ensure_chat_action_permission(user, payload.chat_type, "create-session")
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
            from app.services.project_access_service import ProjectAccessService

            ProjectAccessService(self.db).ensure_project_access(project_id, user, permission_codes=("project:chat",))
            return
        if self._is_external_user(user):
            raise AppException("外部用户默认不能访问基础问答", status_code=403, code=403)

    def _chat_permission_code(self, chat_type: str, action: str) -> str:
        self._validate_chat_type(chat_type)
        prefix = "ai:project-chat" if chat_type == "project_chat" else "ai:base-chat"
        return f"{prefix}:{action}"

    def _has_chat_action_permission(self, user: User, chat_type: str, action: str) -> bool:
        return has_permission(user, self._chat_permission_code(chat_type, action))

    def _ensure_chat_action_permission(self, user: User, chat_type: str, action: str) -> None:
        if not self._has_chat_action_permission(user, chat_type, action):
            raise AppException("No permission for chat action", status_code=403, code=403)

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
