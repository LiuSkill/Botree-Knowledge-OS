"""独立视觉候选召回通道。"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document
from app.models.document_asset import DocumentAsset
from app.models.page_index import DocumentPageBlock
from app.models.user import User
from app.retrieval.base import BaseRetriever, DEFAULT_RETRIEVER_TOP_K
from app.retrieval.schemas import Evidence, EvidenceAsset

logger = logging.getLogger(__name__)


class VisualQueryEmbedder(Protocol):
    def embed_queries(self, queries: list[str]) -> list[list[float]]: ...


class VisualSearchIndex(Protocol):
    def search(self, query_vector: list[float], limit: int, expr: str | None = None) -> list[dict[str, Any]]: ...


class VisualRetriever(BaseRetriever):
    """无需文本 Chunk，直接从整页和局部区域向量中召回证据。"""

    name = "visual"

    def __init__(self, db: Session, embedding_service: VisualQueryEmbedder, indexer: VisualSearchIndex) -> None:
        self.db = db
        self.embedding_service = embedding_service
        self.indexer = indexer
        self.settings = get_settings()

    def search(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = DEFAULT_RETRIEVER_TOP_K,
        *,
        retrieval_scope: dict[str, Any] | None = None,
    ) -> list[Evidence]:
        del mode, project_id, user
        # 已验证范围快照缺失时必须 fail closed，索引内复制的权限字段不能独立放行。
        if retrieval_scope is None:
            logger.warning("视觉召回拒绝执行: verified retrieval_scope missing")
            return []
        allowed_document_ids = self._allowed_document_ids(retrieval_scope)
        publication_tokens = self._publication_tokens(retrieval_scope)
        if not allowed_document_ids or not publication_tokens:
            return []
        expr = self._document_expr(allowed_document_ids, publication_tokens, self.settings.visual_index_generation)
        query_vector = self.embedding_service.embed_queries([query])[0]
        hits = self.indexer.search(query_vector, limit * 3, expr=expr)
        evidences: list[Evidence] = []
        for hit in hits:
            document_id = int(hit["document_id"])
            if allowed_document_ids and document_id not in allowed_document_ids:
                continue
            document = self.db.get(Document, document_id)
            asset = self.db.get(DocumentAsset, int(hit["asset_id"]))
            if not self._is_current_asset(document, asset, int(hit["version_no"])):
                continue
            page_no = int(hit["page_no"])
            evidences.append(self._to_evidence(document, asset, hit, page_no))
            if len(evidences) >= limit:
                break
        logger.info(
            "视觉召回完成: hit_count=%s evidence_count=%s scoped_documents=%s query_preview=%s",
            len(hits),
            len(evidences),
            len(allowed_document_ids),
            query[:120],
        )
        return evidences

    @staticmethod
    def _allowed_document_ids(retrieval_scope: dict[str, Any] | None) -> set[int]:
        if retrieval_scope is None:
            return set()
        return {int(value) for value in retrieval_scope.get("document_ids", [])}

    @staticmethod
    def _publication_tokens(retrieval_scope: dict[str, Any]) -> set[str]:
        return {str(value) for value in retrieval_scope.get("publication_tokens", []) if str(value)}

    @staticmethod
    def _document_expr(document_ids: set[int], publication_tokens: set[str], index_generation: str) -> str | None:
        if not document_ids:
            return None
        safe_generation = index_generation.replace("\\", "\\\\").replace('"', '\\"')
        safe_tokens = [value.replace("\\", "\\\\").replace('"', '\\"') for value in sorted(publication_tokens)]
        return (
            "document_id in ["
            + ", ".join(str(value) for value in sorted(document_ids))
            + f'] and index_generation == "{safe_generation}" and publication_token in ['
            + ", ".join(f'"{value}"' for value in safe_tokens)
            + "]"
        )

    @staticmethod
    def _is_current_asset(document: Document | None, asset: DocumentAsset | None, version_no: int) -> bool:
        return bool(
            document
            and asset
            and not document.is_deleted
            and document.index_status == "indexed"
            and document.version_no == version_no
            and asset.document_id == document.id
            and asset.version_no == version_no
            and asset.status == "ready"
        )

    def _to_evidence(
        self,
        document: Document,
        asset: DocumentAsset,
        hit: dict[str, Any],
        page_no: int,
    ) -> Evidence:
        block_id = int(hit.get("block_id") or 0) or None
        block = self.db.get(DocumentPageBlock, block_id) if block_id else None
        bbox = self._json_value(block.bbox_json) if block else None
        asset_metadata = self._json_value(asset.metadata_json)
        visual_context = self._visual_context(asset_metadata, document.file_name)
        return Evidence(
            score=float(hit["score"]),
            source_type="pdf_visual",
            knowledge_base_id=document.knowledge_base_id,
            project_id=document.project_id,
            document_id=document.id,
            chunk_id=-asset.id,
            drawing_no=document.drawing_no,
            file_name=document.file_name,
            page_number=page_no,
            content=f"视觉证据：{document.file_name} 第{page_no}页",
            retriever=self.name,
            metadata={
                "asset_id": asset.id,
                "asset_type": asset.asset_type,
                "page_id": hit.get("page_id"),
                "block_id": block_id,
                "bbox": bbox,
                "previous_block_id": int(hit.get("previous_block_id") or 0) or None,
                "next_block_id": int(hit.get("next_block_id") or 0) or None,
                "index_generation": hit.get("index_generation"),
                "version_no": document.version_no,
                "security_level": document.security_level,
                "visual_context": visual_context,
            },
            assets=[
                EvidenceAsset(
                    asset_id=asset.id,
                    asset_type=asset.asset_type,
                    url=f"/api/documents/assets/{asset.id}",
                    mime_type=asset.mime_type,
                    file_name=asset.file_name,
                    file_size=asset.file_size,
                    page_number=page_no,
                    block_id=asset.block_id,
                    metadata={
                        "document_id": document.id,
                        "version_no": document.version_no,
                        "bbox": bbox,
                        "previous_block_id": int(hit.get("previous_block_id") or 0) or None,
                        "next_block_id": int(hit.get("next_block_id") or 0) or None,
                        "visual_context": visual_context,
                    },
                )
            ],
        )

    @staticmethod
    def _visual_context(metadata: object | None, default_file_name: str) -> dict[str, Any]:
        if not isinstance(metadata, dict):
            return {"source_file_name": default_file_name}
        visual_admission = metadata.get("visual_admission") if isinstance(metadata.get("visual_admission"), dict) else {}
        source_file_name = str(
            visual_admission.get("source_file_name") or metadata.get("source_file_name") or default_file_name
        )
        result: dict[str, Any] = {"source_file_name": source_file_name}
        for key in ("page_title", "figure_title", "context_text", "category", "priority_score", "status"):
            value = visual_admission.get(key)
            if value not in (None, "", []):
                result[key] = value
        adjacent_texts = visual_admission.get("adjacent_texts")
        if isinstance(adjacent_texts, list) and adjacent_texts:
            result["adjacent_texts"] = adjacent_texts
        return result

    @staticmethod
    def _json_value(value: str | None) -> object | None:
        if not value:
            return None
        try:
            import json

            return json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return None
