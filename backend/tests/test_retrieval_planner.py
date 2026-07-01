"""
Retrieval Planner Tests

负责：
1. 验证 Agentic Retrieval Planner 的规则映射
2. 验证 Qwen Planner 失败时的规则回退
3. 验证 Router 的 staged fallback 和 skip reason 行为
"""

from __future__ import annotations

import logging
import sys
import time
import concurrent.futures
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.router import RetrievalRouter  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402
from app.services.evidence_access_guard_service import EvidenceAccessGuardService  # noqa: E402
from app.services.retrieval_planner_service import RetrievalPlannerService  # noqa: E402

logger = logging.getLogger(__name__)


class FakeLLMService:
    """
    测试用 LLM 服务。

    职责：
    - 避免单元测试访问真实 Qwen 服务
    - 返回非法内容以验证 Planner 回退逻辑
    """

    def __init__(self, _: Any) -> None:
        self.db = None

    def chat(self, _: list[dict[str, str]], model_type: str = "llm") -> str:  # noqa: ARG002
        """
        返回非 JSON 内容，触发 Qwen Planner 回退。

        返回:
            非法 JSON 字符串
        """

        return "not json"

    def model_route(self, task: str, reason: str) -> dict[str, Any]:
        return {"task": task, "model_type": "planner", "source": "database", "reason": reason}


class FakeTablePlannerLLMService:
    """
    测试用 Qwen Planner。

    职责：
    - 模拟模型只选择 milvus/ripgrep 的情况
    - 验证规则层会为表格数值查询补齐 page_index
    """

    def __init__(self, _: Any) -> None:
        self.db = None

    def chat(self, _: list[dict[str, str]], model_type: str = "llm") -> str:  # noqa: ARG002
        """返回合法 Planner JSON。"""

        return '{"selected_retrievers": ["milvus", "ripgrep"], "reason": "model plan", "confidence": 0.9}'

    def model_route(self, task: str, reason: str) -> dict[str, Any]:
        return {"task": task, "model_type": "planner", "source": "database", "reason": reason}


class FakeNewPlannerLLMService:
    """模拟新版 Planner JSON，包含未知 retriever 用于验证过滤。"""

    def __init__(self, _: Any) -> None:
        self.db = None

    def chat(self, _: list[dict[str, str]], model_type: str = "llm") -> str:  # noqa: ARG002
        return (
            '{"selected_retrievers":["milvus","unknown","ripgrep"],'
            '"retriever_reasons":{"milvus":"semantic","unknown":"bad","ripgrep":"exact"},'
            '"priority":["unknown","ripgrep","milvus"],'
            '"query_rewrite":["A vs B"],"reason":"model plan","confidence":0.82}'
        )

    def model_route(self, task: str, reason: str) -> dict[str, Any]:
        return {"task": task, "model_type": "planner", "source": "database", "reason": reason}


class FakeRetriever:
    """
    测试用 Retriever。

    职责：
    - 记录是否被 Router 调用
    - 返回预设 Evidence 列表
    """

    def __init__(self, name: str, evidences: list[Evidence] | None = None, delay_seconds: float = 0.0) -> None:
        self.name = name
        self.evidences = evidences or []
        self.delay_seconds = delay_seconds
        self.calls = 0

    def search(self, query: str, mode: str, project_id: int | None, user: Any, limit: int = 5) -> list[Evidence]:
        """
        模拟 Retriever 的 search 接口。

        参数:
            query: 查询文本
            mode: 检索模式
            project_id: 项目ID
            user: 当前用户
            limit: 返回数量

        返回:
            预设 Evidence 列表
        """

        self.calls += 1
        if self.delay_seconds:
            time.sleep(self.delay_seconds)
        return self.evidences[:limit]


def make_evidence(retriever: str, score: float = 1.0, content: str | None = None) -> Evidence:
    """
    构造测试 Evidence。

    参数:
        retriever: 来源 Retriever
        score: 检索得分
        content: 证据文本

    返回:
        Router 可直接使用的 Evidence
    """

    return Evidence(
        score=score,
        source_type="project",
        knowledge_base_id=1,
        project_id=1,
        document_id=1,
        chunk_id=1,
        drawing_no="D-1",
        file_name="unit.md",
        page_number=1,
        content=content or "这是高质量业务证据内容",
        retriever=retriever,
        metadata={"security_level": "public"},
    )


