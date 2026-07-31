"""ChunkBuilder 输入页载荷适配。"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from typing import Any


def build_chunk_page_payloads_from_page_models(
    pages: Iterable[object],
    blocks: Iterable[object],
    *,
    admitted_page_numbers: set[int] | None = None,
) -> list[dict[str, Any]]:
    """将落库页/块模型恢复为结构化 chunk 输入。"""

    clean_blocks_by_page = _group_kept_blocks_by_page(blocks)
    payloads: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(getattr(page, "page_no", 0) or 0)
        if admitted_page_numbers is not None and page_no not in admitted_page_numbers:
            continue
        corrected_text = str(getattr(page, "corrected_text", None) or "").strip()
        payload: dict[str, Any] = {
            "page_number": page_no,
            "page_title": getattr(page, "page_title", None),
            "clean_content": corrected_text or str(getattr(page, "clean_content", None) or getattr(page, "page_text", None) or ""),
        }
        if not corrected_text:
            page_id = int(getattr(page, "id", 0) or 0)
            clean_blocks = clean_blocks_by_page.get(page_id)
            if clean_blocks:
                payload["clean_blocks"] = clean_blocks
        payloads.append(payload)
    return payloads


def _group_kept_blocks_by_page(blocks: Iterable[object]) -> dict[int, list[dict[str, Any]]]:
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    sorted_blocks = sorted(
        blocks,
        key=lambda item: (
            int(getattr(item, "page_id", 0) or 0),
            int(getattr(item, "block_index", 0) or 0),
        ),
    )
    for block in sorted_blocks:
        if str(getattr(block, "filter_status", "kept") or "kept").lower() == "filtered":
            continue
        page_id = int(getattr(block, "page_id", 0) or 0)
        payload = _block_payload(block)
        if page_id <= 0 or payload is None:
            continue
        grouped[page_id].append(payload)
    return grouped


def _block_payload(block: object) -> dict[str, Any] | None:
    metadata = _json_dict(getattr(block, "metadata_json", None))
    clean_text = str(getattr(block, "clean_text", None) or "")
    raw_text = str(getattr(block, "text", None) or "")
    block_type = str(getattr(block, "block_type", None) or "text")
    if not clean_text and not raw_text and not metadata and block_type != "table":
        return None
    return {
        "block_index": int(getattr(block, "block_index", 0) or 0),
        "block_type": block_type,
        "clean_text": clean_text,
        "text": raw_text,
        "metadata": metadata or {},
    }


def _json_dict(value: object) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None
