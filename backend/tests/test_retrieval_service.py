import sys
from pathlib import Path
from types import SimpleNamespace

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.schemas import Evidence
from app.services.retrieval_service import RetrievalService


def _evidence(retriever: str = "page_index") -> Evidence:
    return Evidence(
        score=0.95,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=1,
        chunk_id=1,
        drawing_no="D-1",
        file_name="unit.md",
        page_number=1,
        content="测试证据",
        retriever=retriever,
        metadata={"security_level": "public"},
    )


class _FakePlan:
    selected_retrievers = ["page_index"]
    fallback_retrievers = ["keyword"]
    fallback_ladder = [["page_index"], ["keyword"]]
    skip_reasons = {"keyword": "planner_fallback_only"}
    query_features = {"resolved_task_type": "document_location"}

    def to_dict(self) -> dict:
        return {
            "selected_retrievers": self.selected_retrievers,
            "fallback_retrievers": self.fallback_retrievers,
            "fallback_ladder": self.fallback_ladder,
            "skip_reasons": self.skip_reasons,
            "query_features": self.query_features,
            "reason": "fake plan",
            "confidence": 1.0,
            "qwen_used": False,
            "strategy": "rules",
            "rule_id": "fake",
        }


def test_retrieval_service_planner_mode_uses_single_planner_authority(monkeypatch) -> None:
    calls: dict[str, object] = {"planner_calls": 0}

    class FakeRouter:
        def __init__(self, db) -> None:
            self.db = db

        def search(self, *args, **kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("planner mode should not call RetrievalRouter.search")

        def prepare_scope(self, mode, project_id, chat_type, user):  # noqa: ANN001
            calls["prepare_scope"] = (mode, project_id, chat_type, getattr(user, "id", None))
            return "project_chat"

        def available_retrievers(self) -> list[str]:
            calls["available_retrievers"] = True
            return ["page_index", "keyword"]

        def execute_planned(self, **kwargs):
            calls["execute_planned"] = kwargs
            return {
                "mode": kwargs["mode"],
                "query_scope": "project_chat",
                "planned_retrievers": kwargs["retriever_names"],
                "used_retrievers": ["page_index"],
                "executed_retrievers": ["page_index"],
                "skipped_retrievers": ["keyword"],
                "skip_reasons": dict(kwargs["skip_reasons"]),
                "fallback_ladder": kwargs["fallback_ladder"],
                "fallback_used": [],
                "fallback_trigger_reason": [],
                "evidences": [_evidence()],
                "retriever_hits": {"page_index": 1},
                "retriever_elapsed_ms": {"page_index": 5},
                "retriever_top_scores": {"page_index": 0.95},
                "retriever_errors": {},
                "retriever_timeouts": {"page_index": False},
            }

        def finalize_retrieval(self, **kwargs):
            calls["finalize_retrieval"] = kwargs
            return {
                "evidences": list(kwargs["evidences"]),
                "rerank_details": [{"backend": "fake"}],
                "pre_rerank_guard": {"accepted": 1, "rejected": []},
            }

    class FakeQwen:
        def __init__(self, db) -> None:
            self.db = db

        def detect_intent(self, query: str, chat_type: str, mode: str) -> str:
            calls["detect_intent"] = (query, chat_type, mode)
            return "project_qa"

        def decompose_query(self, query: str, intent: str) -> list[str]:
            calls["decompose_query"] = (query, intent)
            return [query]

    class FakePlannerService:
        def __init__(self, db) -> None:
            self.db = db

        def plan(self, **kwargs):
            calls["planner_calls"] = int(calls["planner_calls"]) + 1
            calls["plan_kwargs"] = kwargs
            return _FakePlan()

    monkeypatch.setattr("app.services.retrieval_service.RetrievalRouter", FakeRouter)
    monkeypatch.setattr("app.services.retrieval_service.QwenOrchestrationService", FakeQwen)
    monkeypatch.setattr("app.services.retrieval_service.RetrievalPlannerService", FakePlannerService)

    user = SimpleNamespace(id=7)
    result = RetrievalService(None).search(
        query="项目资料里的参数是多少",
        mode="project_chat",
        project_id=1,
        user=user,
        limit=3,
        chat_type="project_chat",
        execution_mode="planner",
    )

    assert calls["planner_calls"] == 1
    assert calls["detect_intent"] == ("项目资料里的参数是多少", "project_chat", "project_chat")
    assert calls["decompose_query"] == ("项目资料里的参数是多少", "project_qa")
    assert calls["execute_planned"]["retriever_names"] == ["page_index"]
    assert calls["plan_kwargs"]["available_retrievers"] == ["page_index", "keyword"]
    assert calls["finalize_retrieval"]["evidences"][0].retriever == "page_index"
    assert result["retrieval_plan"]["selected_retrievers"] == ["page_index"]
    assert result["used_retrievers"] == ["page_index"]
    assert result["citations"][0]["retriever"] == "page_index"


def test_retrieval_service_all_mode_bypasses_planner(monkeypatch) -> None:
    calls = {"search_all": 0}

    class FakeRouter:
        def __init__(self, db) -> None:
            self.db = db

        def search_all(self, query, mode, project_id, user, limit, chat_type):  # noqa: ANN001
            calls["search_all"] += 1
            return {
                "mode": mode,
                "query_scope": mode,
                "planned_retrievers": ["keyword"],
                "used_retrievers": ["keyword"],
                "executed_retrievers": ["keyword"],
                "skipped_retrievers": [],
                "skip_reasons": {},
                "fallback_ladder": [["keyword"]],
                "fallback_used": [],
                "fallback_trigger_reason": [],
                "evidences": [_evidence("keyword")],
                "retriever_hits": {"keyword": 1},
                "retriever_elapsed_ms": {"keyword": 1},
                "retriever_top_scores": {"keyword": 0.8},
                "retriever_errors": {},
                "retriever_timeouts": {"keyword": False},
                "rerank_details": [],
                "pre_rerank_guard": {"accepted": 1, "rejected": []},
                "retrieval_plan": {"strategy": "all"},
            }

    def fail_qwen(db):  # noqa: ANN001
        raise AssertionError("execution_mode=all should bypass planner orchestration")

    def fail_planner(db):  # noqa: ANN001
        raise AssertionError("execution_mode=all should bypass planner service")

    monkeypatch.setattr("app.services.retrieval_service.RetrievalRouter", FakeRouter)
    monkeypatch.setattr("app.services.retrieval_service.QwenOrchestrationService", fail_qwen)
    monkeypatch.setattr("app.services.retrieval_service.RetrievalPlannerService", fail_planner)

    result = RetrievalService(None).search(
        query="调试检索",
        mode="base_chat",
        project_id=None,
        user=SimpleNamespace(id=9),
        limit=2,
        chat_type="base_chat",
        execution_mode="all",
    )

    assert calls["search_all"] == 1
    assert result["citations"][0]["retriever"] == "keyword"