def build_router(*retrievers: FakeRetriever) -> RetrievalRouter:
    """
    构造不依赖数据库的 Router 实例。

    参数:
        retrievers: 测试用 Retriever

    返回:
        注入 fake retriever 的 RetrievalRouter
    """

    router = object.__new__(RetrievalRouter)
    router.retrievers = list(retrievers)
    router.retriever_map = {retriever.name: retriever for retriever in retrievers}
    router.evidence_access_guard = EvidenceAccessGuardService(None)
    router._scope_text = lambda mode: mode  # type: ignore[method-assign]
    router.settings = SimpleNamespace(retrieval_retriever_timeout_ms=4500, ripgrep_timeout_ms=1500)
    router._retriever_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

    def prepare_scope(
        mode: str,
        project_id: int | None,
        chat_type: str | None,
        user: Any,
        knowledge_scope: str | None = None,
    ) -> str:
        return mode

    router._prepare_scope = prepare_scope  # type: ignore[method-assign]
    return router


def test_rule_planner_exact_lookup() -> None:
    """
    exact_lookup 必须优先选择 ripgrep 和 milvus。
    """

    plan = RetrievalPlannerService(None).plan(
        query="E-1001 的设计压力是多少",
        sub_queries=["E-1001"],
        intent="exact_lookup",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
    )
    assert plan.selected_retrievers == ["ripgrep", "milvus"]
    assert plan.fallback_retrievers == ["keyword"]
    assert plan.fallback_ladder == [["ripgrep", "milvus"], ["keyword"]]
    assert plan.qwen_used is False


def test_rule_planner_page_location_uses_page_index_and_ripgrep() -> None:
    """page_location 问题必须选择 page_index + ripgrep。"""

    plan = RetrievalPlannerService(None).plan(
        query="10-PS-0101-3002-003 在哪页、哪张图？",
        sub_queries=["10-PS-0101-3002-003"],
        intent="page_location",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={"query_type": "page_location", "need_page_location": True},
    )
    assert plan.selected_retrievers == ["page_index", "ripgrep"]
    assert plan.fallback_ladder == [["page_index", "ripgrep"], ["keyword"]]


def test_rule_planner_process_flow_uses_page_ripgrep_milvus_and_graph_when_needed() -> None:
    """流程问题优先 page_index + ripgrep + milvus，必要时加入 graphrag。"""

    plan = RetrievalPlannerService(None).plan(
        query="Raw Material & Chemical Feeding 全流程和上下游设备连接是什么？",
        sub_queries=["Raw Material & Chemical Feeding 全流程"],
        intent="project_qa",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={
            "query_type": "process_flow",
            "need_graph_reasoning": True,
            "keywords": ["Raw Material & Chemical Feeding"],
        },
    )
    assert plan.selected_retrievers == ["page_index", "ripgrep", "milvus", "graphrag"]
    assert plan.fallback_ladder == [["page_index", "ripgrep", "milvus", "graphrag"], ["keyword"]]


def test_rule_planner_graph_reasoning_uses_graph_milvus_ripgrep() -> None:
    """graph_reasoning 问题优先 graphrag + milvus + ripgrep。"""

    plan = RetrievalPlannerService(None).plan(
        query="A 和 B 的上下游关系是什么？",
        sub_queries=["A 和 B 的上下游关系"],
        intent="graph_reasoning",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={"query_type": "graph_reasoning", "need_graph_reasoning": True},
    )
    assert plan.selected_retrievers == ["graphrag", "milvus", "ripgrep"]


def test_rule_planner_filters_disabled_milvus() -> None:
    """
    Milvus 未启用时不得报错，且要回退到可用主检索器。
    """

    plan = RetrievalPlannerService(None).plan(
        query="介绍项目总体情况",
        sub_queries=["介绍项目总体情况"],
        intent="project_qa",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["page_index", "ripgrep", "keyword", "graphrag"],
    )
    assert plan.selected_retrievers == ["page_index"]
    assert plan.fallback_ladder[0] == ["page_index"]


