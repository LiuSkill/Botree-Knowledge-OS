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

    def chat(self, _: list[dict[str, str]]) -> str:
        """
        返回非 JSON 内容，触发 Qwen Planner 回退。

        返回:
            非法 JSON 字符串
        """

        return "not json"


class FakeTablePlannerLLMService:
    """
    测试用 Qwen Planner。

    职责：
    - 模拟模型只选择 milvus/ripgrep 的情况
    - 验证规则层会为表格数值查询补齐 page_index
    """

    def __init__(self, _: Any) -> None:
        self.db = None

    def chat(self, _: list[dict[str, str]]) -> str:
        """返回合法 Planner JSON。"""

        return '{"selected_retrievers": ["milvus", "ripgrep"], "reason": "model plan", "confidence": 0.9}'


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
    router._prepare_scope = lambda mode, project_id, chat_type, user: mode  # type: ignore[method-assign]
    router._scope_text = lambda mode: mode  # type: ignore[method-assign]
    return router


def test_rule_planner_exact_lookup() -> None:
    """
    exact_lookup 必须优先选择 ripgrep 和 page_index。
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
    assert plan.selected_retrievers == ["ripgrep", "page_index"]
    assert plan.fallback_retrievers == ["keyword"]
    assert plan.fallback_ladder == [["ripgrep"], ["page_index"], ["keyword"]]
    assert plan.qwen_used is False


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
    assert plan.selected_retrievers == ["graphrag", "milvus"]
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
    test_rule_planner_filters_disabled_milvus()
    test_qwen_invalid_output_falls_back_to_rules()
    test_knowledge_qa_natural_language_prefers_milvus_only()
    test_rule_planner_table_value_lookup_uses_page_index()
    test_qwen_table_value_lookup_keeps_required_page_index()
    test_router_executes_only_planned_retrievers_when_quality_is_enough()
    test_router_keyword_fallback_when_planned_empty()
    test_router_low_quality_milvus_triggers_keyword_fallback()
    logger.info("Retrieval Planner 单元测试通过")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
    main()
