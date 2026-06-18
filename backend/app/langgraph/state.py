"""
LangGraph State

负责：
1. 定义在线检索问答的共享状态
2. 约束意图、查询拆解、召回、重排、回答和 trace 字段
3. 让各节点之间只通过标准状态对象传递数据
"""

from typing import Any, TypedDict

from app.retrieval.schemas import Evidence


class RetrievalGraphState(TypedDict, total=False):
    """
    在线检索问答状态

    职责：
    - 保存用户问题和权限上下文
    - 保存多路检索、重排和回答结果
    - 保存可审计的执行轨迹
    """

    question: str
    chat_type: str
    mode: str
    project_id: int | None
    user: Any
    intent: str
    direct_answer: bool
    direct_answer_type: str | None
    route_decision: dict[str, Any]
    sub_queries: list[str]
    query_profile: dict[str, Any]
    retrieval_plan: dict[str, Any]
    query_features: dict[str, Any]
    query_scope: str
    used_retrievers: list[str]
    planned_retrievers: list[str]
    executed_retrievers: list[str]
    skipped_retrievers: list[str]
    skip_reasons: dict[str, str]
    fallback_ladder: list[list[str]]
    fallback_used: list[str]
    fallback_trigger_reason: list[dict[str, Any]]
    retriever_hits: dict[str, int]
    retriever_elapsed_ms: dict[str, int]
    retriever_top_scores: dict[str, float]
    rerank_details: list[dict[str, Any]]
    evidences: list[Evidence]
    visual_asset_count: int
    evidence_judgement: dict[str, Any]
    model_routes: dict[str, dict[str, Any]]
    answer: str
    trace: list[dict[str, Any]]
    raw: dict[str, Any]