def test_qwen_invalid_output_falls_back_to_rules() -> None:
    """
    Qwen Planner 输出非法 JSON 时必须回退规则计划。
    """

    with patch("app.services.retrieval_planner_service.LLMService", FakeLLMService):
        plan = RetrievalPlannerService(object()).plan(
            query="A 和 B 有什么关系",
            sub_queries=["A 和 B 有什么关系"],
            intent="graph_reasoning",
            chat_type="project_chat",
            mode="project_chat",
            project_id=1,
            available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        )
    assert plan.selected_retrievers == ["graphrag", "milvus", "ripgrep"]
    assert plan.qwen_used is True
    assert plan.strategy == "hybrid_fallback"


def test_knowledge_qa_natural_language_prefers_milvus_only() -> None:
    """
    base_chat + knowledge_qa 的自然语言问题默认只选 milvus。
    """

    plan = RetrievalPlannerService(None).plan(
        query="石墨干燥包装步骤是什么",
        sub_queries=["石墨干燥包装步骤是什么"],
        intent="knowledge_qa",
        chat_type="base_chat",
        mode="base_chat",
        project_id=None,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
    )
    assert plan.selected_retrievers == ["milvus"]
    assert plan.fallback_ladder == [["milvus"], ["keyword"]]
    assert "page_index" in plan.skipped_retrievers


def test_industry_knowledge_scope_uses_base_retrievers_only() -> None:
    """行业基础知识问答只规划行业基础知识库检索器。"""

    plan = RetrievalPlannerService(None).plan(
        query="酸浸原理是什么",
        sub_queries=["酸浸原理"],
        intent="industry_knowledge_qa",
        chat_type="base_chat",
        mode="base_chat",
        project_id=None,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={
            "query_type": "industry_knowledge_qa",
            "knowledge_scope": "industry",
            "is_industry_domain": True,
            "industry_domains": ["hydrometallurgy"],
        },
    )

    assert plan.selected_retrievers == ["milvus", "keyword"]
    assert plan.fallback_retrievers == []
    assert plan.fallback_ladder == [["milvus", "keyword"]]
    assert plan.query_features["knowledge_scope"] == "industry"
    assert plan.metadata["knowledge_scope"] == "industry"
    assert plan.strategy == "rules_fast_path"
    assert plan.metadata["model_route"]["source"] == "rules_fast_path"
    assert plan.metadata["model_route"]["qwen_used"] is False


def test_industry_comparison_scope_still_uses_base_retrievers_only() -> None:
    """行业对比题也不能因为 comparison 画像选入项目型检索器。"""

    plan = RetrievalPlannerService(None).plan(
        query="压滤机和过滤器有什么区别",
        sub_queries=["压滤机", "过滤器"],
        intent="industry_knowledge_qa",
        chat_type="base_chat",
        mode="base_chat",
        project_id=None,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={
            "query_type": "comparison",
            "knowledge_scope": "industry",
            "is_industry_domain": True,
            "industry_domains": ["equipment"],
        },
    )

    assert plan.selected_retrievers == ["milvus", "keyword"]
    assert plan.fallback_ladder == [["milvus", "keyword"]]
    assert plan.qwen_used is False
    assert plan.strategy == "rules_fast_path"
    assert "graphrag" in plan.skipped_retrievers
    assert "page_index" in plan.skipped_retrievers
    assert "ripgrep" in plan.skipped_retrievers


def test_base_definition_summary_how_to_use_rules_fast_path() -> None:
    """自然语言基础知识问答不应调用 Qwen Planner。"""

    for query_type in ("definition", "summary", "how_to"):
        plan = RetrievalPlannerService(None).plan(
            query="压滤机是什么",
            sub_queries=["压滤机是什么"],
            intent="knowledge_qa",
            chat_type="base_chat",
            mode="base_chat",
            project_id=None,
            available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
            query_profile={
                "query_type": query_type,
                "knowledge_scope": "industry",
                "answer_shape": "direct_answer",
            },
        )

        assert plan.selected_retrievers == ["milvus", "keyword"]
        assert plan.qwen_used is False
        assert plan.strategy == "rules_fast_path"
        assert "ripgrep" in plan.skipped_retrievers


