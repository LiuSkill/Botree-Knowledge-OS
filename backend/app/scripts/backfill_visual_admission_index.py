"""回填因视觉准入规则过严而漏进视觉索引的图片。"""

from __future__ import annotations

import argparse
import json
import logging
import time

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.knowledge.indexing.visual_index_service import VisualIndexService
from app.knowledge.indexing.visual_milvus_indexer import VisualMilvusIndexer
from app.models.document import Document
from app.models.page_index import DocumentPage, DocumentPageBlock, IndexPublicationManifest
from app.repositories.document_asset_repository import DocumentAssetRepository
from app.services.index_admission_service import IndexAdmissionService
from app.services.index_pipeline_service import IndexPipelineService
from app.services.visual_embedding_service import VisualEmbeddingService

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="回填视觉准入放宽后新增可索引图片的视觉向量")
    parser.add_argument("--document-id", type=int, default=None)
    parser.add_argument("--knowledge-base-id", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commit-every", type=int, default=20)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    started_at = time.perf_counter()

    with SessionLocal() as db:
        docs = list(_iter_documents(db, index_generation=settings.visual_index_generation, args=args))
        logger.info("视觉准入回填开始: document_count=%s dry_run=%s", len(docs), args.dry_run)

        admission_service = IndexAdmissionService()
        pipeline = IndexPipelineService(db)
        asset_repository = DocumentAssetRepository(db)
        visual_index_service = _build_visual_index_service(settings)
        visual_indexer = VisualMilvusIndexer()

        affected_docs = 0
        metadata_updated_docs = 0
        reindexed_docs = 0
        scanned_assets = 0
        rescored_assets = 0
        changed_assets = 0
        newly_admitted_assets = 0
        rebuilt_vectors = 0
        deleted_vectors = 0

        for position, (document, publication_token) in enumerate(docs, start=1):
            pages = list(
                db.scalars(
                    select(DocumentPage)
                    .where(DocumentPage.document_id == document.id, DocumentPage.version_no == document.version_no)
                    .order_by(DocumentPage.page_no)
                ).all()
            )
            if not pages:
                continue
            blocks = list(
                db.scalars(
                    select(DocumentPageBlock)
                    .where(DocumentPageBlock.document_id == document.id)
                    .order_by(DocumentPageBlock.page_id, DocumentPageBlock.block_index, DocumentPageBlock.id)
                ).all()
            )
            assets = asset_repository.list_by_document_version(document.id, document.version_no, status="ready")
            if not assets:
                continue

            scanned_assets += len(assets)
            page_by_id = {int(page.id): page for page in pages}
            block_by_id = {int(block.id): block for block in blocks}
            neighbor_by_block_id = _neighbor_by_block_id(blocks)
            decisions = admission_service.assess_visual_admission(
                assets,
                page_by_id=page_by_id,
                block_by_id=block_by_id,
                neighbor_by_block_id=neighbor_by_block_id,
            )

            document_newly_admitted = []
            document_changed_assets = 0
            requires_reindex = False
            for asset, decision in decisions.values():
                previous_status = _visual_status(asset.metadata_json)
                previous_payload = _visual_payload(asset.metadata_json)
                current_payload = admission_service._visual_admission_payload(decision)
                if previous_payload != current_payload:
                    document_changed_assets += 1
                if previous_status == "accepted" and not decision.accepted:
                    requires_reindex = True
                if decision.accepted and previous_status != "accepted":
                    document_newly_admitted.append(int(asset.id))
                    requires_reindex = True

            if document_changed_assets == 0:
                continue

            metadata_updated_docs += 1
            affected_docs += 1 if document_newly_admitted else 0
            changed_assets += document_changed_assets
            newly_admitted_assets += len(document_newly_admitted)
            rescored_assets += len(assets)
            admission_service.apply_visual_admission(
                assets,
                page_by_id=page_by_id,
                block_by_id=block_by_id,
                neighbor_by_block_id=neighbor_by_block_id,
            )

            logger.info(
                "视觉准入结果变化: position=%s/%s document_id=%s changed_assets=%s newly_admitted=%s reindex=%s",
                position,
                len(docs),
                document.id,
                document_changed_assets,
                len(document_newly_admitted),
                requires_reindex,
            )

            if args.dry_run:
                continue

            if requires_reindex:
                visual_assets = pipeline._list_visual_assets(document, pages)
                delete_result = visual_indexer.delete_document(document.id, flush=False)
                deleted_vectors += int(delete_result.get("delete_count", 0) or 0)
                if visual_assets:
                    build_result = visual_index_service.build_records(
                        visual_assets,
                        settings.visual_index_generation,
                        publication_token=publication_token,
                    )
                    rebuilt_vectors += int(build_result.get("vector_count", 0) or 0)
                reindexed_docs += 1

            if position % max(1, args.commit_every) == 0:
                db.commit()
                logger.info(
                    "视觉准入回填阶段提交: position=%s/%s metadata_updated_docs=%s reindexed_docs=%s newly_admitted_assets=%s rebuilt_vectors=%s",
                    position,
                    len(docs),
                    metadata_updated_docs,
                    reindexed_docs,
                    newly_admitted_assets,
                    rebuilt_vectors,
                )

        if args.dry_run:
            db.rollback()
        else:
            db.commit()

        summary = {
            "document_count": len(docs),
            "affected_docs": affected_docs,
            "metadata_updated_docs": metadata_updated_docs,
            "reindexed_docs": reindexed_docs,
            "scanned_assets": scanned_assets,
            "rescored_assets": rescored_assets,
            "changed_assets": changed_assets,
            "newly_admitted_assets": newly_admitted_assets,
            "deleted_vectors": deleted_vectors,
            "rebuilt_vectors": rebuilt_vectors,
            "dry_run": args.dry_run,
            "elapsed_seconds": round(time.perf_counter() - started_at, 3),
        }
        logger.info("视觉准入回填完成: %s", summary)
        print("VISUAL_ADMISSION_BACKFILL_DONE", json.dumps(summary, ensure_ascii=False, sort_keys=True))


def _iter_documents(db, *, index_generation: str, args: argparse.Namespace):
    stmt = (
        select(Document, IndexPublicationManifest.publication_token)
        .join(
            IndexPublicationManifest,
            (
                IndexPublicationManifest.document_id == Document.id
            )
            & (IndexPublicationManifest.version_no == Document.version_no),
        )
        .where(
            Document.current_version.is_(True),
            Document.is_current_version.is_(True),
            Document.is_deleted.is_(False),
            Document.parse_status == "success",
            Document.index_status == "indexed",
            IndexPublicationManifest.status == "published",
            IndexPublicationManifest.index_generation == index_generation,
        )
        .order_by(Document.id)
    )
    if args.document_id is not None:
        stmt = stmt.where(Document.id == args.document_id)
    if args.knowledge_base_id is not None:
        stmt = stmt.where(Document.knowledge_base_id == args.knowledge_base_id)
    if args.limit is not None and args.limit > 0:
        stmt = stmt.limit(args.limit)
    yield from db.execute(stmt).all()


def _build_visual_index_service(settings) -> VisualIndexService:
    return VisualIndexService(
        VisualEmbeddingService(
            api_base=settings.visual_embedding_api_base or settings.model_service_api_base,
            api_key=settings.visual_embedding_api_key or settings.model_service_api_key,
            model_name=settings.visual_embedding_model,
            dimension=settings.visual_embedding_dim,
            timeout_seconds=settings.visual_embedding_timeout_seconds,
            index_generation=settings.visual_index_generation,
            distance_metric=settings.visual_embedding_distance_metric,
            batch_size=settings.visual_embedding_batch_size,
        ),
        VisualMilvusIndexer(),
    )


def _neighbor_by_block_id(blocks: list[DocumentPageBlock]) -> dict[int, tuple[int | None, int | None]]:
    blocks_by_page: dict[int, list[DocumentPageBlock]] = {}
    for block in blocks:
        blocks_by_page.setdefault(int(block.page_id), []).append(block)

    result: dict[int, tuple[int | None, int | None]] = {}
    for page_blocks in blocks_by_page.values():
        ordered_blocks = sorted(page_blocks, key=lambda item: int(item.block_index or 0))
        for index, block in enumerate(ordered_blocks):
            previous = ordered_blocks[index - 1] if index > 0 else None
            following = ordered_blocks[index + 1] if index + 1 < len(ordered_blocks) else None
            result[int(block.id)] = (
                int(previous.id) if previous is not None else None,
                int(following.id) if following is not None else None,
            )
    return result


def _visual_status(metadata_json: str | None) -> str:
    if not metadata_json:
        return ""
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return ""
    if not isinstance(metadata, dict):
        return ""
    visual_admission = metadata.get("visual_admission")
    if not isinstance(visual_admission, dict):
        return ""
    return str(visual_admission.get("status") or "")


def _visual_payload(metadata_json: str | None) -> dict[str, object] | None:
    if not metadata_json:
        return None
    try:
        metadata = json.loads(metadata_json)
    except json.JSONDecodeError:
        return None
    if not isinstance(metadata, dict):
        return None
    visual_admission = metadata.get("visual_admission")
    return visual_admission if isinstance(visual_admission, dict) else None


if __name__ == "__main__":
    main()
