"""
PageIndex Retriever

Responsible for page-level retrieval over published page indexes and
mapping results back into unified evidence objects.
"""

from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk
from app.models.page_index import PageIndex
from app.models.user import User
from app.repositories.page_index_repository import PageIndexRepository
from app.retrieval.base import BaseRetriever, DEFAULT_RETRIEVER_TOP_K
from app.retrieval.query_utils import augment_query_terms, is_structured_list_lookup_query, is_table_value_lookup_query, normalize_query_text
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.schemas import Evidence
from app.retrieval.scope import normalize_retrieval_scope
from app.services.project_document_policy_service import ProjectDocumentPolicyService

logger = logging.getLogger(__name__)


class PageIndexRetriever(BaseRetriever):
    """
    PageIndex retriever.

    Responsibilities:
    - score page-level index text and mapped chunks
    - return chunk-backed evidence with page/drawing metadata
    - for flow questions, prioritize drawing-like documents before falling back
    """

    name = "page_index"

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.page_repository = PageIndexRepository(db)
        self.keyword_policy = KeywordRetriever(db)

    def search(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = DEFAULT_RETRIEVER_TOP_K,
        *,
        retrieval_scope: dict[str, object] | None = None,
    ) -> list[Evidence]:
        """Execute page index retrieval."""

        terms = augment_query_terms(query, self.keyword_policy._terms(query))
        normalized_scope = normalize_retrieval_scope(retrieval_scope)
        flow_diagram_query = self._is_flow_diagram_query(query)
        structured_list_query = is_structured_list_lookup_query(query)
        table_value_query = is_table_value_lookup_query(query)
        effective_limit = self._effective_candidate_limit(
            requested_limit=limit,
            flow_diagram_query=flow_diagram_query,
            structured_query=structured_list_query or table_value_query,
        )
        row_limit = self._candidate_row_limit(
            effective_limit=effective_limit,
            flow_diagram_query=flow_diagram_query,
            structured_query=structured_list_query or table_value_query,
        )
        evidences: list[Evidence] = []
        project_document_policy = ProjectDocumentPolicyService(self.db)
        allowed_levels = set(self.keyword_policy._allowed_security_levels(user))
        search_filters = self._index_search_filters(mode, project_id)
        search_filters.update(self._scope_search_filters(normalized_scope))
        scanned_rows = 0

        if flow_diagram_query:
            diagram_rows = self.page_repository.list_searchable_index_rows(
                list(allowed_levels),
                query_terms=self._diagram_query_terms(terms),
                match_document_metadata=True,
                diagram_only=True,
                row_limit=min(row_limit, max(effective_limit * 6, 80)),
                **search_filters,
            )
            scanned_rows += len(diagram_rows)
            evidences.extend(
                self._collect_evidences(
                    rows=diagram_rows,
                    query=query,
                    terms=terms,
                    document_terms=self._diagram_query_terms(terms),
                    mode=mode,
                    project_id=project_id,
                    user=user,
                    allowed_levels=allowed_levels,
                    project_document_policy=project_document_policy,
                    prefer_diagram_documents=True,
                    structured_list_query=structured_list_query,
                )
            )

        if len(self._dedupe_results(evidences, query)) < effective_limit:
            rows = self.page_repository.list_searchable_index_rows(
                list(allowed_levels),
                query_terms=terms,
                match_document_metadata=structured_list_query or table_value_query,
                row_limit=row_limit,
                **search_filters,
            )
            scanned_rows += len(rows)
            evidences.extend(
                self._collect_evidences(
                    rows=rows,
                    query=query,
                    terms=terms,
                    document_terms=terms,
                    mode=mode,
                    project_id=project_id,
                    user=user,
                    allowed_levels=allowed_levels,
                    project_document_policy=project_document_policy,
                    prefer_diagram_documents=flow_diagram_query,
                    structured_list_query=structured_list_query,
                )
            )

        results = self._dedupe_results(evidences, query)[:effective_limit]
        logger.info(
            "PageIndex候选集收缩: requested_limit=%s effective_limit=%s row_limit=%s scanned_rows=%s returned=%s flow=%s structured=%s query_preview=%s",
            limit,
            effective_limit,
            row_limit,
            scanned_rows,
            len(results),
            flow_diagram_query,
            structured_list_query or table_value_query,
            query[:120],
        )
        return results

    def _collect_evidences(
        self,
        *,
        rows: list[tuple[PageIndex, Document, DocumentChunk]],
        query: str,
        terms: list[str],
        document_terms: list[str],
        mode: str,
        project_id: int | None,
        user: User,
        allowed_levels: set[str],
        project_document_policy: ProjectDocumentPolicyService,
        prefer_diagram_documents: bool,
        structured_list_query: bool,
    ) -> list[Evidence]:
        evidences: list[Evidence] = []
        for page_index, document, chunk in rows:
            if not self._row_allowed(
                document=document,
                chunk=chunk,
                mode=mode,
                project_id=project_id,
                user=user,
                allowed_levels=allowed_levels,
                project_document_policy=project_document_policy,
            ):
                continue

            page_score = self.keyword_policy._score(page_index.index_text, query, terms)
            chunk_score = self.keyword_policy._score(chunk.content, query, terms)
            drawing_no = page_index.drawing_no or document.drawing_no
            document_score = self.keyword_policy._score(
                self._document_search_text(document, drawing_no),
                query,
                document_terms,
            )
            if page_score <= 0 and chunk_score <= 0 and document_score <= 0:
                continue

            # Same page may map to multiple chunks; use chunk score for answer text
            # and document-level score/penalties to lift real drawings for flow queries.
            score = page_score + chunk_score * 0.6
            if structured_list_query:
                score += min(document_score, 4.0) * 0.7
            bonus = 0.0
            penalty = 0.0
            if prefer_diagram_documents:
                bonus = self._diagram_priority_bonus(document)
                penalty = self._diagram_noise_penalty(document)
                score += min(document_score, 4.0) * 0.8 + bonus - penalty

            if score <= 0:
                continue

            evidences.append(
                Evidence(
                    score=score + 1.0,
                    source_type=self.keyword_policy._source_type(document.knowledge_type, mode),
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    chunk_id=chunk.id,
                    drawing_no=drawing_no,
                    file_name=document.file_name,
                    page_number=page_index.page_no,
                    content=chunk.content,
                    retriever=self.name,
                    metadata=self.keyword_policy._evidence_metadata(
                        document,
                        chunk,
                        {
                            "page_index_id": page_index.id,
                            "page_score": round(page_score, 4),
                            "chunk_score": round(chunk_score, 4),
                            "document_score": round(document_score, 4),
                            "diagram_priority_bonus": round(bonus, 4),
                            "diagram_noise_penalty": round(penalty, 4),
                            "page_index_security_level": page_index.security_level,
                            "prefer_diagram_documents": prefer_diagram_documents,
                            "structured_list_query": structured_list_query,
                        },
                    ),
                )
            )
        return sorted(evidences, key=lambda item: item.score, reverse=True)

    def _row_allowed(
        self,
        *,
        document: Document,
        chunk: DocumentChunk,
        mode: str,
        project_id: int | None,
        user: User,
        allowed_levels: set[str],
        project_document_policy: ProjectDocumentPolicyService,
    ) -> bool:
        if not self.keyword_policy._scope_allowed(
            document.knowledge_type,
            document.project_id,
            document.knowledge_base_id,
            mode,
            project_id,
            user,
        ):
            return False
        if document.project_id is not None:
            if project_document_policy.project_chat_document_reject_reason(
                document,
                user=user,
                project_id=project_id,
                require_chat_permission=mode == "project_chat",
            ):
                return False
        if document.project_id is not None and project_document_policy.project_chat_chunk_reject_reason(
            chunk,
            document,
            user=user,
            project_id=project_id,
        ):
            return False
        return chunk.security_level in allowed_levels

    def _effective_candidate_limit(
        self,
        *,
        requested_limit: int,
        flow_diagram_query: bool,
        structured_query: bool,
    ) -> int:
        try:
            normalized_limit = int(requested_limit)
        except (TypeError, ValueError):
            normalized_limit = DEFAULT_RETRIEVER_TOP_K
        configured_limit = self._safe_positive_int(
            getattr(getattr(self, "settings", None), "retrieval_page_index_candidate_limit", DEFAULT_RETRIEVER_TOP_K),
            DEFAULT_RETRIEVER_TOP_K,
        )
        if structured_query:
            configured_limit = max(configured_limit, int(configured_limit * 1.5))
        elif flow_diagram_query:
            configured_limit = min(configured_limit, 24)
        return max(1, min(max(normalized_limit, 1), configured_limit))

    def _candidate_row_limit(
        self,
        *,
        effective_limit: int,
        flow_diagram_query: bool,
        structured_query: bool,
    ) -> int:
        configured_limit = self._safe_positive_int(
            getattr(getattr(self, "settings", None), "retrieval_page_index_row_limit", 240),
            240,
        )
        if structured_query:
            configured_limit = max(configured_limit, int(configured_limit * 1.5))
            proportional_limit = max(effective_limit * 12, effective_limit + 40)
        elif flow_diagram_query:
            configured_limit = min(configured_limit, 160)
            proportional_limit = max(effective_limit * 8, effective_limit + 32)
        else:
            proportional_limit = max(effective_limit * 8, effective_limit + 32)
        return max(effective_limit, min(configured_limit, proportional_limit))

    def _safe_positive_int(self, value: object, default: int) -> int:
        try:
            normalized = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            normalized = default
        return max(1, normalized)

    def _index_search_filters(self, mode: str, project_id: int | None) -> dict[str, object]:
        effective_mode = self.keyword_policy._effective_mode(mode, project_id)
        if effective_mode in {"project_chat", "project_only"} and project_id is not None:
            return {"knowledge_type": "project", "project_id": project_id}
        if effective_mode in {"base_chat", "base_only"}:
            return {"knowledge_type": "base"}
        return {}

    def _scope_search_filters(self, retrieval_scope: dict[str, object]) -> dict[str, object]:
        filters: dict[str, object] = {}
        for key in ("document_ids", "chunk_ids", "page_numbers_by_document"):
            value = retrieval_scope.get(key)
            if value:
                filters[key] = value
        return filters

    def _is_flow_diagram_query(self, query: str) -> bool:
        lowered = normalize_query_text(query).lower()
        return any(
            hint in lowered
            for hint in (
                "流程",
                "flow",
                "p&id",
                "pid",
                "pfd",
                "diagram",
                "drawing",
                "进料",
                "出料",
                "物料流向",
                "上下游",
                "evaporation",
                "crystallization",
            )
        )

    def _diagram_query_terms(self, terms: list[str]) -> list[str]:
        return list(dict.fromkeys([*terms, "pid", "p&id", "pfd", "flow", "diagram", "drawing", "流程图", "工艺流程"]))

    def _document_search_text(self, document: Document, drawing_no: str | None) -> str:
        return " ".join(
            filter(
                None,
                [
                    document.file_name,
                    document.document_name,
                    document.drawing_name,
                    drawing_no,
                    document.document_type,
                    document.discipline,
                ],
            )
        )

    def _diagram_priority_bonus(self, document: Document) -> float:
        text = self._document_search_text(document, document.drawing_no).lower()
        bonus = 0.0
        if "process flow diagram" in text or "流程图" in text or "工艺流程" in text:
            bonus += 2.0
        if "pfd" in text:
            bonus += 1.6
        if "p&id" in text or "pid" in text:
            bonus += 1.2
        if document.document_type == "图纸":
            bonus += 0.6
        return bonus

    def _diagram_noise_penalty(self, document: Document) -> float:
        text = self._document_search_text(document, document.drawing_no).lower()
        penalty = 0.0
        if "index" in text:
            penalty += 2.4
        if "list" in text or "summary" in text or "legend" in text:
            penalty += 1.5
        if any(token in text for token in ("comment", "reply", "meeting", "纪要", "审查")):
            penalty += 1.2
        return penalty

    def _dedupe_results(self, evidences: list[Evidence], query: str) -> list[Evidence]:
        if self._should_keep_multiple_chunks_per_page(query):
            best_by_chunk: dict[tuple[int, int], Evidence] = {}
            for evidence in sorted(evidences, key=lambda item: item.score, reverse=True):
                chunk_key = (evidence.document_id, evidence.chunk_id)
                best_by_chunk.setdefault(chunk_key, evidence)
            return list(best_by_chunk.values())
        return self._dedupe_by_page(evidences)

    def _should_keep_multiple_chunks_per_page(self, query: str) -> bool:
        return is_table_value_lookup_query(query) or is_structured_list_lookup_query(query)

    def _dedupe_by_page(self, evidences: list[Evidence]) -> list[Evidence]:
        best_by_page: dict[tuple[int, int | None, str | None], Evidence] = {}
        for evidence in sorted(evidences, key=lambda item: item.score, reverse=True):
            page_key = (evidence.document_id, evidence.page_number, evidence.drawing_no)
            best_by_page.setdefault(page_key, evidence)
        return list(best_by_page.values())
