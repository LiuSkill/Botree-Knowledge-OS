"""敏感内容过滤上线前关键安全链路验收测试。"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_user, get_db
from app.langgraph.retrieval_graph import RetrievalGraph
from app.retrieval.schemas import Evidence
from main import app
from app.schemas.chat import ChatCompletionRequest
from app.services.chat_service import ChatService
from app.services.sensitive_content_service import (
    RoleSensitivePermissionService,
    SensitiveContentService,
)


def user_with_roles(*roles: tuple[int, str, bool]) -> SimpleNamespace:
    return SimpleNamespace(
        id=9,
        username="acceptance-user",
        roles=[SimpleNamespace(id=role_id, code=code, enabled=enabled, permissions=[]) for role_id, code, enabled in roles],
    )


def test_role_permissions_use_union_and_admin_can_view_every_enabled_type() -> None:
    service = object.__new__(RoleSensitivePermissionService)
    service.rule_service = SimpleNamespace(load=lambda: ({"price": object(), "cost": object()}, ()))
    service.repository = SimpleNamespace(allowed_types=lambda role_ids: {"price"} if role_ids == {1, 2} else set())

    assert service.allowed_types(user_with_roles((1, "sales", True), (2, "finance", True))) == {"price"}
    assert service.allowed_types(user_with_roles((3, "admin", True))) == {"price", "cost"}


def test_rule_or_permission_load_exception_blocks_instead_of_returning_original() -> None:
    service = SensitiveContentService(None)
    service.rule_service = SimpleNamespace(load=lambda: (_ for _ in ()).throw(RuntimeError("rule unavailable")))
    service.permission_service = SimpleNamespace(allowed_types=lambda _user: set())
    with pytest.raises(RuntimeError, match="rule unavailable"):
        service.filter_for_user("报价为 100 万元", user_with_roles((1, "sales", True)))

    service.rule_service = SimpleNamespace(load=lambda: ({"price": object()}, ()))
    service.permission_service = SimpleNamespace(
        allowed_types=lambda _user: (_ for _ in ()).throw(RuntimeError("permission unavailable"))
    )
    with pytest.raises(RuntimeError, match="permission unavailable"):
        service.filter_for_user("报价为 100 万元", user_with_roles((1, "sales", True)))


def test_final_answer_is_filtered_before_trace_and_log(caplog: pytest.LogCaptureFixture) -> None:
    graph = object.__new__(RetrievalGraph)
    graph.sensitive_content_service = SensitiveContentService(None)
    state = {
        "chat_type": "base_chat", "mode": "auto", "user": user_with_roles((1, "sales", True)),
        "answer_policy_action": "normal_answer", "evidences": [], "trace": [], "raw": {"run_id": "acceptance"},
    }
    caplog.set_level(logging.INFO)

    result = graph.finalize_answer(state, "最终报价为 1350 万元。")

    assert result["answer"] == "最终报价为 [报价信息已隐藏]。"
    assert result["final_answer_redacted"] is True
    assert "1350 万元" not in caplog.text
    assert "1350 万元" not in json.dumps(result["agent_trace"], ensure_ascii=False)


def test_evidence_log_summary_contains_no_content_preview() -> None:
    graph = object.__new__(RetrievalGraph)
    evidence = SimpleNamespace(
        retriever="vector", score=0.9, source_type="chunk", project_id=1, knowledge_base_id=2,
        document_id=3, drawing_no=None, page_number=4, chunk_id=5, assets=[], content="供应商报价 500 万元",
    )
    summary = graph._evidence_log_summary([evidence])
    assert summary[0]["content_length"] == len(evidence.content)
    assert evidence.content not in json.dumps(summary, ensure_ascii=False)


def test_table_evidence_is_safe_before_answer_generator_and_citation() -> None:
    graph = object.__new__(RetrievalGraph)
    graph.sensitive_content_service = SensitiveContentService(None)
    evidence = Evidence(
        score=0.9, source_type="chunk", knowledge_base_id=1, project_id=2, document_id=3, chunk_id=4,
        drawing_no=None, file_name="quote.md", page_number=1,
        content="| 设备 | 供应商报价 | 成本 | 毛利率 |\n|---|---:|---:|---:|\n| A | 35 万元 | 20 万元 | 42% |",
        retriever="vector",
    )
    state = {"user": user_with_roles((1, "ordinary", True)), "redaction_types": [], "redaction_count": 0}

    safe_evidence = graph._sanitize_evidences(state, [evidence])[0]
    citation = ChatService._serialize_evidences(object.__new__(ChatService), [safe_evidence])[0]

    for raw_value in ("35 万元", "20 万元", "42%"):
        assert raw_value not in safe_evidence.content
        assert raw_value not in citation["content"]
    assert {"supplier_price", "cost", "gross_margin"}.issubset(state["redaction_types"])


def test_ordinary_user_cannot_access_sensitive_management_api() -> None:
    fake_db = SimpleNamespace(add=lambda _item: None, commit=lambda: None, rollback=lambda: None)

    def override_db():
        yield fake_db

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = lambda: user_with_roles((1, "ordinary", True))
    try:
        response = TestClient(app).get("/api/sensitive-content/types")
        assert response.status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_stream_buffers_raw_tokens_until_final_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeAnswerGenerator:
        last_model_route = {}

        def stream_generate(self, *_args, **_kwargs):
            yield "报价为 "
            yield "1350 万元"

    class FakeGraph:
        answer_generator = FakeAnswerGenerator()

        def __init__(self, _db):
            self.filter = SensitiveContentService(None)

        def prepare_stream(self, *_args, **_kwargs):
            yield "prepared", {"chat_type": "base_chat", "mode": "auto", "evidences": [], "trace": [],
                               "raw": {}, "user": user_with_roles((1, "ordinary", True))}

        def prepare_answer_context(self, _state): return []
        def next_trace_sequence(self, _state): return 1
        def answer_running_trace_delta(self, _state, _sequence): return {}
        def trace_delta_payload(self, _item): return {}

        def finalize_answer(self, state, answer, **_kwargs):
            filtered = self.filter.filter_for_user(answer, state["user"])
            return {"answer": filtered.safe_content, "agent_trace": [], "trace_steps": [], "raw": {},
                    "redacted": filtered.redacted, "redaction_types": list(filtered.redaction_types),
                    "redaction_count": filtered.redaction_count, "final_answer_redacted": filtered.redacted}

    monkeypatch.setattr("app.services.chat_service.RetrievalGraph", FakeGraph)
    service = object.__new__(ChatService)
    service.db = SimpleNamespace(rollback=lambda: None)
    service.repository = SimpleNamespace(add_message=lambda _message: None)
    service._ensure_chat_action_permission = lambda *_args: None
    service._validate_chat_request = lambda *_args: None
    service._get_or_create_session = lambda *_args: SimpleNamespace(id=7)
    service._resolve_general_confirmation_decision = lambda *_args: None
    service._progress_event_from_trace = lambda *_args: None
    service._build_visible_progress_events = lambda *_args, **_kwargs: []
    service._persist_agent_result = lambda _payload, _user, _session, result: result
    payload = ChatCompletionRequest(message="请给出报价")

    events = list(service.complete_stream(payload, user_with_roles((1, "ordinary", True))))
    delta_events = [event for event in events if "event: delta" in event]
    assert len(delta_events) == 1
    assert "1350 万元" not in "".join(delta_events)
    assert "[报价信息已隐藏]" in delta_events[0]


def test_application_sources_do_not_define_forbidden_raw_response_fields() -> None:
    root = Path(__file__).resolve().parents[1]
    forbidden = ("raw_" + "answer", "raw_" + "chunk_content", "raw_" + "snippet", "unmasked_" + "content")
    sources = list((root / "app").rglob("*.py")) + list((root.parent / "frontend" / "src").rglob("*.ts"))
    sources += list((root.parent / "frontend" / "src").rglob("*.vue"))
    for source in sources:
        text = source.read_text(encoding="utf-8")
        assert not any(field in text for field in forbidden), f"{source} 包含禁止的原始敏感字段"