def test_project_overview_uses_rules_fast_path_without_page_index_or_qwen() -> None:
    plan = RetrievalPlannerService(object()).plan(
        query="Introduce 2 x 2000 TPA Battery Black Mass Recycling Project",
        sub_queries=["Introduce 2 x 2000 TPA Battery Black Mass Recycling Project"],
        intent="project_overview",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["project_metadata", "page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={
            "query_type": "project_overview",
            "answer_shape": "project_summary",
            "knowledge_scope": "project",
            "need_page_location": False,
            "need_exact_term": False,
            "need_graph_reasoning": False,
            "need_visual_asset": False,
            "has_project_name": True,
        },
    )

    assert plan.selected_retrievers == ["project_metadata", "milvus", "keyword"]
    assert plan.fallback_ladder == [["project_metadata", "milvus", "keyword"]]
    assert plan.skipped_retrievers == ["page_index", "ripgrep", "graphrag"]
    assert plan.qwen_used is False
    assert plan.strategy == "rules_fast_path"
    assert plan.metadata["model_route"]["source"] == "rules_fast_path"


def test_policy_matrix_project_overview_uses_metadata_milvus_keyword_only() -> None:
    started_at = time.perf_counter()
    plan = RetrievalPlannerService(object()).plan(
        query="2 x 2000 TPA Battery Black Mass Recycling Project项目介绍",
        sub_queries=["2 x 2000 TPA Battery Black Mass Recycling Project项目介绍"],
        intent="project_overview",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["project_metadata", "page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={
            "query_type": "project_overview",
            "answer_shape": "project_summary",
            "knowledge_scope": "project",
        },
        policy_resolution={
            "resolved_task_type": "project_overview",
            "answer_policy": "STRICT_KB",
            "knowledge_scope": "project",
        },
        question_understanding={
            "retrieval_needs": {"semantic_retrieval": True, "keyword_retrieval": True},
            "query_rewrites": ["2 x 2000 TPA Battery Black Mass Recycling Project项目介绍"],
        },
    )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.5
    assert plan.selected_retrievers == ["project_metadata", "milvus", "keyword"]
    assert plan.fallback_ladder == [["project_metadata", "milvus", "keyword"]]
    assert plan.skipped_retrievers == ["page_index", "ripgrep", "graphrag"]
    assert plan.qwen_used is False
    assert plan.strategy == "policy_matrix"
    assert plan.to_dict()["resolved_task_type"] == "project_overview"
    assert plan.to_dict()["query_rewrites"] == ["2 x 2000 TPA Battery Black Mass Recycling Project项目介绍"]


def test_policy_matrix_process_flow_keeps_page_index_without_page_hint() -> None:
    plan = RetrievalPlannerService(object()).plan(
        query="本项目的黑粉进料流程介绍",
        sub_queries=["本项目的黑粉进料流程介绍"],
        intent="project_overview",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["project_metadata", "page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={
            "query_type": "project_overview",
            "answer_shape": "project_summary",
            "knowledge_scope": "project",
        },
        policy_resolution={
            "resolved_task_type": "process_flow",
            "answer_policy": "STRICT_KB",
            "knowledge_scope": "project",
        },
        question_understanding={
            "retrieval_needs": {
                "semantic_retrieval": True,
                "keyword_retrieval": True,
                "page_level_retrieval": False,
                "graph_retrieval": True,
                "exact_text_search": False,
                "visual_evidence": False,
            },
            "query_rewrites": [
                "本项目的黑粉进料流程介绍",
                "Black Mass Feeding",
                "Raw Material Feeding",
            ],
        },
    )

    assert plan.selected_retrievers == ["milvus", "keyword", "page_index"]
    assert "page_index" not in plan.skipped_retrievers
    assert "ripgrep" in plan.skipped_retrievers
    assert plan.query_features["resolved_task_type"] == "process_flow"
    assert plan.query_features["retrieval_needs"]["exact_text_search"] is False
    assert "Black Mass Feeding" in plan.to_dict()["query_rewrites"]


