"""
System QA Audit Tests

职责：
1. 验证问答审计明细的筛选与分页
2. 验证会话审计聚合字段
3. 防止 trace 缺失时问题文本回退失效
"""

from __future__ import annotations

from datetime import datetime
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.exceptions import AppException  # noqa: E402
from app.models import Base, ChatCitation, ChatMessage, ChatSession, Project, RetrievalTrace, User  # noqa: E402
from app.services.system_service import SystemService  # noqa: E402


def make_session() -> Session:
    """创建独立内存数据库会话。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def seed_audit_fixture(db: Session) -> dict[str, Any]:
    """写入多用户、多项目、多反馈状态的问答审计数据。"""

    user_a = User(username="alice", password_hash="x", real_name="Alice")
    user_b = User(username="bob", password_hash="x", real_name="Bob")
    project_a = Project(name="回收项目A", code="P-A", status="active", progress=20)
    project_b = Project(name="回收项目B", code="P-B", status="active", progress=10)
    db.add_all([user_a, user_b, project_a, project_b])
    db.flush()

    session_a = ChatSession(
        user_id=user_a.id,
        title="项目A会话",
        chat_type="project_chat",
        mode="auto",
        project_id=project_a.id,
        created_at=datetime(2026, 1, 1, 10, 0, 0),
    )
    session_b = ChatSession(
        user_id=user_b.id,
        title="基础会话",
        chat_type="base_chat",
        mode="auto",
        created_at=datetime(2026, 1, 1, 11, 0, 0),
    )
    empty_session = ChatSession(
        user_id=user_a.id,
        title="项目B空会话",
        chat_type="project_chat",
        mode="auto",
        project_id=project_b.id,
        created_at=datetime(2026, 1, 1, 12, 0, 0),
    )
    db.add_all([session_a, session_b, empty_session])
    db.flush()

    question_a = ChatMessage(
        session_id=session_a.id,
        user_id=user_a.id,
        role="user",
        content="项目A怎么处理镍钴分离？",
        created_at=datetime(2026, 1, 1, 10, 1, 0),
    )
    answer_a = ChatMessage(
        session_id=session_a.id,
        role="assistant",
        content="项目A回答",
        feedback_status="like",
        created_at=datetime(2026, 1, 1, 10, 2, 0),
    )
    question_a2 = ChatMessage(
        session_id=session_a.id,
        user_id=user_a.id,
        role="user",
        content="项目A追问引用来源？",
        created_at=datetime(2026, 1, 1, 10, 3, 0),
    )
    answer_a2 = ChatMessage(
        session_id=session_a.id,
        role="assistant",
        content="项目A追问回答",
        created_at=datetime(2026, 1, 1, 10, 4, 0),
    )
    question_b = ChatMessage(
        session_id=session_b.id,
        user_id=user_b.id,
        role="user",
        content="基础知识问题",
        created_at=datetime(2026, 1, 1, 11, 1, 0),
    )
    answer_b = ChatMessage(
        session_id=session_b.id,
        role="assistant",
        content="基础知识回答",
        feedback_status="dislike",
        created_at=datetime(2026, 1, 1, 11, 2, 0),
    )
    db.add_all([question_a, answer_a, question_a2, answer_a2, question_b, answer_b])
    db.flush()

    db.add_all(
        [
            ChatCitation(
                message_id=answer_a.id,
                source_type="project",
                knowledge_base_id=1,
                project_id=project_a.id,
                document_id=1,
                chunk_id=1,
                file_name="source-a.pdf",
                content="citation-a-1",
                assets_json=(
                    '[{"asset_id": 101, "asset_type": "page_preview", "url": "/assets/101", '
                    '"mime_type": "image/png", "file_name": "page-1.png", "file_size": 128}]'
                ),
            ),
            ChatCitation(
                message_id=answer_a.id,
                source_type="project",
                knowledge_base_id=1,
                project_id=project_a.id,
                document_id=2,
                chunk_id=2,
                file_name="source-b.pdf",
                content="citation-a-2",
            ),
            RetrievalTrace(
                user_id=user_a.id,
                session_id=session_a.id,
                message_id=answer_a.id,
                chat_type="project_chat",
                mode="auto",
                project_id=project_a.id,
                question="trace中的项目A问题",
                intent="project_qa",
                retriever_hits_json='{"milvus": 2, "keyword": 1}',
                elapsed_ms=180,
                created_at=datetime(2026, 1, 1, 10, 2, 1),
            ),
            RetrievalTrace(
                user_id=user_a.id,
                session_id=session_a.id,
                message_id=answer_a2.id,
                chat_type="project_chat",
                mode="auto",
                project_id=project_a.id,
                question="trace中的项目A追问",
                intent="project_qa",
                retriever_hits_json='{"keyword": 1}',
                elapsed_ms=90,
                created_at=datetime(2026, 1, 1, 10, 4, 1),
            ),
        ]
    )
    db.commit()
    return {
        "user_a": user_a,
        "user_b": user_b,
        "project_a": project_a,
        "project_b": project_b,
    }


def test_qa_audit_details_filter_feedback_and_paginate() -> None:
    """问答详情应支持反馈筛选并返回分页信息。"""

    db = make_session()
    try:
        fixture = seed_audit_fixture(db)

        result = SystemService(db).qa_audits(user_id=fixture["user_a"].id, project_id=fixture["project_a"].id, page=1, page_size=1)
        like_result = SystemService(db).qa_audits(feedback_status="like")
        none_result = SystemService(db).qa_audits(feedback_status="none")

        assert result["total"] == 2
        assert result["page"] == 1
        assert result["page_size"] == 1
        assert len(result["items"]) == 1
        assert result["items"][0]["question"] == "trace中的项目A追问"
        assert result["items"][0]["retrievers"] == ["keyword"]
        assert like_result["items"][0]["feedback_status"] == "like"
        assert like_result["items"][0]["citation_count"] == 2
        assert len(like_result["items"][0]["citations"]) == 2
        assert like_result["items"][0]["citations"][0]["file_name"] == "source-a.pdf"
        assert like_result["items"][0]["citations"][0]["assets"][0]["asset_id"] == 101
        assert none_result["total"] == 1
        assert none_result["items"][0]["feedback_status"] is None
    finally:
        db.close()


def test_qa_audit_details_fallback_to_previous_user_question() -> None:
    """缺少 retrieval_trace 时，问答详情应回退到同会话上一条用户消息。"""

    db = make_session()
    try:
        seed_audit_fixture(db)

        result = SystemService(db).qa_audits(feedback_status="dislike")

        assert result["total"] == 1
        assert result["items"][0]["question"] == "基础知识问题"
        assert result["items"][0]["feedback_status"] == "dislike"
    finally:
        db.close()


def test_qa_audit_sessions_aggregate_and_filter_time() -> None:
    """会话审计应按最近问答时间聚合，并支持时间筛选。"""

    db = make_session()
    try:
        fixture = seed_audit_fixture(db)

        result = SystemService(db).qa_audit_sessions(user_id=fixture["user_a"].id, project_id=fixture["project_a"].id)
        time_result = SystemService(db).qa_audit_sessions(
            user_id=fixture["user_a"].id,
            started_at=datetime(2026, 1, 1, 11, 30, 0),
        )

        assert result["total"] == 1
        session = result["items"][0]
        assert session["question_count"] == 2
        assert session["answer_count"] == 2
        assert session["citation_count"] == 2
        assert session["latest_question"] == "项目A追问引用来源？"
        assert session["latest_answer"] == "项目A追问回答"
        assert time_result["total"] == 1
        assert time_result["items"][0]["title"] == "项目B空会话"
    finally:
        db.close()


def test_qa_audit_rejects_invalid_feedback_filter() -> None:
    """反馈筛选只接受已定义枚举。"""

    db = make_session()
    try:
        seed_audit_fixture(db)

        with pytest.raises(AppException):
            SystemService(db).qa_audits(feedback_status="unknown")
    finally:
        db.close()
