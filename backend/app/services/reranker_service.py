"""
Reranker Service

负责：
1. 对 PageIndex、Milvus、ripgrep、GraphRAG 等多路证据统一重排
2. 保留重排分数和原因，供检索审计使用
3. 在专用 Qwen Reranker 未接入时提供确定性排序降级
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from app.retrieval.query_utils import boilerplate_multiplier, contains_search_token, extract_query_terms, normalize_query_text, score_text_relevance
from app.retrieval.schemas import Evidence


class RerankerService:
    """
    证据重排服务

    职责：
    - 综合原始召回分数、精确命中和来源类型权重
    - 输出排序后的 Evidence
    - 为 retrieval_trace 提供可审计的分数明细
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.last_details: list[dict] = []

    def rerank(self, query: str, evidences: list[Evidence], limit: int = 5) -> list[Evidence]:
        """
        重排证据。

        参数:
            query: 用户问题。
            evidences: 合并去重后的证据。
            limit: 返回数量。

        返回:
            重排后的证据列表。
        """

        terms = self._terms(query)
        scored: list[tuple[float, Evidence, dict]] = []
        for evidence in evidences:
            exact_bonus = self._exact_bonus(evidence.content, query, terms)
            source_bonus = self._source_bonus(evidence.retriever)
            relevance_bonus = score_text_relevance(evidence.content, query, terms) * 0.3
            quality_multiplier = boilerplate_multiplier(evidence.content)
            raw_score = evidence.score
            final_score = (raw_score + exact_bonus + source_bonus + relevance_bonus) * quality_multiplier
            evidence.metadata = {
                **evidence.metadata,
                "rerank_score": final_score,
                "rerank_raw_score": raw_score,
                "rerank_exact_bonus": exact_bonus,
                "rerank_source_bonus": source_bonus,
                "rerank_relevance_bonus": relevance_bonus,
                "rerank_quality_multiplier": quality_multiplier,
            }
            evidence.score = final_score
            scored.append(
                (
                    final_score,
                    evidence,
                    {
                        "retriever": evidence.retriever,
                        "document_id": evidence.document_id,
                        "chunk_id": evidence.chunk_id,
                        "page_number": evidence.page_number,
                        "raw_score": raw_score,
                        "score": final_score,
                        "quality_multiplier": quality_multiplier,
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        self.last_details = [item[2] for item in scored[:limit]]
        return [item[1] for item in scored[:limit]]

    def _terms(self, query: str) -> list[str]:
        """抽取重排关键词。"""

        return extract_query_terms(query)

    def _exact_bonus(self, content: str, query: str, terms: list[str]) -> float:
        """计算精确命中奖励分。"""

        text = normalize_query_text(content).lower()
        bonus = 0.0
        if query and normalize_query_text(query).lower() in text:
            bonus += 5.0
        for term in terms:
            if term and contains_search_token(text, term):
                bonus += 0.8
        return bonus

    def _source_bonus(self, retriever: str) -> float:
        """根据召回来源给出稳定优先级。"""

        return {
            "ripgrep": 1.5,
            "page_index": 1.3,
            "graphrag": 0.9,
            "milvus": 0.6,
            "keyword": 0.2,
        }.get(retriever, 0.0)
