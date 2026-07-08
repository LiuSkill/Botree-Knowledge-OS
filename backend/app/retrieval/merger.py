"""
Evidence Merger

负责：
1. 合并多检索器返回的证据
2. 按 Chunk 去重并按得分排序
3. 控制最终传给 Agent 的证据数量
"""

from app.retrieval.schemas import Evidence

DEFAULT_MERGED_EVIDENCE_TOP_K = 20


class EvidenceMerger:
    """
    证据合并器

    职责：
    - 去除重复 Chunk
    - 保留最高得分证据
    """

    def merge(self, evidence_groups: list[list[Evidence]], limit: int = DEFAULT_MERGED_EVIDENCE_TOP_K) -> list[Evidence]:
        """
        合并证据

        参数:
            evidence_groups: 多个检索器证据列表
            limit: 最大返回数量

        返回:
            合并后的证据列表。
        """

        by_chunk: dict[int, Evidence] = {}
        for group in evidence_groups:
            for item in group:
                existing = by_chunk.get(item.chunk_id)
                if existing is None or item.score > existing.score:
                    by_chunk[item.chunk_id] = item
        return sorted(by_chunk.values(), key=lambda item: item.score, reverse=True)[:limit]
