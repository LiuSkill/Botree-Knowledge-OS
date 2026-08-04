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

RESERVED_VISUAL_EVIDENCE_TOP_K = 3
FLOW_DIAGRAM_CATEGORIES = {"flow_diagram", "process_diagram"}
FLOW_DIAGRAM_TOKENS = (
    "process flow diagram",
    "process_flow_diagram",
    "flow diagram",
    "pfd",
    "流程图",
    "工艺流程",
    "实验流程",
)


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
        raw_evidences = [item for group in evidence_groups for item in group]
        reserved_visuals = self._reserved_visual_evidences(raw_evidences, visual_context)
        merged = self._top(self.merger.merge(evidence_groups, merge_limit), merge_limit)
        candidates = self._prepend_unique_evidences(reserved_visuals, self._top(merged, rerank_candidate_limit))
        guard = self.evidence_access_guard.filter_evidences(
            evidences=candidates,
            chat_type=chat_type,
            project_id=project_id,
            user=user,
            audit_action=audit_action,
        )
        guarded_reserved_visuals = self._filter_reserved_after_guard(guard.evidences, reserved_visuals)
        candidates = self._prepend_unique_evidences(
            guarded_reserved_visuals,
            self._top(guard.evidences, rerank_candidate_limit),
        )
        reserved_visuals = guarded_reserved_visuals
        before_ids = [self._debug_id(item) for item in candidates]
        before_scores = [float(item.score) for item in candidates]

        started_at = time.perf_counter()
        evidences = self._top(rerank(candidates, result_limit), result_limit)
        evidences = self._combine_reserved_visuals(evidences, reserved_visuals, result_limit, visual_context)
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
            reserved_visuals = self._filter_reserved_after_guard(evidences, reserved_visuals)
        if visual_limit is not None:
            evidences = self._top(evidences, visual_limit)
            evidences = self._combine_reserved_visuals(evidences, reserved_visuals, visual_limit, visual_context)

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

    def _reserved_visual_evidences(
        self,
        evidences: list[Evidence],
        visual_context: dict[str, Any] | None,
    ) -> list[Evidence]:
        """Reserve top visual hits for visual questions before RRF can crowd them out."""

        if not self._should_reserve_visual_evidence(visual_context):
            return []
        visual_evidences = [
            item
            for item in evidences
            if item.retriever == "visual" and item.assets and not item.metadata.get("metadata_only")
        ]
        return sorted(visual_evidences, key=self._visual_flow_rank, reverse=True)[:RESERVED_VISUAL_EVIDENCE_TOP_K]

    def _combine_reserved_visuals(
        self,
        evidences: list[Evidence],
        reserved_visuals: list[Evidence],
        limit: int,
        visual_context: dict[str, Any] | None,
    ) -> list[Evidence]:
        if not reserved_visuals or not self._should_reserve_visual_evidence(visual_context):
            return evidences
        return self._prepend_unique_evidences(reserved_visuals, evidences)[: max(0, limit)]

    def _filter_reserved_after_guard(
        self,
        candidates: list[Evidence],
        reserved_visuals: list[Evidence],
    ) -> list[Evidence]:
        if not reserved_visuals:
            return []
        candidate_keys = {self._evidence_identity(item) for item in candidates}
        return [item for item in reserved_visuals if self._evidence_identity(item) in candidate_keys]

    def _prefer_explicit_flow_diagram_documents(
        self,
        evidences: list[Evidence],
        visual_context: dict[str, Any],
    ) -> list[Evidence]:
        """Keep explicit flow-diagram documents when a visual flow query found them."""

        if not self._is_flow_visual_context(visual_context):
            return evidences
        matched_document_ids = {
            item.document_id
            for item in evidences
            if item.assets and self._is_explicit_flow_diagram_evidence(item)
        }
        if not matched_document_ids:
            return evidences
        return [item for item in evidences if item.document_id in matched_document_ids]

    @staticmethod
    def _prepend_unique_evidences(primary: list[Evidence], secondary: list[Evidence]) -> list[Evidence]:
        result: list[Evidence] = []
        seen: set[tuple[object, ...]] = set()
        for item in [*primary, *secondary]:
            key = RetrievalFinalizerService._evidence_identity(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    @staticmethod
    def _evidence_identity(evidence: Evidence) -> tuple[object, ...]:
        asset_id = evidence.metadata.get("asset_id")
        if asset_id is None and evidence.assets:
            asset_id = evidence.assets[0].asset_id
        if asset_id is not None:
            return ("asset", asset_id)
        return (
            evidence.retriever,
            evidence.document_id,
            evidence.chunk_id,
            evidence.page_number,
            evidence.metadata.get("block_id"),
        )

    @staticmethod
    def _is_flow_visual_context(visual_context: dict[str, Any] | None) -> bool:
        if visual_context is None:
            return False
        profile = dict(visual_context.get("query_profile") or visual_context)
        return bool(
            profile.get("query_type") == "process_flow"
            or profile.get("answer_shape") in {"process_steps", "flow_description", "material_flow"}
        )

    @staticmethod
    def _should_reserve_visual_evidence(visual_context: dict[str, Any] | None) -> bool:
        if visual_context is None:
            return False
        profile = dict(visual_context.get("query_profile") or visual_context)
        retrieval_needs = profile.get("retrieval_needs") or visual_context.get("retrieval_needs") or {}
        return bool(
            RetrievalFinalizerService._is_flow_visual_context(visual_context)
            or profile.get("need_visual_asset")
            or profile.get("visual_evidence")
            or visual_context.get("visual_evidence")
            or (isinstance(retrieval_needs, dict) and retrieval_needs.get("visual_evidence"))
        )

    def _visual_flow_rank(self, evidence: Evidence) -> tuple[int, int, float]:
        category_rank = 0
        priority_score = 0
        contexts = self._visual_contexts(evidence)
        for context in contexts:
            category = str(context.get("category") or "").strip().lower()
            if category in FLOW_DIAGRAM_CATEGORIES:
                category_rank = max(category_rank, 4)
            elif category == "equipment_diagram":
                category_rank = max(category_rank, 2)
            elif category == "table_snapshot":
                category_rank = max(category_rank, 1)
            try:
                priority_score = max(priority_score, int(context.get("priority_score") or 0))
            except (TypeError, ValueError):
                pass
        if self._contains_flow_token(evidence):
            category_rank = max(category_rank, 3)
        return (category_rank, priority_score, float(evidence.score))

    def _is_explicit_flow_diagram_evidence(self, evidence: Evidence) -> bool:
        for context in self._visual_contexts(evidence):
            category = str(context.get("category") or "").strip().lower()
            if category in FLOW_DIAGRAM_CATEGORIES:
                return True
            if self._context_contains_flow_token(context):
                return True
        return self._contains_flow_token(evidence)

    @staticmethod
    def _visual_contexts(evidence: Evidence) -> list[dict[str, Any]]:
        contexts: list[dict[str, Any]] = []
        metadata_context = evidence.metadata.get("visual_context")
        if isinstance(metadata_context, dict):
            contexts.append(metadata_context)
        for asset in evidence.assets:
            asset_context = asset.metadata.get("visual_context")
            if isinstance(asset_context, dict):
                contexts.append(asset_context)
            elif asset.metadata:
                contexts.append(asset.metadata)
        return contexts

    @staticmethod
    def _contains_flow_token(evidence: Evidence) -> bool:
        text = f"{evidence.file_name} {evidence.drawing_no or ''} {evidence.content}".lower()
        return any(token in text for token in FLOW_DIAGRAM_TOKENS)

    @staticmethod
    def _context_contains_flow_token(context: dict[str, Any]) -> bool:
        text = " ".join(
            str(context.get(key) or "")
            for key in ("source_file_name", "page_title", "figure_title", "context_text", "category")
        ).lower()
        return any(token in text for token in FLOW_DIAGRAM_TOKENS)
