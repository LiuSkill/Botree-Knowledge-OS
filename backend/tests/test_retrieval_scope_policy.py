from __future__ import annotations

from typing import Any, cast

from app.models.user import Role, User
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever


def make_admin_user() -> User:
    user = User(id=1, username="admin", password_hash="x", real_name="Admin")
    user.roles = [Role(id=1, name="Admin", code="admin", enabled=True)]
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
