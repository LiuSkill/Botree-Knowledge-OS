"""Result conversion and RRF fusion utilities."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from eval.beir.types import BeirResults, SearchHit


def hits_to_beir_results(query_hits: dict[str, list[SearchHit]]) -> BeirResults:
    """Convert query hits to BEIR results format: {query_id: {doc_id: score}}."""

    return {
        query_id: {hit.doc_id: float(hit.score) for hit in hits}
        for query_id, hits in query_hits.items()
    }


def reciprocal_rank_fusion(hit_groups: dict[str, list[SearchHit]], top_k: int, rrf_k: int = 60) -> list[SearchHit]:
    """Fuse multiple ranked lists using Reciprocal Rank Fusion."""

    scores: dict[str, float] = defaultdict(float)
    metadata: dict[str, dict[str, Any]] = defaultdict(lambda: {"sources": {}})
    sample_hit: dict[str, SearchHit] = {}
    for retriever_name, hits in hit_groups.items():
        seen: set[str] = set()
        for rank, hit in enumerate(hits, start=1):
            if hit.doc_id in seen:
                continue
            seen.add(hit.doc_id)
            sample_hit.setdefault(hit.doc_id, hit)
            scores[hit.doc_id] += 1.0 / (rrf_k + rank)
            metadata[hit.doc_id]["sources"][retriever_name] = {"rank": rank, "score": hit.score}

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [
        SearchHit(
            doc_id=doc_id,
            score=float(score),
            rank=rank,
            retriever="rrf",
            metadata=metadata[doc_id],
            title=sample_hit.get(doc_id, SearchHit(doc_id, 0.0, 0, "rrf")).title,
            text=sample_hit.get(doc_id, SearchHit(doc_id, 0.0, 0, "rrf")).text,
        )
        for rank, (doc_id, score) in enumerate(ranked, start=1)
    ]


def weighted_fusion(hit_groups: dict[str, list[SearchHit]], weights: dict[str, float], top_k: int) -> list[SearchHit]:
    """
    Fuse ranked lists with per-source weights.

    不同检索器的原始分数尺度差异较大，这里先对每一路分数做 min-max 归一化，
    再按配置权重累加，避免 BM25 原始分数天然压过向量相似度。
    """

    scores: dict[str, float] = defaultdict(float)
    metadata: dict[str, dict[str, Any]] = defaultdict(lambda: {"sources": {}})
    sample_hit: dict[str, SearchHit] = {}
    for retriever_name, hits in hit_groups.items():
        if not hits:
            continue
        weight = float(weights.get(retriever_name, 1.0))
        raw_scores = [float(hit.score) for hit in hits]
        min_score = min(raw_scores)
        max_score = max(raw_scores)
        denominator = max_score - min_score
        for rank, hit in enumerate(hits, start=1):
            normalized = (float(hit.score) - min_score) / denominator if denominator > 0 else 1.0
            scores[hit.doc_id] += weight * normalized
            sample_hit.setdefault(hit.doc_id, hit)
            metadata[hit.doc_id]["sources"][retriever_name] = {
                "rank": rank,
                "score": hit.score,
                "normalized_score": normalized,
                "weight": weight,
            }

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
    return [
        SearchHit(
            doc_id=doc_id,
            score=float(score),
            rank=rank,
            retriever="weighted",
            metadata=metadata[doc_id],
            title=sample_hit.get(doc_id, SearchHit(doc_id, 0.0, 0, "weighted")).title,
            text=sample_hit.get(doc_id, SearchHit(doc_id, 0.0, 0, "weighted")).text,
        )
        for rank, (doc_id, score) in enumerate(ranked, start=1)
    ]


def concat_dedupe_fusion(hit_groups: dict[str, list[SearchHit]], top_k: int) -> list[SearchHit]:
    """Concatenate ranked lists in adapter order and remove duplicate doc_ids."""

    fused: list[SearchHit] = []
    seen: set[str] = set()
    for retriever_name, hits in hit_groups.items():
        for hit in hits:
            if hit.doc_id in seen:
                continue
            seen.add(hit.doc_id)
            fused.append(
                SearchHit(
                    doc_id=hit.doc_id,
                    score=float(hit.score),
                    rank=len(fused) + 1,
                    retriever="concat_dedupe",
                    metadata={"sources": {retriever_name: {"rank": hit.rank, "score": hit.score}}},
                    title=hit.title,
                    text=hit.text,
                )
            )
            if len(fused) >= top_k:
                return fused
    return fused


def fuse_hits(
    hit_groups: dict[str, list[SearchHit]],
    method: str,
    top_k: int,
    weights: dict[str, float] | None = None,
) -> list[SearchHit]:
    """Dispatch a configured fusion method."""

    normalized = method.lower()
    if normalized == "rrf":
        return reciprocal_rank_fusion(hit_groups, top_k=top_k)
    if normalized == "weighted":
        return weighted_fusion(hit_groups, weights or {}, top_k=top_k)
    if normalized == "concat_dedupe":
        return concat_dedupe_fusion(hit_groups, top_k=top_k)
    raise ValueError(f"Unsupported fusion method: {method}")
