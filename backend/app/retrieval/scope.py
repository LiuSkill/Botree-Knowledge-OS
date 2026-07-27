"""Helpers for narrowing retry retrieval to a small evidence-derived scope."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def positive_int_values(values: object, *, limit: int = 50) -> list[int]:
    """Return ordered, de-duplicated positive integer values."""

    result: list[int] = []
    seen: set[int] = set()
    for item in _iter_values(values):
        normalized = _positive_int(item)
        if normalized is None or normalized in seen:
            continue
        result.append(normalized)
        seen.add(normalized)
        if len(result) >= limit:
            break
    return result


def normalize_page_numbers_by_document(values: object, *, limit_docs: int = 10, limit_pages_per_doc: int = 24) -> dict[int, list[int]]:
    """Normalize a document -> page numbers mapping for SQL filters."""

    if not isinstance(values, dict):
        return {}
    result: dict[int, list[int]] = {}
    for raw_document_id, raw_pages in values.items():
        document_id = _positive_int(raw_document_id)
        if document_id is None:
            continue
        pages = positive_int_values(raw_pages, limit=limit_pages_per_doc)
        if not pages:
            continue
        result[document_id] = pages
        if len(result) >= limit_docs:
            break
    return result


def normalize_retrieval_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize optional retry scope so retrievers can consume it safely."""

    if not scope:
        return {}
    document_ids = positive_int_values(scope.get("document_ids"), limit=5000)
    chunk_ids = positive_int_values(scope.get("chunk_ids"), limit=80)
    page_numbers_by_document = normalize_page_numbers_by_document(scope.get("page_numbers_by_document"))
    for document_id in page_numbers_by_document:
        if document_id not in document_ids:
            document_ids.append(document_id)

    normalized: dict[str, Any] = {}
    if document_ids:
        normalized["document_ids"] = document_ids
    if chunk_ids:
        normalized["chunk_ids"] = chunk_ids
    if page_numbers_by_document:
        normalized["page_numbers_by_document"] = page_numbers_by_document
    file_names = [str(item).strip() for item in _iter_values(scope.get("file_names")) if str(item).strip()]
    if file_names:
        normalized["file_names"] = list(dict.fromkeys(file_names))[:10]
    for key in ("snapshot_id", "verified", "verified_at", "expires_at"):
        if key in scope:
            normalized[key] = scope[key]
    publication_tokens = [
        str(item).strip() for item in _iter_values(scope.get("publication_tokens")) if str(item).strip()
    ]
    if publication_tokens:
        normalized["publication_tokens"] = list(dict.fromkeys(publication_tokens))[:5000]
    return normalized


def retrieval_scope_has_filters(scope: dict[str, Any] | None) -> bool:
    """Whether a normalized scope contains any hard retrieval filter."""

    normalized = normalize_retrieval_scope(scope)
    return bool(
        normalized.get("document_ids")
        or normalized.get("chunk_ids")
        or normalized.get("page_numbers_by_document")
    )


def constrain_verified_scope(
    verified_scope: dict[str, Any],
    requested_scope: dict[str, Any] | None,
) -> dict[str, Any]:
    """在不更换请求级安全快照的前提下进一步收窄检索范围。"""

    verified = normalize_retrieval_scope(verified_scope)
    requested = normalize_retrieval_scope(requested_scope)
    verified_ids = set(verified.get("document_ids", []))
    requested_ids = set(requested.get("document_ids", []))
    result = {**verified, **requested}
    result["document_ids"] = sorted(verified_ids & requested_ids) if requested_ids else sorted(verified_ids)
    verified_tokens = set(verified.get("publication_tokens", []))
    requested_tokens = set(requested.get("publication_tokens", []))
    if verified_tokens:
        result["publication_tokens"] = sorted(
            verified_tokens & requested_tokens if requested_tokens else verified_tokens
        )
    return normalize_retrieval_scope(result)


def _iter_values(values: object) -> Iterable[object]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        return [values]
    if isinstance(values, dict):
        return values.values()
    if isinstance(values, Iterable):
        return values
    return [values]


def _positive_int(value: object) -> int | None:
    try:
        normalized = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None
