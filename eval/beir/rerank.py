"""BEIR reranking adapter using the existing project reranker service."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from eval.beir.types import BeirCorpus, SearchHit

logger = logging.getLogger(__name__)


@dataclass
class RerankResult:
    """Structured rerank output used by reports and diagnostics."""

    hits: list[SearchHit]
    debug_rows: list[dict[str, Any]]
    input_samples: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    model_name: str = ""
    model_provider: str = ""
    model_configured: bool = False
    model_loaded: bool = False
    score_order: str = "desc"
    candidate_count: int = 0


class BeirReranker:
    """Adapt BEIR doc hits to the project's Evidence-based reranker."""

    def __init__(
        self,
        db: Session | None,
        score_order: str = "desc",
        *,
        rerank_top_k: int = 100,
        require_real_reranker: bool = True,
        allow_fallback: bool = False,
    ) -> None:
        from app.services.reranker_service import RerankerService

        self.db = db
        self.reranker = RerankerService(db)
        self.score_order = _normalize_score_order(score_order)
        self.rerank_top_k = max(1, int(rerank_top_k))
        self.require_real_reranker = bool(require_real_reranker)
        self.allow_fallback = bool(allow_fallback)
        self.model_name, self.model_provider, self.model_configured, self.model_loaded = self._resolve_model_config(db)
        self.base_warnings = self._build_base_warnings()
        if self.require_real_reranker and not self.model_loaded:
            raise RuntimeError(
                "RERANKER_MODEL_UNCONFIGURED: require_real_reranker=true but no enabled local reranker model is available."
            )

    def rerank(
        self,
        query_id: str,
        query: str,
        hits: list[SearchHit],
        corpus: BeirCorpus,
        expected_doc_ids: set[str],
        limit: int,
    ) -> RerankResult:
        """Rerank the candidate Top100 hits and return BEIR doc_id hits."""

        from app.retrieval.schemas import Evidence

        candidate_hits = hits[: self.rerank_top_k]
        logger.info(
            "stage=rerank status=started reranker_enabled=true reranker_model_name=%s reranker_model_provider=%s "
            "reranker_model_configured=%s reranker_model_loaded=%s reranker_score_order=%s query_id=%s rerank_candidate_count=%s",
            self.model_name,
            self.model_provider or "-",
            self.model_configured,
            self.model_loaded,
            self.score_order,
            query_id,
            len(candidate_hits),
        )
        evidences: list[Evidence] = []
        input_samples: list[dict[str, Any]] = []
        warnings = list(self.base_warnings)
        for index, hit in enumerate(candidate_hits, start=1):
            content = _candidate_text(hit, corpus)
            if not content:
                warnings.append(f"RERANK_INPUT_EMPTY_TEXT: query_id={query_id} doc_id={hit.doc_id} old_rank={index}")
            if index <= 3:
                input_samples.append(
                    {
                        "query_text": query,
                        "candidate_doc_id": hit.doc_id,
                        "old_rank": index,
                        "old_score": hit.score,
                        "candidate_title": _clip(_candidate_title(hit, corpus), 500),
                        "candidate_text_preview": _clip(content, 2000),
                    }
                )
            if not content:
                continue
            evidences.append(
                Evidence(
                    score=hit.score,
                    source_type="beir",
                    knowledge_base_id=0,
                    project_id=None,
                    document_id=index,
                    chunk_id=index,
                    drawing_no=None,
                    file_name=hit.doc_id,
                    page_number=None,
                    content=content,
                    retriever=hit.retriever,
                    metadata={"beir_doc_id": hit.doc_id, "beir_raw_rank": index, "beir_raw_score": hit.score},
                )
            )

        reranked = self.reranker.rerank(
            query,
            evidences,
            len(evidences),
            require_real_model=self.require_real_reranker,
            allow_fallback=self.allow_fallback,
            score_order=self.score_order,
        )
        runtime = getattr(self.reranker, "last_runtime", {}) or {}
        self.model_name = str(runtime.get("model_name") or self.model_name)
        self.model_provider = str(runtime.get("provider") or self.model_provider)
        self.model_loaded = bool(runtime.get("model_loaded", self.model_loaded))
        if runtime.get("fallback_used") and not self.allow_fallback:
            raise RuntimeError("RERANKER_FALLBACK_FORBIDDEN: deterministic fallback was used while allow_reranker_fallback=false")
        reranked = sorted(reranked, key=lambda evidence: float(evidence.score), reverse=self.score_order == "desc")
        ranked_evidences = reranked[:limit]
        results: list[SearchHit] = []
        debug_rows: list[dict[str, Any]] = []
        for rank, evidence in enumerate(reranked, start=1):
            doc_id = str(evidence.metadata["beir_doc_id"])
            rerank_score = float(evidence.metadata.get("rerank_score", evidence.score))
            old_rank = int(evidence.metadata.get("beir_raw_rank") or 0)
            is_qrels_hit = doc_id in expected_doc_ids
            logger.debug(
                "stage=rerank action=rank_changed query_id=%s doc_id=%s old_rank=%s new_rank=%s reranker_score=%s is_qrels_hit=%s",
                query_id,
                doc_id,
                old_rank,
                rank,
                rerank_score,
                is_qrels_hit,
            )
            debug_rows.append(
                {
                    "query_id": query_id,
                    "doc_id": doc_id,
                    "old_rank": old_rank,
                    "new_rank": rank,
                    "rank_delta": old_rank - rank if old_rank else "",
                    "old_score": float(evidence.metadata.get("beir_raw_score", 0.0)),
                    "reranker_score": rerank_score,
                    "is_qrels_hit": is_qrels_hit,
                    "source_retriever": evidence.retriever,
                    "score_order": self.score_order,
                    "reranker_model_name": self.model_name,
                    "candidate_doc_text_len": len(evidence.content or ""),
                }
            )
            if rank > limit:
                continue
            beir_score = float(len(ranked_evidences) - rank + 1)
            results.append(
                SearchHit(
                    doc_id=doc_id,
                    score=beir_score,
                    rank=rank,
                    retriever=f"{evidence.retriever}+rerank",
                    metadata={
                        "raw_rank": evidence.metadata.get("beir_raw_rank"),
                        "raw_score": evidence.metadata.get("beir_raw_score"),
                        "rerank_score": rerank_score,
                        "reranker_model_name": self.model_name,
                        "reranker_score_order": self.score_order,
                    },
                    title=_candidate_title_from_corpus(doc_id, corpus),
                    text=_candidate_body_from_corpus(doc_id, corpus),
                )
            )
        return RerankResult(
            hits=results,
            debug_rows=debug_rows,
            input_samples=input_samples,
            warnings=warnings,
            model_name=self.model_name,
            model_provider=self.model_provider,
            model_configured=self.model_configured,
            model_loaded=self.model_loaded,
            score_order=self.score_order,
            candidate_count=len(candidate_hits),
        )

    def _resolve_model_config(self, db: Session | None) -> tuple[str, str, bool, bool]:
        """Read the default reranker model config when one exists."""

        from app.services.reranker_service import RerankerService

        service = RerankerService(db)
        try:
            runtime_config = service.ensure_real_model()
            model_name = str(getattr(runtime_config, "model_name", "") or getattr(runtime_config, "api_base", "") or "local_reranker")
            return model_name, str(getattr(runtime_config, "provider", "") or "local"), True, True
        except Exception as exc:
            logger.warning("stage=rerank action=real_reranker_config_unavailable error=%s", exc)
            if db is None:
                return "deterministic_fallback", "", False, False
        try:
            from app.repositories.model_repository import ModelConfigRepository

            config = ModelConfigRepository(db).get_default("reranker")
        except Exception as exc:
            logger.warning("stage=rerank action=load_model_config_failed error=%s", exc)
            return "deterministic_fallback", "", False, False
        if config is None:
            return "deterministic_fallback", "", False, False
        return str(config.model_name or "unknown_reranker"), str(config.provider or ""), True, False

    def _build_base_warnings(self) -> list[str]:
        """Return non-silent warnings for fallback or unverified reranker runtime."""

        if not self.model_configured:
            return [
                "RERANKER_MODEL_UNCONFIGURED: no enabled default model_config with model_type='reranker'; "
                "BEIR cannot use a real reranker unless allow_reranker_fallback=true."
            ]
        if not self.model_loaded:
            return [f"RERANKER_MODEL_NOT_LOADED: default reranker '{self.model_name}' is configured but failed validation."]
        return []


