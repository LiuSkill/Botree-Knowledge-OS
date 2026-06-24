"""Keyword retrieval adapters reserved for BEIR evaluation."""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from eval.beir.types import BeirCorpus, SearchHit

logger = logging.getLogger(__name__)

TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_]+")


class KeywordAdapter:
    """Base keyword retrieval adapter interface."""

    name = "keyword"

    def index(self, corpus: BeirCorpus) -> None:
        """Build or refresh the keyword index."""

        raise NotImplementedError

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        """Return TopK keyword hits."""

        raise NotImplementedError


class BM25KeywordAdapter(KeywordAdapter):
    """Small in-memory BM25 adapter for BEIR smoke and baseline evaluation."""

    name = "bm25"

    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self.doc_ids: list[str] = []
        self.doc_tokens: list[list[str]] = []
        self.doc_lengths: list[int] = []
        self.term_frequencies: list[Counter[str]] = []
        self.document_frequency: Counter[str] = Counter()
        self.avg_doc_length = 0.0
        self.documents: dict[str, dict[str, str]] = {}

    def index(self, corpus: BeirCorpus) -> None:
        """Build BM25 statistics from the BEIR corpus."""

        self.doc_ids = []
        self.doc_tokens = []
        self.doc_lengths = []
        self.term_frequencies = []
        self.document_frequency = Counter()
        self.documents = dict(corpus)

        for doc_id, document in corpus.items():
            tokens = tokenize(_document_text(document))
            term_frequency = Counter(tokens)
            self.doc_ids.append(doc_id)
            self.doc_tokens.append(tokens)
            self.doc_lengths.append(len(tokens))
            self.term_frequencies.append(term_frequency)
            self.document_frequency.update(term_frequency.keys())

        total_length = sum(self.doc_lengths)
        self.avg_doc_length = total_length / len(self.doc_lengths) if self.doc_lengths else 0.0
        logger.info("BM25索引构建完成: documents=%s avg_doc_length=%.2f", len(self.doc_ids), self.avg_doc_length)

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        """Score all documents with BM25 and return TopK."""

        query_terms = tokenize(query)
        if not query_terms or not self.doc_ids:
            return []

        scores: list[tuple[float, str]] = []
        total_docs = len(self.doc_ids)
        for index, doc_id in enumerate(self.doc_ids):
            score = 0.0
            term_frequency = self.term_frequencies[index]
            doc_length = self.doc_lengths[index]
            for term in query_terms:
                frequency = term_frequency.get(term, 0)
                if frequency <= 0:
                    continue
                doc_frequency = self.document_frequency.get(term, 0)
                idf = math.log(1.0 + (total_docs - doc_frequency + 0.5) / (doc_frequency + 0.5))
                denominator = frequency + self.k1 * (1.0 - self.b + self.b * doc_length / max(self.avg_doc_length, 1.0))
                score += idf * frequency * (self.k1 + 1.0) / denominator
            if score > 0:
                scores.append((score, doc_id))

        scores.sort(key=lambda item: item[0], reverse=True)
        return [
            SearchHit(
                doc_id=doc_id,
                score=float(score),
                rank=rank,
                retriever=self.name,
                title=self.documents.get(doc_id, {}).get("title", ""),
                text=self.documents.get(doc_id, {}).get("text", ""),
            )
            for rank, (score, doc_id) in enumerate(scores[:top_k], start=1)
        ]


class RipgrepKeywordAdapter(KeywordAdapter):
    """ripgrep-backed exact term adapter for future large local text mirrors."""

    name = "ripgrep"

    def __init__(self, index_dir: Path, ripgrep_binary: str = "rg") -> None:
        self.index_dir = index_dir
        self.ripgrep_binary = ripgrep_binary
        self.path_to_doc_id: dict[str, str] = {}
        self.documents: dict[str, dict[str, str]] = {}

    def index(self, corpus: BeirCorpus) -> None:
        """Create a simple one-file-per-document text mirror for rg."""

        self.index_dir.mkdir(parents=True, exist_ok=True)
        self.documents = dict(corpus)
        manifest: dict[str, str] = {}
        for doc_id, document in corpus.items():
            path = self.index_dir / f"{_safe_file_name(doc_id)}.txt"
            path.write_text(_document_text(document), encoding="utf-8")
            resolved = str(path.resolve())
            manifest[resolved] = doc_id
        (self.index_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        self.path_to_doc_id = manifest
        logger.info("ripgrep文本镜像构建完成: documents=%s dir=%s", len(manifest), self.index_dir)

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        """Run rg with token-level fixed-string patterns."""

        patterns = tokenize(query)
        if not patterns or not self.path_to_doc_id:
            return []
        pattern_args = [value for pattern in patterns for value in ("-e", pattern)]
        completed = subprocess.run(
            [self.ripgrep_binary, "--json", "--fixed-strings", "--ignore-case", *pattern_args, *self.path_to_doc_id.keys()],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
        )
        doc_scores: dict[str, float] = defaultdict(float)
        for line in completed.stdout.splitlines():
            hit = _parse_rg_json(line)
            if not hit:
                continue
            doc_id = self.path_to_doc_id.get(hit["path"])
            if doc_id:
                doc_scores[doc_id] += 1.0
        ranked = sorted(doc_scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        return [
            SearchHit(
                doc_id=doc_id,
                score=score,
                rank=rank,
                retriever=self.name,
                title=self.documents.get(doc_id, {}).get("title", ""),
                text=self.documents.get(doc_id, {}).get("text", ""),
            )
            for rank, (doc_id, score) in enumerate(ranked, start=1)
        ]


def make_keyword_adapter(adapter_name: str, index_dir: Path, ripgrep_binary: str = "rg") -> KeywordAdapter:
    """Factory for keyword adapters."""

    normalized = adapter_name.lower()
    if normalized == "bm25":
        return BM25KeywordAdapter()
    if normalized == "ripgrep":
        return RipgrepKeywordAdapter(index_dir=index_dir, ripgrep_binary=ripgrep_binary)
    raise ValueError(f"不支持的 keyword adapter: {adapter_name}")


def tokenize(text: str) -> list[str]:
    """Tokenize BEIR English text for lightweight keyword scoring."""

    return TOKEN_PATTERN.findall((text or "").lower())


def _document_text(document: dict[str, str]) -> str:
    """Return title + body text for keyword indexing."""

    title = (document.get("title") or "").strip()
    body = (document.get("text") or "").strip()
    return f"{title}\n{body}".strip()


def _safe_file_name(doc_id: str) -> str:
    """Create a Windows-safe mirror file name."""

    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", doc_id)
    return safe[:120] or "doc"


def _parse_rg_json(line: str) -> dict[str, str] | None:
    """Parse a ripgrep JSON match event."""

    try:
        payload = json.loads(line)
    except json.JSONDecodeError:
        return None
    if payload.get("type") != "match":
        return None
    data = payload.get("data") or {}
    path = str(Path(data.get("path", {}).get("text", "")).resolve())
    return {"path": path} if path else None
