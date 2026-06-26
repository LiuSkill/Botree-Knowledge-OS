from __future__ import annotations

from typing import Any, cast

from app.models.user import Role, User
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
