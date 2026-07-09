from __future__ import annotations

from typing import Any, cast

from app.models.user import Role, User
from app.retrieval.schemas import Evidence
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.router import RetrievalRouter
from app.services.qwen_orchestration_service import QwenOrchestrationService


def make_admin_user() -> User:
    user = User(id=1, username="admin", password_hash="x", real_name="Admin")
    user.roles = [Role(id=1, name="Admin", code="admin", enabled=True, security_level="confidential")]
    return user


def test_base_chat_only_allows_base_knowledge() -> None:
    retriever = KeywordRetriever(cast(Any, None))
    user = make_admin_user()

    assert retriever._scope_allowed("base", None, 1, "base_chat", None, user) is True
    assert retriever._scope_allowed("project", 10, 2, "base_chat", None, user) is False


def test_project_chat_only_allows_selected_project_knowledge() -> None:
    retriever = KeywordRetriever(cast(Any, None))
    user = make_admin_user()

    assert retriever._scope_allowed("project", 10, 2, "project_chat", 10, user) is True
    assert retriever._scope_allowed("project", 20, 3, "project_chat", 10, user) is False
    assert retriever._scope_allowed("base", None, 1, "project_chat", 10, user) is False


def test_project_with_industry_allows_project_and_authorized_base_only() -> None:
    retriever = KeywordRetriever(cast(Any, None))
    user = make_admin_user()

    assert retriever._scope_allowed("project", 10, 2, "project_with_industry", 10, user) is True
    assert retriever._scope_allowed("base", None, 1, "project_with_industry", 10, user) is True
    assert retriever._scope_allowed("project", 20, 3, "project_with_industry", 10, user) is False


def test_chat_type_forces_independent_retrieval_library() -> None:
    router = object.__new__(RetrievalRouter)

    assert router._effective_mode("hybrid", 10, "base_chat", knowledge_scope="project") == "base_chat"
    assert router._effective_mode("base_only", 10, "project_chat", knowledge_scope="industry") == "project_chat"
    assert (
        router._effective_mode("project_with_industry", 10, "project_chat", knowledge_scope="project_with_industry")
        == "project_chat"
    )


def test_project_intent_scope_does_not_append_base_library() -> None:
    service = QwenOrchestrationService(cast(Any, None))

    assert service._knowledge_scope_for_intent("project_qa") == "project"
    assert service._knowledge_scope_for_intent("exact_lookup") == "project"
    assert service._knowledge_scope_for_intent("industry_knowledge_qa") == "industry"


def test_structured_list_stage_quality_forces_fallback_on_generic_table_noise() -> None:
    router = object.__new__(RetrievalRouter)
    evidence = Evidence(
        score=1.24,
        source_type="project",
        knowledge_base_id=1,
        project_id=2,
        document_id=900,
        chunk_id=1001,
        drawing_no=None,
        file_name="PERFORMANCE TEST OF THE PUMP.pdf",
        page_number=3,
        content="| No. | Test Item | Result | Unit |\n| 1 | Flow rate | 12 | m3/h |",
        retriever="page_index",
        metadata={"document_name": "PERFORMANCE TEST OF THE PUMP.pdf"},
    )

    quality = router._assess_stage_quality("该项目的最终产品有哪些", [evidence])  # noqa: SLF001
    should_continue, reason = router._should_continue_fallback(  # noqa: SLF001
        quality,
        1,
        3,
        remaining_budget_ms=9000,
        min_remaining_budget_ms=1000,
    )

    assert quality["structured_anchor_support_count"] == 0
    assert quality["table_like_without_anchor_count"] == 1
    assert should_continue is True
    assert reason == "structured_anchor_support_count==0"


def test_structured_list_stage_quality_accepts_real_product_list_rows() -> None:
    router = object.__new__(RetrievalRouter)
    evidences = [
        Evidence(
            score=1.42,
            source_type="project",
            knowledge_base_id=1,
            project_id=2,
            document_id=308,
            chunk_id=51193,
            drawing_no=None,
            file_name="BCE2413-PS-40-007 Product List_Rev.1B.pdf",
            page_number=3,
            content="| No. | Product Name | Product Remarks |\n| 1 | Li2CO3 | / |",
            retriever="page_index",
            metadata={"document_name": "BCE2413-PS-40-007 Product List_Rev.1B.pdf"},
        ),
        Evidence(
            score=1.21,
            source_type="project",
            knowledge_base_id=1,
            project_id=2,
            document_id=308,
            chunk_id=51194,
            drawing_no=None,
            file_name="BCE2413-PS-40-007 Product List_Rev.1B.pdf",
            page_number=3,
            content="| 2 | Na2SO4 | / |",
            retriever="page_index",
            metadata={"document_name": "BCE2413-PS-40-007 Product List_Rev.1B.pdf"},
        ),
    ]

    quality = router._assess_stage_quality("该项目的最终产品有哪些", evidences)  # noqa: SLF001
    should_continue, reason = router._should_continue_fallback(  # noqa: SLF001
        quality,
        1,
        3,
        remaining_budget_ms=9000,
        min_remaining_budget_ms=1000,
    )

    assert quality["structured_anchor_support_count"] >= 1
    assert should_continue is False
    assert reason == "quality_enough"
