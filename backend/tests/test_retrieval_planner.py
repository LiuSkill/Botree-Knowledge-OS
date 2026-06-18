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
from pathlib import Path
from typing import Any
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.retrieval.router import RetrievalRouter  # noqa: E402
from app.retrieval.schemas import Evidence  # noqa: E402
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

    def __init__(self, name: str, evidences: list[Evidence] | None = None) -> None:
        self.name = name
        self.evidences = evidences or []
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
    router._scope_text = lambda mode: mode  # type: ignore[method-assign]

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

    assert plan.selected_retrievers == ["milvus"]
    assert plan.fallback_retrievers == ["keyword"]
    assert plan.fallback_ladder == [["milvus"], ["keyword"]]
    assert plan.query_features["knowledge_scope"] == "industry"
    assert plan.metadata["knowledge_scope"] == "industry"


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

    assert plan.selected_retrievers == ["milvus"]
    assert plan.fallback_ladder == [["milvus"], ["keyword"]]
    assert "graphrag" in plan.skipped_retrievers
    assert "page_index" in plan.skipped_retrievers


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
            query="请对比 A 和 B 的方案差异",
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
    test_rule_planner_table_value_lookup_uses_page_index()
    test_qwen_table_value_lookup_keeps_required_page_index()
    test_qwen_new_payload_filters_unknown_retriever_and_keeps_new_fields()
    test_router_executes_only_planned_retrievers_when_quality_is_enough()
    test_router_keyword_fallback_when_planned_empty()
    test_router_low_quality_milvus_triggers_keyword_fallback()
    logger.info("Retrieval Planner 单元测试通过")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    main()
