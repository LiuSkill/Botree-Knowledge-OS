"""跨通道证据排名融合、去重与来源保留。"""

from __future__ import annotations

import re

from app.retrieval.schemas import Evidence

DEFAULT_MERGED_EVIDENCE_TOP_K = 20
RRF_K = 60


class EvidenceMerger:
    """通过 RRF 消除不同检索空间原始分数不可比的问题。"""

    def merge(self, evidence_groups: list[list[Evidence]], limit: int = DEFAULT_MERGED_EVIDENCE_TOP_K) -> list[Evidence]:
        fused: dict[tuple[object, ...], Evidence] = {}
        fused_scores: dict[tuple[object, ...], float] = {}
        for group in evidence_groups:
            ordered = sorted(group, key=lambda item: float(item.score), reverse=True)
            for rank, item in enumerate(ordered, start=1):
                key = self._dedupe_key(item)
                contribution = 1.0 / (RRF_K + rank)
                mapping = self._source_mapping(item)
                if key not in fused:
                    item.metadata = {
                        **item.metadata,
                        "fusion_method": "rrf",
                        "source_mappings": [mapping],
                        "raw_scores": {item.retriever: float(item.score)},
                    }
                    fused[key] = item
                    fused_scores[key] = contribution
                    continue
                existing = fused[key]
                fused_scores[key] += contribution
                if mapping not in existing.metadata["source_mappings"]:
                    existing.metadata["source_mappings"].append(mapping)
                existing.metadata["raw_scores"][item.retriever] = float(item.score)
                existing.assets.extend(asset for asset in item.assets if asset.asset_id not in {a.asset_id for a in existing.assets})
        for key, item in fused.items():
            item.score = fused_scores[key]
            item.metadata["fused_score"] = fused_scores[key]
        ordered = sorted(fused.values(), key=lambda item: float(item.score), reverse=True)
        return self._diversify(ordered, limit)

    def _diversify(self, evidences: list[Evidence], limit: int) -> list[Evidence]:
        """先覆盖不同文档/页面/区域，再按融合分数补齐，保留参数略有差异的近重复项。"""

        selected: list[Evidence] = []
        deferred: list[Evidence] = []
        seen_sources: set[tuple[object, ...]] = set()
        for evidence in evidences:
            source = (
                evidence.document_id,
                evidence.page_number,
                evidence.metadata.get("block_id") if evidence.retriever == "visual" else None,
            )
            if source in seen_sources:
                deferred.append(evidence)
                continue
            seen_sources.add(source)
            selected.append(evidence)
            if len(selected) >= limit:
                return selected
        return (selected + deferred)[:limit]

    def _dedupe_key(self, evidence: Evidence) -> tuple[object, ...]:
        if evidence.retriever == "visual" or evidence.metadata.get("asset_id"):
            return ("visual", evidence.metadata.get("asset_id"), evidence.metadata.get("block_id"))
        normalized = re.sub(r"\s+", " ", evidence.content).strip().lower()
        return ("content", normalized) if normalized else ("chunk", evidence.document_id, evidence.chunk_id)

    def _source_mapping(self, evidence: Evidence) -> dict[str, object]:
        return {
            "document_id": evidence.document_id,
            "chunk_id": evidence.chunk_id,
            "page_number": evidence.page_number,
            "retriever": evidence.retriever,
            "asset_id": evidence.metadata.get("asset_id"),
        }