def test_policy_matrix_document_location_uses_page_index_and_ripgrep() -> None:
    plan = RetrievalPlannerService(object()).plan(
        query="黑粉进料流程在哪张图纸第几页",
        sub_queries=["黑粉进料流程在哪张图纸第几页"],
        intent="project_qa",
        chat_type="project_chat",
        mode="project_chat",
        project_id=1,
        available_retrievers=["project_metadata", "page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        query_profile={
            "query_type": "page_location",
            "answer_shape": "source_location",
            "knowledge_scope": "project",
            "need_page_location": True,
        },
        policy_resolution={
            "resolved_task_type": "document_location",
            "answer_policy": "STRICT_KB",
            "knowledge_scope": "project",
        },
        question_understanding={
            "retrieval_needs": {
                "semantic_retrieval": True,
                "keyword_retrieval": True,
                "page_level_retrieval": True,
                "graph_retrieval": False,
                "exact_text_search": True,
                "visual_evidence": True,
            },
            "query_rewrites": ["黑粉进料流程在哪张图纸第几页"],
        },
    )

    assert plan.selected_retrievers == ["keyword", "page_index", "ripgrep"]
    assert "page_index" in plan.selected_retrievers
    assert "ripgrep" in plan.selected_retrievers
    assert plan.to_dict()["retrieval_needs"]["exact_text_search"] is True


def test_rule_planner_table_value_lookup_uses_page_index() -> None:
    """
    元素 Min/Max 等表格数值查询必须执行 page_index。
    """

    plan = RetrievalPlannerService(None).plan(
        query="Co的最大值和最小值是多少",
        sub_queries=["Co的最大值和最小值是多少"],
        intent="knowledge_qa",
        chat_type="base_chat",
        mode="base_chat",
        project_id=None,
        available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
    )
    assert plan.qwen_used is False
    assert plan.query_features["has_table_value_lookup"] is True
    assert plan.selected_retrievers == ["page_index", "milvus", "ripgrep"]
    assert plan.fallback_ladder == [["page_index", "milvus"], ["ripgrep"], ["keyword"]]
    assert "page_index" not in plan.skipped_retrievers


def test_qwen_table_value_lookup_keeps_required_page_index() -> None:
    """
    即使 Qwen 没选择 page_index，表格数值查询也必须补齐页级索引。
    """

    with patch("app.services.retrieval_planner_service.LLMService", FakeTablePlannerLLMService):
        plan = RetrievalPlannerService(object()).plan(
            query="2 x 2000 TPA Battery Black Mass Recycling Project项目中 Co的最大值和最小值",
            sub_queries=["Co的最大值和最小值"],
            intent="knowledge_qa",
            chat_type="base_chat",
            mode="base_chat",
            project_id=None,
            available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag"],
        )
    assert plan.qwen_used is True
    assert plan.selected_retrievers[:3] == ["page_index", "milvus", "ripgrep"]
    assert plan.fallback_ladder[0] == ["page_index", "milvus", "ripgrep"]
    assert "page_index" not in plan.skipped_retrievers


def test_qwen_new_payload_filters_unknown_retriever_and_keeps_new_fields() -> None:
    """新版 Planner JSON 需要过滤未知 retriever，并保留新字段。"""

    with patch("app.services.retrieval_planner_service.LLMService", FakeNewPlannerLLMService):
        plan = RetrievalPlannerService(object()).plan(
            query="请对比 10-AB-123 中 A 和 B 的方案差异",
            sub_queries=["A", "B"],
            intent="project_qa",
            chat_type="project_chat",
            mode="project_chat",
            project_id=1,
            available_retrievers=["page_index", "milvus", "ripgrep", "keyword", "graphrag", "unknown"],
            query_profile={"query_type": "comparison", "answer_shape": "comparison_table"},
        )

    plan_dict = plan.to_dict()
    assert "unknown" not in plan.selected_retrievers
    assert "unknown" not in plan_dict["priority"]
    assert plan_dict["retriever_reasons"] == {"milvus": "semantic", "ripgrep": "exact"}
    assert plan_dict["query_rewrite"] == ["A vs B"]


def test_router_executes_only_planned_retrievers_when_quality_is_enough() -> None:
    """
    规划命中且质量足够时，不应继续执行 keyword fallback。
    """

    page_index = FakeRetriever(
        "page_index",
        [
            make_evidence("page_index", score=0.96, content="第一条高质量证据"),
            make_evidence("page_index", score=0.93, content="第二条高质量证据"),
        ],
    )
    keyword = FakeRetriever("keyword", [make_evidence("keyword")])
    router = build_router(page_index, keyword)
    result = router.execute_planned(
        query="E-1001",
        mode="project_chat",
        project_id=1,
        user=None,
        retriever_names=["page_index"],
        fallback_retrievers=["keyword"],
        fallback_ladder=[["page_index"], ["keyword"]],
    )
    assert result["used_retrievers"] == ["page_index"]
    assert result["fallback_used"] == []
    assert page_index.calls == 1
    assert keyword.calls == 0


