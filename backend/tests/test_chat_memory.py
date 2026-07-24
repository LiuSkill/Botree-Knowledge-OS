"""
Chat Memory Tests

负责：
1. 验证会话级短期记忆的公开行为
2. 锁定同步问答对短期记忆失败的降级策略
3. 验证检索图中的短期记忆节点顺序
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.dialects import mysql
from sqlalchemy.schema import CreateTable

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import Base, ChatMessage, ChatSession  # noqa: E402
from app.models.user import Role, User  # noqa: E402
from app.langgraph.retrieval_graph import RetrievalGraph  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402
from app.schemas.chat import ChatCompletionRequest  # noqa: E402
from app.services.chat_memory_service import (  # noqa: E402
    ChatMemoryService,
    MemoryCitationAnchor,
    TurnOutcome,
)
from app.services.chat_service import ChatService  # noqa: E402


def make_session() -> Session:
    """创建独立内存数据库会话。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def make_admin_user() -> User:
    """创建具备问答权限的管理员测试用户。"""

    user = User(id=1, username="admin", password_hash="x", real_name="Admin")
    user.roles = [Role(id=1, name="Admin", code="admin", enabled=True)]
    return user


def _build_turn_outcome(
    *,
    session_id: int,
    user_message_id: int,
    assistant_message_id: int,
    question: str,
    answer: str,
    chat_type: str = "project_chat",
    project_id: int | None = 1,
    evidence_status: str = "ENOUGH",
) -> TurnOutcome:
    evidence = Evidence(
        score=0.95,
        source_type="project" if chat_type == "project_chat" else "base",
        knowledge_base_id=1,
        project_id=project_id,
        document_id=11,
        chunk_id=21,
        drawing_no=None,
        file_name="source.pdf",
        page_number=1,
        content="项目资料说明：黑粉进料经过给料系统进入浸出段，再进入过滤单元。",
        retriever="milvus",
        metadata={"security_level": "public"},
    )
    return TurnOutcome(
        session_id=session_id,
        user_message_id=user_message_id,
        assistant_message_id=assistant_message_id,
        user_message=question,
        answer=answer,
        answer_type="normal_answer",
        evidence_status=evidence_status,
        chat_type=chat_type,
        project_id=project_id,
        citations=[
            MemoryCitationAnchor(
                citation_id=1,
                source_type=evidence.source_type,
                knowledge_base_id=evidence.knowledge_base_id,
                project_id=evidence.project_id,
                document_id=evidence.document_id,
                chunk_id=evidence.chunk_id,
                file_name=evidence.file_name,
                page_number=evidence.page_number,
            )
        ],
        evidences=[evidence],
        trace_steps=[],
        raw={},
        turn_context=None,
    )


def test_chat_memory_finalize_then_prepare_rewrites_follow_up() -> None:
    """证据支持的上一轮主题应能帮助承接明显追问。"""

    db = make_session()
    try:
        session = ChatSession(user_id=1, title="短期记忆测试", chat_type="project_chat", mode="auto", project_id=1)
        db.add(session)
        db.flush()

        user_message = ChatMessage(session_id=session.id, user_id=1, role="user", content="黑粉进料流程是什么")
        assistant_message = ChatMessage(session_id=session.id, user_id=None, role="assistant", content="先给料，再浸出，最后过滤。")
        db.add_all([user_message, assistant_message])
        db.flush()

        memory_service = ChatMemoryService(db)
        outcome = _build_turn_outcome(
            session_id=session.id,
            user_message_id=user_message.id,
            assistant_message_id=assistant_message.id,
            question=user_message.content,
            answer=assistant_message.content,
        )
        result = memory_service.finalize_turn_memory(session, outcome)
        db.commit()

        snapshot = json.loads(str(session.memory_state_json or "{}"))
        assert result.updated is True
        assert snapshot["schema_version"] == 1
        assert snapshot["stable_context"]["chat_type"] == "project_chat"
        assert snapshot["topic_context"]["topic_label"] == "黑粉进料流程是什么"
        assert snapshot["confirmed_contexts"][0]["anchor"]["source_kind"] == "assistant_final_with_citation"

        follow_up = ChatMessage(session_id=session.id, user_id=1, role="user", content="第二步呢")
        db.add(follow_up)
        db.flush()

        turn_context = memory_service.prepare_turn_context(session, follow_up, follow_up.content)

        assert turn_context.memory_trigger_mode == "rewrite_single"
        assert turn_context.effective_question == "关于黑粉进料流程是什么，第二步呢"
        assert turn_context.memory_trace["decision_reason"] == "context_dependent_with_memory"
        assert turn_context.memory_referenced_context_ids
    finally:
        db.close()