def _document_text(document: dict[str, str]) -> str:
    """Return title + text for reranker scoring."""

    title = (document.get("title") or "").strip()
    body = (document.get("text") or "").strip()
    return f"{title}\n{body}".strip()


def _candidate_text(hit: SearchHit, corpus: BeirCorpus) -> str:
    """Build reranker input text from title + text, never from doc_id or metadata."""

    corpus_text = _document_text(corpus.get(hit.doc_id, {}))
    if corpus_text:
        return corpus_text
    return f"{hit.title.strip()}\n{hit.text.strip()}".strip()


def _candidate_title(hit: SearchHit, corpus: BeirCorpus) -> str:
    """Return the BEIR title used in rerank diagnostics."""

    return _candidate_title_from_corpus(hit.doc_id, corpus) or hit.title.strip()


def _candidate_title_from_corpus(doc_id: str, corpus: BeirCorpus) -> str:
    return (corpus.get(doc_id, {}).get("title") or "").strip()


def _candidate_body_from_corpus(doc_id: str, corpus: BeirCorpus) -> str:
    return (corpus.get(doc_id, {}).get("text") or "").strip()


def _normalize_score_order(score_order: str) -> str:
    normalized = score_order.strip().lower()
    if normalized not in {"desc", "asc"}:
        raise ValueError(f"Unsupported reranker_score_order: {score_order}")
    return normalized


def _clip(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...<truncated>"