def test_router_keyword_fallback_when_planned_empty() -> None:
    """
    规划检索器无结果时，必须按阶段触发 keyword fallback。
    """

    page_index = FakeRetriever("page_index", [])
    keyword = FakeRetriever("keyword", [make_evidence("keyword", score=0.9)])
    router = build_router(page_index, keyword)
    result = router.execute_planned(
        query="E-1001",
        mode="project_chat",
        project_id=1,
        user=None,
        retriever_names=["page_index"],
        fallback_retrievers=["keyword"],
        fallback_ladder=[["page_index"], ["keyword"]],
    )
    assert result["used_retrievers"] == ["page_index", "keyword"]
    assert result["fallback_used"] == ["keyword"]
    assert result["fallback_trigger_reason"][0]["reason"] == "hits==0"
    assert page_index.calls == 1
    assert keyword.calls == 1


def test_router_low_quality_milvus_triggers_keyword_fallback() -> None:
    """
    低质量 Milvus 结果必须触发下一层 keyword fallback。
    """

    milvus = FakeRetriever("milvus", [make_evidence("milvus", score=0.41, content="泛化程度较高的单条证据")])
    keyword = FakeRetriever("keyword", [make_evidence("keyword", score=0.9, content="精确补救证据")])
    router = build_router(milvus, keyword)
    result = router.execute_planned(
        query="石墨干燥包装步骤是什么",
        mode="base_chat",
        project_id=None,
        user=None,
        retriever_names=["milvus"],
        fallback_retrievers=["keyword"],
        fallback_ladder=[["milvus"], ["keyword"]],
    )
    assert result["used_retrievers"] == ["milvus", "keyword"]
    assert result["fallback_used"] == ["keyword"]
    assert result["fallback_trigger_reason"][0]["reason"].startswith("top_raw_score<")
    assert milvus.calls == 1
    assert keyword.calls == 1


def test_router_executes_same_stage_retrievers_in_parallel() -> None:
    """同一阶段的检索器应并行执行，避免 milvus/keyword 串行累加耗时。"""

    milvus = FakeRetriever("milvus", [make_evidence("milvus", score=0.95)], delay_seconds=0.2)
    keyword = FakeRetriever("keyword", [make_evidence("keyword", score=0.94)], delay_seconds=0.2)
    router = build_router(milvus, keyword)
    started_at = time.perf_counter()
    result = router.execute_planned(
        query="压滤机和过滤器有什么区别",
        mode="base_chat",
        project_id=None,
        user=None,
        retriever_names=["milvus", "keyword"],
        fallback_ladder=[["milvus", "keyword"]],
    )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.35
    assert result["used_retrievers"] == ["milvus", "keyword"]
    assert result["retriever_hits"] == {"milvus": 1, "keyword": 1}
    assert result["retriever_timeouts"] == {"milvus": False, "keyword": False}


def test_router_does_not_override_planner_selected_retrievers() -> None:
    """Router 只执行 Planner 已选检索器，不再运行时二次跳过。"""

    ripgrep = FakeRetriever("ripgrep", [make_evidence("ripgrep")])
    keyword = FakeRetriever("keyword", [make_evidence("keyword", score=0.9)])
    router = build_router(ripgrep, keyword)
    result = router.execute_planned(
        query="压滤机和过滤器有什么区别",
        mode="base_chat",
        project_id=None,
        user=None,
        retriever_names=["ripgrep", "keyword"],
        fallback_ladder=[["ripgrep", "keyword"]],
        query_features={"query_profile": {"query_type": "comparison", "answer_shape": "comparison_table"}},
    )

    assert ripgrep.calls == 1
    assert keyword.calls == 1
    assert result["used_retrievers"] == ["ripgrep", "keyword"]
    assert "ripgrep" not in result["skip_reasons"]