def test_chat_service_complete_does_not_fail_when_memory_writeback_raises(monkeypatch) -> None:
    """短期记忆写回失败不能阻断主回答落库。"""

    db = make_session()
    try:
        user = make_admin_user()

        class FakeExecutor:
            def __init__(self, _db):
                self.db = _db

            def run(self, question, chat_type, mode, project_id, _user, *, turn_context=None):
                return {
                    "answer": f"回答：{question}",
                    "chat_type": chat_type,
                    "mode": mode,
                    "answer_type": "normal_answer",
                    "intent_type": "knowledge_qa",
                    "answer_policy": "STRICT_KB" if chat_type == "project_chat" else "KB_FIRST",
                    "evidence_status": "EMPTY",
                    "query_scope": "自动判断",
                    "used_retrievers": [],
                    "agent_trace": [],
                    "trace_steps": [],
                    "evidences": [],
                    "raw": {
                        "memory_original_question": question,
                        "memory_effective_question": turn_context.effective_question if turn_context else question,
                    },
                }

        monkeypatch.setattr("app.services.chat_service.AgentExecutor", FakeExecutor)
        monkeypatch.setattr("app.services.chat_service.SystemService.record_operation", lambda *args, **kwargs: None)
        monkeypatch.setattr("app.services.chat_service.RetrievalTraceService.record_chat_trace", lambda *args, **kwargs: None)
        monkeypatch.setattr(
            "app.services.chat_service.ChatMemoryService.finalize_turn_memory",
            lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        )

        result = ChatService(db).complete(ChatCompletionRequest(message="黑粉进料流程是什么"), user)

        session = db.get(ChatSession, result["session_id"])
        assert result["answer"] == "回答：黑粉进料流程是什么"
        assert session is not None
        assert db.scalar(select(func.count()).select_from(ChatMessage)) == 2
        assert bool(session.memory_rebuild_needed) is True
    finally:
        db.close()


def test_prepare_node_specs_insert_session_memory_before_query_decompose() -> None:
    """会话短期记忆节点应位于答案策略路由后、查询拆解前。"""

    graph = object.__new__(RetrievalGraph)

    keys = [key for key, _ in graph._prepare_node_specs()]  # type: ignore[attr-defined]

    assert keys.index("answer_policy_router") < keys.index("session_memory")
    assert keys.index("session_memory") < keys.index("query_decompose")


def test_chat_memory_pending_ttl_expires_after_two_follow_up_turns() -> None:
    """待验证上下文应在两个后续用户回合后自然过期。"""

    db = make_session()
    try:
        session = ChatSession(user_id=1, title="TTL 测试", chat_type="base_chat", mode="auto")
        db.add(session)
        db.flush()

        memory_service = ChatMemoryService(db)
        for index, question in enumerate(("黑粉进料有异常吗", "那如果继续偏大呢", "如果还是不行呢"), start=1):
            user_message = ChatMessage(session_id=session.id, user_id=1, role="user", content=question)
            assistant_message = ChatMessage(session_id=session.id, user_id=None, role="assistant", content="证据不足，请补充资料。")
            db.add_all([user_message, assistant_message])
            db.flush()

            outcome = TurnOutcome(
                session_id=session.id,
                user_message_id=user_message.id,
                assistant_message_id=assistant_message.id,
                user_message=question,
                answer="证据不足，请补充资料。",
                answer_type="refusal",
                evidence_status="EMPTY",
                chat_type="base_chat",
                project_id=None,
                citations=[],
                evidences=[],
                trace_steps=[],
                raw={},
                turn_context=None,
            )
            memory_service.finalize_turn_memory(session, outcome)
            db.commit()

            snapshot = json.loads(str(session.memory_state_json or "{}"))
            if index == 1:
                assert snapshot["pending_contexts"][0]["pending_turn_ttl"] == 2
            if index == 2:
                assert snapshot["pending_contexts"][-1]["pending_turn_ttl"] == 1
            if index == 3:
                ttl_values = [item["pending_turn_ttl"] for item in snapshot["pending_contexts"]]
                assert 0 not in ttl_values
                assert len(ttl_values) <= 2
    finally:
        db.close()


def test_chat_memory_topic_shift_replaces_old_topic_context() -> None:
    """明显切题后应清理旧 topic context，只保留新主题。"""

    db = make_session()
    try:
        session = ChatSession(user_id=1, title="切题测试", chat_type="project_chat", mode="auto", project_id=7)
        db.add(session)
        db.flush()

        memory_service = ChatMemoryService(db)
        first_user = ChatMessage(session_id=session.id, user_id=1, role="user", content="黑粉进料流程是什么")
        first_assistant = ChatMessage(session_id=session.id, user_id=None, role="assistant", content="先给料，再浸出，最后过滤。")
        db.add_all([first_user, first_assistant])
        db.flush()
        memory_service.finalize_turn_memory(
            session,
            _build_turn_outcome(
                session_id=session.id,
                user_message_id=first_user.id,
                assistant_message_id=first_assistant.id,
                question=first_user.content,
                answer=first_assistant.content,
                project_id=7,
            ),
        )
        db.commit()

        second_user = ChatMessage(session_id=session.id, user_id=1, role="user", content="萃取段温度参数是多少")
        second_assistant = ChatMessage(session_id=session.id, user_id=None, role="assistant", content="萃取段控制温度为 65℃。")
        db.add_all([second_user, second_assistant])
        db.flush()
        memory_service.finalize_turn_memory(
            session,
            _build_turn_outcome(
                session_id=session.id,
                user_message_id=second_user.id,
                assistant_message_id=second_assistant.id,
                question=second_user.content,
                answer=second_assistant.content,
                project_id=7,
            ),
        )
        db.commit()

        snapshot = json.loads(str(session.memory_state_json or "{}"))
        assert snapshot["topic_context"]["topic_label"] == "萃取段温度参数是多少"
        assert snapshot["confirmed_contexts"][0]["summary"] == "萃取段温度参数是多少"
        assert all(item["summary"] != "黑粉进料流程是什么" for item in snapshot["confirmed_contexts"])
    finally:
        db.close()


def test_chat_session_memory_field_compiles_to_longtext_for_mysql() -> None:
    """短期记忆快照在 MySQL 下必须使用 LONGTEXT，避免结构化 JSON 超过 TEXT 限制。"""

    chat_sql = str(CreateTable(ChatSession.__table__).compile(dialect=mysql.dialect()))

    assert "memory_state_json LONGTEXT" in chat_sql
