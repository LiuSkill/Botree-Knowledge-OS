"""Shard-aware knowledge base rebuild runner for maintenance use."""

from __future__ import annotations

import argparse
import logging
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.exceptions import AppException
from app.knowledge.indexing.index_service import IndexService
from app.knowledge.indexing.visual_milvus_indexer import VisualMilvusIndexer
from app.models.document import Document
from app.repositories.graph_repository import GraphRepository
from app.repositories.page_index_repository import PageIndexRepository
from app.services.index_pipeline_service import IndexPipelineService
from app.services.knowledge_base_rebuild_service import KnowledgeBaseRebuildService

logger = logging.getLogger(__name__)

RETRYABLE_APP_CODES = {502, 503, 504}


def main() -> None:
    parser = argparse.ArgumentParser(description="原地完整重建指定知识库的一个分片")
    parser.add_argument("knowledge_base_id", type=int)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--resume-after-document-id", type=int, default=None)
    parser.add_argument("--lock-wait-timeout", type=int, default=30)
    parser.add_argument("--max-retries", type=int, default=8)
    parser.add_argument("--retry-sleep-seconds", type=int, default=5)
    args = parser.parse_args()

    if args.shard_count <= 0:
        raise SystemExit("shard-count must be positive")
    if args.shard_index < 0 or args.shard_index >= args.shard_count:
        raise SystemExit("shard-index out of range")

    logging.basicConfig(level=logging.INFO)

    with SessionLocal() as db:
        db.execute(text(f"SET SESSION innodb_lock_wait_timeout = {int(args.lock_wait_timeout)}"))
        service = KnowledgeBaseRebuildService(db)
        all_documents = service.repository.list_source_documents(args.knowledge_base_id)
        for document in all_documents:
            pages = service.repository.list_pages(document)
            if not pages:
                raise AppException(f"文档 {document.id} 缺少可复用解析页，无法原地重建")
            service._backfill_admission(document, pages)
        before = service._snapshot(all_documents)
        documents = all_documents[args.shard_index :: args.shard_count]
        if args.resume_after_document_id is not None:
            try:
                resume_index = [item.id for item in documents].index(args.resume_after_document_id)
            except ValueError as exc:
                raise SystemExit(
                    f"resume-after-document-id={args.resume_after_document_id} 不属于 shard {args.shard_index + 1}/{args.shard_count}"
                ) from exc
            documents = documents[resume_index + 1 :]
        document_ids = [item.id for item in documents]
        logger.info(
            "知识库分片重建开始: knowledge_base_id=%s shard=%s/%s document_count=%s total_documents=%s resume_after_document_id=%s",
            args.knowledge_base_id,
            args.shard_index + 1,
            args.shard_count,
            len(document_ids),
            len(all_documents),
            args.resume_after_document_id,
        )
        for position, document_id in enumerate(document_ids, start=1):
            for attempt in range(1, args.max_retries + 1):
                try:
                    document = db.get(Document, document_id)
                    if document is None:
                        raise AppException(f"文档 {document_id} 不存在，无法重建")
                    pages = service.repository.list_pages(document)
                    payloads = [
                        {
                            "page_number": page.page_no,
                            "page_title": page.page_title,
                            "text": page.corrected_text or page.clean_content or page.page_text,
                        }
                        for page in pages
                        if page.index_admission_status == "text_indexed"
                    ]
                    chunks = service._build_chunks(document, payloads)
                    old_chunks = service.document_repository.list_chunks(document.id, include_obsolete=True)
                    vector_ids = [chunk.vector_id for chunk in old_chunks if chunk.vector_id]
                    IndexService(db).delete_document_index(document.id, vector_ids, flush=False)
                    if get_settings().visual_index_enabled:
                        VisualMilvusIndexer().delete_document(document.id, flush=False)
                    GraphRepository(db).clear_all_document_graph(document.id)
                    PageIndexRepository(db).clear_document_indexes(document.id, document.version_no)
                    service.document_repository.replace_chunks(document.id, chunks, version_no=document.version_no)
                    pipeline = IndexPipelineService(db)
                    result = pipeline.build_all(document, publish=False)
                    manifest = service.publication_repository.get_by_token(str(result["publication_token"]))
                    if manifest is None:
                        raise AppException(f"document {document.id} is missing its staging publication manifest")
                    pipeline.publish_all(document, manifest=manifest)
                    db.flush()
                    service.ensure_unchanged(
                        before,
                        service._snapshot(service.repository.list_source_documents(args.knowledge_base_id)),
                    )
                    db.commit()
                    logger.info(
                        "知识库分片文档重建并发布完成: knowledge_base_id=%s shard=%s/%s position=%s/%s document_id=%s",
                        args.knowledge_base_id,
                        args.shard_index + 1,
                        args.shard_count,
                        position,
                        len(document_ids),
                        document.id,
                    )
                    break
                except OperationalError as exc:
                    db.rollback()
                    error_code = exc.orig.args[0] if getattr(exc, "orig", None) and getattr(exc.orig, "args", None) else None
                    if error_code not in {1205, 1213} or attempt >= args.max_retries:
                        raise
                    _sleep_before_retry(
                        args,
                        document_id=document_id,
                        position=position,
                        total=len(document_ids),
                        attempt=attempt,
                        error_code=str(error_code),
                    )
                except AppException as exc:
                    db.rollback()
                    if exc.code not in RETRYABLE_APP_CODES or attempt >= args.max_retries:
                        raise
                    _sleep_before_retry(
                        args,
                        document_id=document_id,
                        position=position,
                        total=len(document_ids),
                        attempt=attempt,
                        error_code=str(exc.code),
                    )
        logger.info(
            "知识库分片重建完成: knowledge_base_id=%s shard=%s/%s document_count=%s",
            args.knowledge_base_id,
            args.shard_index + 1,
            args.shard_count,
            len(document_ids),
        )


def _sleep_before_retry(
    args: argparse.Namespace,
    *,
    document_id: int,
    position: int,
    total: int,
    attempt: int,
    error_code: str,
) -> None:
    sleep_seconds = args.retry_sleep_seconds * attempt
    logger.warning(
        "知识库分片文档重建重试: knowledge_base_id=%s shard=%s/%s position=%s/%s document_id=%s attempt=%s/%s error_code=%s sleep_seconds=%s",
        args.knowledge_base_id,
        args.shard_index + 1,
        args.shard_count,
        position,
        total,
        document_id,
        attempt,
        args.max_retries,
        error_code,
        sleep_seconds,
    )
    time.sleep(sleep_seconds)


if __name__ == "__main__":
    main()