def test_router_process_flow_does_not_skip_page_index_without_page_hint() -> None:
    """process_flow 即使没有页码信号，也应允许 page_index 执行并受 timeout 控制。"""

    page_index = FakeRetriever("page_index", [make_evidence("page_index")])
    router = build_router(page_index)
    result = router.execute_planned(
        query="本项目的黑粉进料流程介绍",
        mode="project_chat",
        project_id=1,
        user=None,
        retriever_names=["page_index"],
        fallback_ladder=[["page_index"]],
        query_features={
            "resolved_task_type": "process_flow",
            "retrieval_needs": {"exact_text_search": False, "visual_evidence": False},
            "query_profile": {"query_type": "project_overview"},
        },
        intent="process_flow",
    )

    assert page_index.calls == 1
    assert result["used_retrievers"] == ["page_index"]
    assert result["retriever_timeouts"] == {"page_index": False}


def test_router_timeout_returns_without_waiting_for_blocking_retriever() -> None:
    page_index = FakeRetriever("page_index", [make_evidence("page_index")], delay_seconds=0.4)
    router = build_router(page_index)
    router.settings.retrieval_retriever_timeout_ms = 50

    started_at = time.perf_counter()
    result = router.execute_planned(
        query="第几页写了项目介绍",
        mode="project_chat",
        project_id=1,
        user=None,
        retriever_names=["page_index"],
        fallback_ladder=[["page_index"]],
        query_features={"has_page_hint": True, "query_profile": {"need_page_location": True}},
    )
    elapsed = time.perf_counter() - started_at

    assert elapsed < 0.2
    assert result["retriever_timeouts"] == {"page_index": True}
    assert result["retriever_hits"] == {"page_index": 0}


def test_router_ripgrep_timeout_envelope_exceeds_rg_subprocess_timeout() -> None:
    ripgrep = FakeRetriever("ripgrep", [make_evidence("ripgrep")], delay_seconds=0.1)
    router = build_router(ripgrep)
    router.settings.ripgrep_timeout_ms = 50
    router.settings.retrieval_retriever_timeout_ms = 500

    result = router.execute_planned(
        query="10-PS-0101-3002-003",
        mode="project_chat",
        project_id=1,
        user=None,
        retriever_names=["ripgrep"],
        fallback_ladder=[["ripgrep"]],
        query_features={"has_exact_token": True},
    )

    assert result["retriever_timeouts"] == {"ripgrep": False}
    assert result["retriever_hits"] == {"ripgrep": 1}


def main() -> None:
    """
    执行轻量单元测试。
    """

    test_rule_planner_exact_lookup()
    test_rule_planner_page_location_uses_page_index_and_ripgrep()
    test_rule_planner_process_flow_uses_page_ripgrep_milvus_and_graph_when_needed()
    test_rule_planner_graph_reasoning_uses_graph_milvus_ripgrep()
    test_rule_planner_filters_disabled_milvus()
    test_qwen_invalid_output_falls_back_to_rules()
    test_knowledge_qa_natural_language_prefers_milvus_only()
    test_industry_knowledge_scope_uses_base_retrievers_only()
    test_industry_comparison_scope_still_uses_base_retrievers_only()
    test_policy_matrix_project_overview_uses_metadata_milvus_keyword_only()
    test_policy_matrix_process_flow_keeps_page_index_without_page_hint()
    test_policy_matrix_document_location_uses_page_index_and_ripgrep()
    test_rule_planner_table_value_lookup_uses_page_index()
    test_qwen_table_value_lookup_keeps_required_page_index()
    test_qwen_new_payload_filters_unknown_retriever_and_keeps_new_fields()
    test_router_executes_only_planned_retrievers_when_quality_is_enough()
    test_router_keyword_fallback_when_planned_empty()
    test_router_low_quality_milvus_triggers_keyword_fallback()
    test_router_executes_same_stage_retrievers_in_parallel()
    test_router_does_not_override_planner_selected_retrievers()
    test_router_process_flow_does_not_skip_page_index_without_page_hint()
    test_router_timeout_returns_without_waiting_for_blocking_retriever()
    test_router_ripgrep_timeout_envelope_exceeds_rg_subprocess_timeout()
    logger.info("Retrieval Planner 单元测试通过")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    main()
