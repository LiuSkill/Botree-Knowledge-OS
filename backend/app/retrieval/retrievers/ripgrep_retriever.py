"""
ripgrep retriever.

Use ripgrep over page-index text mirrors and map matches back to chunk-backed
evidence objects.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document, DocumentChunk
from app.models.page_index import PageIndex
from app.models.user import User
from app.repositories.page_index_repository import PageIndexRepository
from app.retrieval.base import BaseRetriever, DEFAULT_RETRIEVER_TOP_K
from app.retrieval.query_utils import (
    augment_query_terms,
    expand_search_phrases,
    extract_query_terms,
    is_structured_list_lookup_query,
    is_table_value_lookup_query,
    normalize_query_text,
    score_text_relevance,
)
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.schemas import Evidence
from app.retrieval.scope import normalize_retrieval_scope
from app.services.project_document_policy_service import ProjectDocumentPolicyService

logger = logging.getLogger(__name__)

RIPGREP_MAX_COMMAND_CHARS = 28000


class RipgrepRetriever(BaseRetriever):
    """Exact-text retriever backed by ripgrep over page mirror files."""

    name = "ripgrep"

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.page_repository = PageIndexRepository(db)
        self.keyword_policy = KeywordRetriever(db)
        self._binary_available: bool | None = None

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
        """Run exact search over authorized page mirror files."""

        query_terms = augment_query_terms(query)
        normalized_scope = normalize_retrieval_scope(retrieval_scope)
        structured_query = is_structured_list_lookup_query(query) or is_table_value_lookup_query(query)
        patterns = self._limited_patterns(query, expand_search_phrases(query), structured_query=structured_query)
        structured_list_query = is_structured_list_lookup_query(query)
        if not query.strip() or not patterns or not self._is_ripgrep_available():
            return []

        effective_limit = self._effective_candidate_limit(
            requested_limit=limit,
            structured_query=structured_query,
        )
        row_limit = self._candidate_row_limit(effective_limit=effective_limit, structured_query=structured_query)
        prefilter_terms = self._prefilter_terms(query, query_terms, structured_query=structured_query)
        project_document_policy = ProjectDocumentPolicyService(self.db)
        allowed_indexes = self._allowed_page_indexes(
            mode,
            project_id,
            user,
            project_document_policy,
            prefilter_terms,
            match_document_metadata=structured_query,
            row_limit=row_limit,
            retrieval_scope=normalized_scope,
        )
        path_map: dict[str, list[tuple[PageIndex, Document, DocumentChunk]]] = {}
        for page_index, document, chunk in allowed_indexes:
            if not page_index.text_mirror_path or not page_index.chunk_id:
                continue
            path_map.setdefault(str(Path(page_index.text_mirror_path).resolve()), []).append((page_index, document, chunk))
        if not path_map:
            return []

        pattern_args = [value for pattern in patterns for value in ("-e", pattern)]
        base_args = [
            self.settings.ripgrep_binary,
            "--json",
            "--fixed-strings",
            "--ignore-case",
            "--max-count",
            str(self._max_count_per_file(structured_query=structured_query)),
            *pattern_args,
        ]
        deadline = time.perf_counter() + max(int(self.settings.ripgrep_timeout_ms), 1) / 1000

        evidences: list[Evidence] = []
        seen_chunks: set[int] = set()
        max_candidates = max(effective_limit * 3, effective_limit)
        for batch_paths in self._path_batches(base_args, list(path_map.keys())):
            remaining_seconds = deadline - time.perf_counter()
            if remaining_seconds <= 0:
                logger.warning(
                    "ripgrep timed out: timeout_ms=%s file_count=%s query_preview=%s",
                    self.settings.ripgrep_timeout_ms,
                    len(path_map),
                    query[:120],
                )
                break

            try:
                completed = subprocess.run(
                    [*base_args, *batch_paths],
                    check=False,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=max(remaining_seconds, 0.05),
                )
            except FileNotFoundError as exc:
                logger.warning("ripgrep start failed: binary=%s error=%s", self.settings.ripgrep_binary, exc)
                return []
            except subprocess.TimeoutExpired:
                logger.warning(
                    "ripgrep timed out: timeout_ms=%s file_count=%s query_preview=%s",
                    self.settings.ripgrep_timeout_ms,
                    len(path_map),
                    query[:120],
                )
                break
            except (subprocess.SubprocessError, OSError) as exc:
                logger.warning("ripgrep search failed: %s", exc)
                return []

            for line in completed.stdout.splitlines():
                hit = self._parse_rg_match(line)
                if not hit:
                    continue
                rows = path_map.get(hit["path"])
                if not rows:
                    continue
                for page_index, document, chunk in self._rank_rows_for_hit(rows, hit["line"], query, query_terms):
                    if page_index.chunk_id in seen_chunks:
                        continue
                    evidence = self._to_evidence(
                        page_index,
                        document,
                        chunk,
                        hit["line"],
                        query,
                        query_terms,
                        mode,
                        project_id,
                        user,
                        project_document_policy,
                        structured_list_query,
                    )
                    if evidence:
                        evidences.append(evidence)
                        seen_chunks.add(page_index.chunk_id)
                    if len(evidences) >= max_candidates:
                        results = sorted(evidences, key=lambda item: item.score, reverse=True)[:effective_limit]
                        self._log_candidate_shrink(
                            query=query,
                            requested_limit=limit,
                            effective_limit=effective_limit,
                            row_limit=row_limit,
                            allowed_row_count=len(allowed_indexes),
                            path_count=len(path_map),
                            pattern_count=len(patterns),
                            returned_count=len(results),
                            structured_query=structured_query,
                        )
                        return results

        results = sorted(evidences, key=lambda item: item.score, reverse=True)[:effective_limit]
        self._log_candidate_shrink(
            query=query,
            requested_limit=limit,
            effective_limit=effective_limit,
            row_limit=row_limit,
            allowed_row_count=len(allowed_indexes),
            path_count=len(path_map),
            pattern_count=len(patterns),
            returned_count=len(results),
            structured_query=structured_query,
        )
        return results

    def _is_ripgrep_available(self) -> bool:
        if self._binary_available is not None:
            return self._binary_available
        binary = str(self.settings.ripgrep_binary or "").strip()
        resolved_binary = shutil.which(binary) if binary else None
        if not resolved_binary:
            self._binary_available = False
        else:
            try:
                subprocess.run(
                    [binary, "--version"],
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=1,
                )
                self._binary_available = True
            except (FileNotFoundError, OSError, subprocess.SubprocessError):
                self._binary_available = False
        if not self._binary_available:
            logger.warning("ripgrep unavailable: binary=%s", self.settings.ripgrep_binary)
        return self._binary_available

    def _path_batches(self, base_args: list[str], paths: list[str], max_command_chars: int = RIPGREP_MAX_COMMAND_CHARS) -> list[list[str]]:
        """Batch file paths to stay below Windows command length limits."""

        batches: list[list[str]] = []
        current_batch: list[str] = []
        base_size = sum(len(arg) + 1 for arg in base_args)
        current_size = base_size
        for path in paths:
            path_size = len(path) + 1
            if current_batch and current_size + path_size > max_command_chars:
                batches.append(current_batch)
                current_batch = [path]
                current_size = base_size + path_size
                continue
            current_batch.append(path)
            current_size += path_size
        if current_batch:
            batches.append(current_batch)
        return batches or [[]]

    def _limited_patterns(self, query: str, patterns: list[str], *, structured_query: bool) -> list[str]:
        pattern_limit = self._safe_positive_int(
            getattr(self.settings, "retrieval_ripgrep_pattern_limit", 8),
            8,
        )
        normalized_query = normalize_query_text(query).lower()
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for index, pattern in enumerate(patterns):
            normalized = normalize_query_text(pattern)
            if len(normalized) < 2:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            score = self._pattern_quality_score(normalized, normalized_query, structured_query=structured_query)
            if score < 0:
                continue
            scored.append((score, index, normalized))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [pattern for _, _, pattern in scored[:pattern_limit]]

    def _pattern_quality_score(self, pattern: str, normalized_query: str, *, structured_query: bool) -> int:
        lowered = pattern.lower()
        score = 0
        if self._looks_like_exact_fragment(pattern):
            score += 28
        if " " in pattern:
            score += 14
        if len(pattern) >= 8:
            score += 8
        if structured_query and any(token in lowered for token in ("product list", "product name", "equipment list", "material list")):
            score += 28
        if lowered == normalized_query and not self._looks_like_exact_fragment(pattern):
            score -= 14
        if lowered in {"project", "list", "item", "items", "name", "names", "product", "equipment", "material"}:
            score -= 18
        if len(pattern) <= 3 and not self._looks_like_exact_fragment(pattern):
            score -= 10
        return score

    def _prefilter_terms(self, query: str, query_terms: list[str], *, structured_query: bool) -> list[str]:
        scored: list[tuple[int, int, str]] = []
        seen: set[str] = set()
        for index, term in enumerate(query_terms):
            normalized = normalize_query_text(term)
            if len(normalized) < 2:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            score = 0
            if self._looks_like_exact_fragment(normalized):
                score += 30
            if " " in normalized:
                score += 12
            if len(normalized) >= 6:
                score += 8
            if structured_query and key in {"product list", "product name", "equipment list", "equipment name", "material list", "material name"}:
                score += 25
            if key in {"project", "list", "item", "items", "name", "names", "product", "equipment", "material"}:
                score -= 16
            if score >= 0:
                scored.append((score, index, normalized))
        scored.sort(key=lambda item: (-item[0], item[1]))
        terms = [term for _, _, term in scored[:6]]
        if terms:
            return terms
        return [term for term in query_terms[:4] if len(normalize_query_text(term)) >= 2]

    def _looks_like_exact_fragment(self, text: str) -> bool:
        return bool(
            re.search(r"\b[A-Z]{1,8}[A-Z0-9]*[-_/][A-Z0-9]{2,}(?:[-_/][A-Z0-9]{2,})*\b", text, re.IGNORECASE)
            or re.search(r"\b\d+(?:\.\d+){1,3}\b", text)
            or re.search(r"\b\d+\s*[xX]\s*\d+\b", text)
            or re.search(r"(?:第\s*)?\d+\s*页", text)
            or re.search(r"(?:\u7b2c\s*)?\d+\s*\u9875", text)
            or re.search(r"\bpage\s*\d+\b", text, re.IGNORECASE)
        )

    def _effective_candidate_limit(self, *, requested_limit: int, structured_query: bool) -> int:
        try:
            normalized_limit = int(requested_limit)
        except (TypeError, ValueError):
            normalized_limit = DEFAULT_RETRIEVER_TOP_K
        configured_limit = self._safe_positive_int(
            getattr(self.settings, "retrieval_ripgrep_candidate_limit", DEFAULT_RETRIEVER_TOP_K),
            DEFAULT_RETRIEVER_TOP_K,
        )
        if structured_query:
            configured_limit = max(configured_limit, int(configured_limit * 1.5))
        return max(1, min(max(normalized_limit, 1), configured_limit))

    def _candidate_row_limit(self, *, effective_limit: int, structured_query: bool) -> int:
        configured_limit = self._safe_positive_int(
            getattr(self.settings, "retrieval_ripgrep_row_limit", 180),
            180,
        )
        if structured_query:
            configured_limit = max(configured_limit, int(configured_limit * 1.5))
            proportional_limit = max(effective_limit * 10, effective_limit + 40)
        else:
            proportional_limit = max(effective_limit * 8, effective_limit + 32)
        return max(effective_limit, min(configured_limit, proportional_limit))

    def _max_count_per_file(self, *, structured_query: bool) -> int:
        configured_limit = self._safe_positive_int(
            getattr(self.settings, "retrieval_ripgrep_max_count_per_file", 8),
            8,
        )
        if structured_query:
            return max(configured_limit, int(configured_limit * 1.5))
        return configured_limit

    def _safe_positive_int(self, value: object, default: int) -> int:
        try:
            normalized = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            normalized = default
        return max(1, normalized)

    def _log_candidate_shrink(
        self,
        *,
        query: str,
        requested_limit: int,
        effective_limit: int,
        row_limit: int,
        allowed_row_count: int,
        path_count: int,
        pattern_count: int,
        returned_count: int,
        structured_query: bool,
    ) -> None:
        logger.info(
            "Ripgrep候选集收缩: requested_limit=%s effective_limit=%s row_limit=%s allowed_rows=%s path_count=%s pattern_count=%s returned=%s structured=%s query_preview=%s",
            requested_limit,
            effective_limit,
            row_limit,
            allowed_row_count,
            path_count,
            pattern_count,
            returned_count,
            structured_query,
            query[:120],
        )

    def _allowed_page_indexes(
        self,
        mode: str,
        project_id: int | None,
        user: User,
        project_document_policy: ProjectDocumentPolicyService,
        query_terms: list[str],
        *,
        match_document_metadata: bool = False,
        row_limit: int | None = None,
        retrieval_scope: dict[str, object] | None = None,
    ) -> list[tuple[PageIndex, Document, DocumentChunk]]:
        """Load authorized page mirrors that may be searched by ripgrep."""

        result: list[tuple[PageIndex, Document, DocumentChunk]] = []
        allowed_levels = set(self.keyword_policy._allowed_security_levels(user))
        search_filters = self._index_search_filters(mode, project_id)
        search_filters.update(self._scope_search_filters(normalize_retrieval_scope(retrieval_scope)))
        for page_index, document, chunk in self.page_repository.list_searchable_index_rows(
            list(allowed_levels),
            query_terms=query_terms,
            require_text_mirror=True,
            match_document_metadata=match_document_metadata,
            row_limit=row_limit,
            **search_filters,
        ):
            if not self.keyword_policy._scope_allowed(
                document.knowledge_type,
                document.project_id,
                document.knowledge_base_id,
                mode,
                project_id,
                user,
            ):
                continue
            if document.project_id is not None and project_document_policy.project_chat_document_reject_reason(
                document,
                user=user,
                project_id=project_id,
                require_chat_permission=mode == "project_chat",
            ):
                continue
            result.append((page_index, document, chunk))
        return result

    def _parse_rg_match(self, line: str) -> dict | None:
        """Parse a ripgrep JSON match line."""

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if payload.get("type") != "match":
            return None
        data = payload.get("data") or {}
        path = str(Path(data.get("path", {}).get("text", "")).resolve())
        text = data.get("lines", {}).get("text", "").strip()
        if not path or not text:
            return None
        return {"path": path, "line": text}

    def _rank_rows_for_hit(
        self,
        rows: list[tuple[PageIndex, Document, DocumentChunk]],
        hit_line: str,
        query: str,
        query_terms: list[str],
    ) -> list[tuple[PageIndex, Document, DocumentChunk]]:
        """Rank candidate chunk rows for one ripgrep hit."""

        normalized_hit = normalize_query_text(hit_line).lower()
        hit_terms = extract_query_terms(hit_line)
        ranked: list[tuple[float, tuple[PageIndex, Document, DocumentChunk]]] = []
        for row in rows:
            page_index, document, chunk = row
            score = score_text_relevance(chunk.content, query, query_terms)
            score += score_text_relevance(chunk.content, hit_line, hit_terms)
            score += score_text_relevance(self._document_search_text(document, page_index), query, query_terms) * 0.7
            if normalized_hit and normalized_hit in normalize_query_text(chunk.content).lower():
                score += 4.0
            ranked.append((score, row))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [row for _, row in ranked]

    def _to_evidence(
        self,
        page_index: PageIndex,
        document: Document,
        chunk: DocumentChunk,
        hit_line: str,
        query: str,
        query_terms: list[str],
        mode: str,
        project_id: int | None,
        user: User,
        project_document_policy: ProjectDocumentPolicyService,
        structured_list_query: bool,
    ) -> Evidence | None:
        """Convert one match-row mapping into an Evidence object."""

        if chunk.chunk_status != "active":
            return None
        if document.project_id is not None and project_document_policy.project_chat_chunk_reject_reason(
            chunk,
            document,
            user=user,
            project_id=project_id,
        ):
            return None
        if chunk.security_level != page_index.security_level or document.security_level != page_index.security_level:
            return None

        hit_terms = extract_query_terms(hit_line)
        score = 10.0 + score_text_relevance(chunk.content, query, query_terms)
        score += score_text_relevance(chunk.content, hit_line, hit_terms)
        if structured_list_query:
            score += score_text_relevance(self._document_search_text(document, page_index), query, query_terms) * 0.6

        return Evidence(
            score=score,
            source_type=self.keyword_policy._source_type(document.knowledge_type, mode),
            knowledge_base_id=document.knowledge_base_id,
            project_id=document.project_id,
            document_id=document.id,
            chunk_id=chunk.id,
            drawing_no=page_index.drawing_no or document.drawing_no,
            file_name=document.file_name,
            page_number=page_index.page_no,
            content=chunk.content,
            retriever=self.name,
            metadata=self.keyword_policy._evidence_metadata(
                document,
                chunk,
                {
                    "hit_line": hit_line,
                    "page_index_id": page_index.id,
                    "page_index_security_level": page_index.security_level,
                    "structured_list_query": structured_list_query,
                },
            ),
        )

    def _document_search_text(self, document: Document, page_index: PageIndex) -> str:
        return " ".join(
            filter(
                None,
                [
                    document.file_name,
                    getattr(document, "document_name", None),
                    getattr(document, "drawing_name", None),
                    page_index.drawing_no,
                    document.drawing_no,
                    getattr(document, "document_type", None),
                ],
            )
        )

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
