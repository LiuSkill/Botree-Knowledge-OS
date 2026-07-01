"""
Visual Evidence Service

负责把命中的页级检索证据增强为可供视觉模型分析和前端展示的图片证据。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document_asset import DocumentAsset
from app.models.page_index import DocumentPage, PageIndex
from app.repositories.document_asset_repository import DocumentAssetRepository
from app.repositories.page_index_repository import PageIndexRepository
from app.retrieval.schemas import Evidence, EvidenceAsset
from app.services.document_asset_service import ASSET_TYPE_BLOCK_IMAGE, ASSET_TYPE_PAGE_PREVIEW

logger = logging.getLogger(__name__)

VISUAL_ASSET_TYPES = {ASSET_TYPE_PAGE_PREVIEW, ASSET_TYPE_BLOCK_IMAGE}
VISUAL_QUERY_HINTS = (
    "图",
    "图片",
    "图纸",
    "流程",
    "pid",
    "p&id",
    "diagram",
    "drawing",
    "flow",
)
ASSET_MARKDOWN_METADATA_KEYS = (
    "original_candidate_value",
    "resolved_local_path",
    "local_path",
    "inline_payload_key",
    "remote_url",
    "image_path",
    "img_path",
    "path",
    "saved_path",
    "file_name",
    "image_name",
    "img_name",
)


class VisualEvidenceService:
    """
    视觉证据增强服务。

    业务规则：
    - 仅在图纸号、PID/P&ID、流程图等视觉相关问题中尝试挂图。
    - 优先选择命中页的 page_preview；没有页面预览时回退到同页最大的 block_image。
    - 只向后续链路传递资产 ID 和安全展示元数据，图片内容由 LLMService 临时读取。
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.page_repository = PageIndexRepository(db)
        self.asset_repository = DocumentAssetRepository(db)

    def enrich(
        self,
        question: str,
        evidences: list[Evidence],
        query_features: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        """为检索证据挂载命中页图片资产。"""

        if not evidences or not self._should_enrich(question, query_features or {}):
            return evidences

        started_at = time.perf_counter()
        max_images = max(0, int(self.settings.vision_llm_max_images))
        if max_images <= 0:
            return evidences

        selected_count = 0
        seen_asset_ids: set[int] = set()
        for evidence in evidences:
            if selected_count >= max_images:
                break
            page_context = self._resolve_page_context(evidence)
            if page_context is None:
                continue
            page, version_no = page_context
            candidates = self.asset_repository.list_ready_page_image_assets(
                document_id=evidence.document_id,
                version_no=version_no,
                page_id=page.id,
                asset_types=VISUAL_ASSET_TYPES,
            )
            selected_assets = self._select_assets(candidates, max_images - selected_count, seen_asset_ids)
            if not selected_assets:
                continue
            evidence.assets.extend(self._to_evidence_asset(asset, page.page_no) for asset in selected_assets)
            seen_asset_ids.update(asset.id for asset in selected_assets)
            selected_count += len(selected_assets)

        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "视觉证据增强完成: evidence_count=%s visual_asset_count=%s elapsed_ms=%s",
            len(evidences),
            selected_count,
            elapsed_ms,
        )
        return evidences

    def _should_enrich(self, question: str, query_features: dict[str, Any]) -> bool:
        """判断本次问题是否需要尝试挂载图片证据。"""

        if query_features.get("has_doc_code"):
            return True
        lowered = question.lower()
        return any(hint in lowered for hint in VISUAL_QUERY_HINTS)

    def _resolve_page_context(self, evidence: Evidence) -> tuple[DocumentPage, int] | None:
        """从 Evidence 的 PageIndex 元数据或页码回溯页面和版本。"""

        page_index = self._resolve_page_index(evidence)
        if page_index is not None:
            page = self.db.get(DocumentPage, page_index.page_id)
            if page is not None:
                return page, page_index.version_no

        if evidence.page_number is None:
            return None
        page = self.page_repository.get_page(evidence.document_id, evidence.page_number)
        if page is None:
            return None
        return page, page.version_no

    def _resolve_page_index(self, evidence: Evidence) -> PageIndex | None:
        """从证据元数据中读取 PageIndex ID。"""

        raw_page_index_id = evidence.metadata.get("page_index_id")
        if raw_page_index_id is None:
            return None
        try:
            page_index_id = int(raw_page_index_id)
        except (TypeError, ValueError):
            return None
        return self.page_repository.get_page_index(page_index_id)

    def _select_assets(
        self,
        candidates: list[DocumentAsset],
        remaining: int,
        seen_asset_ids: set[int],
    ) -> list[DocumentAsset]:
        """按页面预览优先、图块大小兜底的策略选图。"""

        max_bytes = max(0, int(self.settings.vision_llm_max_image_bytes))
        available = [
            asset
            for asset in candidates
            if asset.id not in seen_asset_ids and (max_bytes <= 0 or int(asset.file_size or 0) <= max_bytes)
        ]
        if not available or remaining <= 0:
            return []

        page_previews = [asset for asset in available if asset.asset_type == ASSET_TYPE_PAGE_PREVIEW]
        block_images = sorted(
            [asset for asset in available if asset.asset_type == ASSET_TYPE_BLOCK_IMAGE],
            key=lambda item: item.file_size,
            reverse=True,
        )
        selected: list[DocumentAsset] = []
        if page_previews:
            selected.append(page_previews[0])
            selected.extend(block_images[: max(0, remaining - 1)])
            return selected[:remaining]
        return block_images[:remaining]

    def _to_evidence_asset(self, asset: DocumentAsset, page_no: int | None) -> EvidenceAsset:
        """转换为可返回前端和可传递给 LLMService 的资产元数据。"""

        return EvidenceAsset(
            asset_id=asset.id,
            asset_type=asset.asset_type,
            url=f"/api/documents/assets/{asset.id}",
            mime_type=asset.mime_type,
            file_name=asset.file_name,
            file_size=asset.file_size,
            page_number=page_no,
            block_id=asset.block_id,
            metadata=self._build_asset_metadata(asset),
        )

    def _build_asset_metadata(self, asset: DocumentAsset) -> dict[str, Any]:
        """构建前端 Markdown 图片匹配所需的安全资产元数据。"""

        metadata: dict[str, Any] = {"document_id": asset.document_id, "version_no": asset.version_no}
        if not asset.metadata_json:
            return metadata
        try:
            parsed = json.loads(asset.metadata_json)
        except json.JSONDecodeError:
            logger.warning("视觉证据资产元数据解析失败: asset_id=%s", asset.id)
            return metadata
        if not isinstance(parsed, dict):
            return metadata
        for key in ASSET_MARKDOWN_METADATA_KEYS:
            value = parsed.get(key)
            if isinstance(value, (str, int, float, list)):
                metadata[key] = value
        return metadata
