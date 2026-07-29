"""统一完成检索证据的融合、安全过滤、重排与视觉增强。"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from app.retrieval.merger import EvidenceMerger
from app.retrieval.schemas import Evidence
from app.services.evidence_access_guard_service import EvidenceAccessGuardService

logger = logging.getLogger(__name__)


class _Reranker(Protocol):
    last_details: list[dict[str, Any]]
    last_runtime: dict[str, Any]


class _VisualEvidenceService(Protocol):
    def enrich(
        self,
        question: str,
        evidences: list[Evidence],
        query_features: dict[str, Any] | None = None,
    ) -> list[Evidence]: ...


@dataclass(frozen=True)
class RetrievalFinalizationResult:
    evidences: list[Evidence]
    merged_count: int
    metadata_filtered_count: int
    visual_asset_count: int
    pre_rerank_guard: dict[str, Any]
    rerank_details: list[dict[str, Any]]
    reranker_runtime: dict[str, Any]
    before_rerank_ids: list[str]
    before_rerank_scores: list[float]
    rerank_elapsed_ms: int


class RetrievalFinalizerService:
    """收拢所有检索入口共同遵守的最终证据规则。"""

    def __init__(
        self,
        *,
        evidence_access_guard: EvidenceAccessGuardService,
        reranker: _Reranker,
        visual_evidence_service: _VisualEvidenceService | None = None,
        merger: EvidenceMerger | None = None,
    ) -> None:
        self.evidence_access_guard = evidence_access_guard
        self.reranker = reranker
        self.visual_evidence_service = visual_evidence_service
        self.merger = merger or EvidenceMerger()

    def finalize(
        self,
        *,
        query: str,
        evidence_groups: list[list[Evidence]],
        merge_limit: int,
        rerank_candidate_limit: int,
        result_limit: int,
        chat_type: str,
        project_id: int | None,
        user: Any | None,
        rerank: Callable[[list[Evidence], int], list[Evidence]],
        visual_context: dict[str, Any] | None = None,
        visual_limit: int | None = None,
        audit_action: str = "RAG证据权限过滤",
    ) -> RetrievalFinalizationResult:
        finalization_started_at = time.perf_counter()
        merged = self._top(self.merger.merge(evidence_groups, merge_limit), merge_limit)
        candidates = self._top(merged, rerank_candidate_limit)
        guard = self.evidence_access_guard.filter_evidences(
            evidences=candidates,
            chat_type=chat_type,
            project_id=project_id,
            user=user,
            audit_action=audit_action,
        )
        candidates = self._top(guard.evidences, rerank_candidate_limit)
        before_ids = [self._debug_id(item) for item in candidates]
        before_scores = [float(item.score) for item in candidates]

        started_at = time.perf_counter()
        evidences = self._top(rerank(candidates, result_limit), result_limit)
        rerank_elapsed_ms = int((time.perf_counter() - started_at) * 1000)

        metadata_filtered_count = sum(bool(item.metadata.get("metadata_only")) for item in evidences)
        if metadata_filtered_count:
            evidences = self._top(
                [item for item in evidences if not item.metadata.get("metadata_only")],
                result_limit,
            )

        if self.visual_evidence_service is not None and visual_context is not None:
            context = dict(visual_context)
            if any(item.retriever == "visual" for item in evidences):
                context["visual_evidence"] = True
            evidences = self.visual_evidence_service.enrich(query, evidences, context)
        if visual_context is not None:
            evidences = self._prefer_explicit_flow_diagram_documents(evidences, visual_context)
        if visual_limit is not None:
            evidences = self._top(evidences, visual_limit)

        guard_details = guard.to_dict()
        guard_details["accepted"] = len(guard.evidences)
        result = RetrievalFinalizationResult(
            evidences=evidences,
            merged_count=len(merged),
            metadata_filtered_count=metadata_filtered_count,
            visual_asset_count=sum(len(item.assets) for item in evidences),
            pre_rerank_guard=guard_details,
            rerank_details=list(getattr(self.reranker, "last_details", [])),
            reranker_runtime=dict(getattr(self.reranker, "last_runtime", {})),
            before_rerank_ids=before_ids,
            before_rerank_scores=before_scores,
            rerank_elapsed_ms=rerank_elapsed_ms,
        )
        logger.info(
            "检索证据统一收尾完成: project_id=%s merged_count=%s accepted_count=%s final_count=%s "
            "metadata_filtered_count=%s visual_asset_count=%s rerank_elapsed_ms=%s elapsed_ms=%s",
            project_id,
            result.merged_count,
            len(guard.evidences),
            len(result.evidences),
            result.metadata_filtered_count,
            result.visual_asset_count,
            result.rerank_elapsed_ms,
            int((time.perf_counter() - finalization_started_at) * 1000),
        )
        return result

    @staticmethod
    def _top(evidences: list[Evidence], limit: int) -> list[Evidence]:
        return sorted(evidences, key=lambda item: float(item.score), reverse=True)[: max(0, limit)]

    @staticmethod
    def _debug_id(evidence: Evidence) -> str:
        return f"{evidence.document_id}:{evidence.chunk_id}"

    @staticmethod
    def _prefer_explicit_flow_diagram_documents(
        evidences: list[Evidence],
        visual_context: dict[str, Any],
    ) -> list[Evidence]:
        """Keep explicit flow-diagram documents when a visual flow query found them."""

        profile = dict(visual_context.get("query_profile") or visual_context)
        if profile.get("query_type") != "process_flow" or not (
            profile.get("need_visual_asset") or visual_context.get("visual_evidence")
        ):
            return evidences
        flow_tokens = ("process flow diagram", "process_flow_diagram", "pfd", "流程图", "工艺流程")
        matched_document_ids = {
            item.document_id
            for item in evidences
            if item.assets
            and any(
                token in f"{item.file_name} {item.content}".lower()
                for token in flow_tokens
            )
        }
        if not matched_document_ids:
            return evidences
        return [item for item in evidences if item.document_id in matched_document_ids]
