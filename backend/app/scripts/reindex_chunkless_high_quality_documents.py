"""Rebuild approved parsed documents that still have no active chunks."""

from __future__ import annotations

import argparse
import logging
from typing import Any

from sqlalchemy import Select, case, func, select, text

from app.core.database import SessionLocal
from app.models.document import Document, DocumentChunk
from app.models.page_index import DocumentPage
from app.models.user import User
from app.services.document_service import DocumentService

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="批量重建已审核已解析但仍没有 active chunk 的文档索引")
    parser.add_argument("--operator-id", type=int, default=1)
    parser.add_argument("--document-id", type=int, action="append", dest="document_ids")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--lock-wait-timeout", type=int, default=30)
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    with SessionLocal() as db:
        db.execute(text(f"SET SESSION innodb_lock_wait_timeout = {int(args.lock_wait_timeout)}"))
        if db.get(User, args.operator_id) is None:
            raise SystemExit(f"operator_id={args.operator_id} 不存在")
        candidates = _load_candidates(db, document_ids=args.document_ids, limit=args.limit)

    if not candidates:
        logger.info("没有发现需要重建的候选文档")
        return

    logger.info("候选文档数=%s", len(candidates))
    for item in candidates:
        logger.info(
            "候选文档: document_id=%s version_no=%s pages=%s clean_chars=%s file_name=%s",
            item["document_id"],
            item["version_no"],
            item["page_count"],
            item["clean_char_count"],
            item["file_name"],
        )

    succeeded = 0
    failed = 0
    for item in candidates:
        document_id = int(item["document_id"])
        version_no = int(item["version_no"])
        try:
            with SessionLocal() as db:
                db.execute(text(f"SET SESSION innodb_lock_wait_timeout = {int(args.lock_wait_timeout)}"))
                operator = db.get(User, args.operator_id)
                if operator is None:
                    raise RuntimeError(f"operator_id={args.operator_id} 不存在")
                before = _version_counts(db, document_id, version_no)
                result = DocumentService(db).build_document_index(document_id, operator, version_no=version_no)
                after = _version_counts(db, document_id, version_no)
                logger.info(
                    "重建完成: document_id=%s version_no=%s chunk_count=%s active_chunks=%s->%s text_pages=%s->%s publish=%s",
                    document_id,
                    version_no,
                    result.get("chunk_count"),
                    before["active_chunk_count"],
                    after["active_chunk_count"],
                    before["text_page_count"],
                    after["text_page_count"],
                    (result.get("publish") or {}).get("published_page_index_count"),
                )
                succeeded += 1
        except Exception:
            failed += 1
            logger.exception("重建失败: document_id=%s version_no=%s", document_id, version_no)
            if args.stop_on_error:
                raise

    with SessionLocal() as db:
        inconsistent = _remaining_chunkless_with_text_pages(db)
        remaining = _remaining_chunkless(db, document_ids=args.document_ids)

    logger.info("批量重建结束: succeeded=%s failed=%s", succeeded, failed)
    if inconsistent:
        logger.warning("仍存在已命中文本准入但没有 active chunk 的文档数=%s", len(inconsistent))
        for item in inconsistent:
            logger.warning(
                "异常文档: document_id=%s version_no=%s text_pages=%s active_chunks=%s file_name=%s",
                item["document_id"],
                item["version_no"],
                item["text_page_count"],
                item["active_chunk_count"],
                item["file_name"],
            )
    else:
        logger.info("验证通过：不存在 text_indexed 页面但仍没有 active chunk 的文档")

    if remaining:
        logger.info("仍无 active chunk 的文档数=%s", len(remaining))
        for item in remaining:
            logger.info(
                "剩余文档: document_id=%s version_no=%s text_pages=%s visual_pages=%s metadata_pages=%s clean_chars=%s file_name=%s",
                item["document_id"],
                item["version_no"],
                item["text_page_count"],
                item["visual_page_count"],
                item["metadata_page_count"],
                item["clean_char_count"],
                item["file_name"],
            )
    else:
        logger.info("所有候选文档都已生成 active chunk")


def _base_candidate_stmt(document_ids: list[int] | None = None) -> Select[tuple[Document]]:
    stmt = select(Document).where(
        Document.review_status == "approved",
        Document.parse_status == "success",
        Document.is_deleted.is_(False),
        _page_count_subquery() > 0,
        _active_chunk_count_subquery() == 0,
    )
    if document_ids:
        stmt = stmt.where(Document.id.in_(document_ids))
    return stmt.order_by(Document.id)


def _load_candidates(db: Any, *, document_ids: list[int] | None, limit: int | None) -> list[dict[str, Any]]:
    stmt = _base_candidate_stmt(document_ids=document_ids)
    if limit is not None and limit > 0:
        stmt = stmt.limit(limit)
    documents = list(db.scalars(stmt).all())
    rows: list[dict[str, Any]] = []
    for document in documents:
        counts = _version_counts(db, document.id, document.version_no)
        rows.append(
            {
                "document_id": document.id,
                "version_no": document.version_no,
                "file_name": document.file_name,
                "page_count": counts["page_count"],
                "clean_char_count": counts["clean_char_count"],
            }
        )
    return rows


def _remaining_chunkless_with_text_pages(db: Any) -> list[dict[str, Any]]:
    documents = list(db.scalars(_base_candidate_stmt()).all())
    rows: list[dict[str, Any]] = []
    for document in documents:
        counts = _version_counts(db, document.id, document.version_no)
        if counts["text_page_count"] > 0:
            rows.append(
                {
                    "document_id": document.id,
                    "version_no": document.version_no,
                    "file_name": document.file_name,
                    **counts,
                }
            )
    return rows


def _remaining_chunkless(db: Any, *, document_ids: list[int] | None) -> list[dict[str, Any]]:
    documents = list(db.scalars(_base_candidate_stmt(document_ids=document_ids)).all())
    return [
        {
            "document_id": document.id,
            "version_no": document.version_no,
            "file_name": document.file_name,
            **_version_counts(db, document.id, document.version_no),
        }
        for document in documents
    ]


def _version_counts(db: Any, document_id: int, version_no: int) -> dict[str, int]:
    page_stmt = select(
        func.count(DocumentPage.id),
        func.coalesce(func.sum(func.length(func.coalesce(DocumentPage.clean_content, ""))), 0),
        func.sum(case((DocumentPage.index_admission_status == "text_indexed", 1), else_=0)),
        func.sum(case((DocumentPage.index_admission_status == "visual_indexed", 1), else_=0)),
        func.sum(case((DocumentPage.index_admission_status == "metadata_only", 1), else_=0)),
    ).where(
        DocumentPage.document_id == document_id,
        DocumentPage.version_no == version_no,
    )
    page_count, clean_char_count, text_page_count, visual_page_count, metadata_page_count = db.execute(page_stmt).one()
    active_chunk_count = db.scalar(
        select(func.count(DocumentChunk.id)).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.version_no == version_no,
            DocumentChunk.chunk_status == "active",
        )
    )
    return {
        "page_count": int(page_count or 0),
        "clean_char_count": int(clean_char_count or 0),
        "text_page_count": int(text_page_count or 0),
        "visual_page_count": int(visual_page_count or 0),
        "metadata_page_count": int(metadata_page_count or 0),
        "active_chunk_count": int(active_chunk_count or 0),
    }


def _page_count_subquery() -> Any:
    return (
        select(func.count(DocumentPage.id))
        .where(
            DocumentPage.document_id == Document.id,
            DocumentPage.version_no == Document.version_no,
        )
        .correlate(Document)
        .scalar_subquery()
    )


def _active_chunk_count_subquery() -> Any:
    return (
        select(func.count(DocumentChunk.id))
        .where(
            DocumentChunk.document_id == Document.id,
            DocumentChunk.version_no == Document.version_no,
            DocumentChunk.chunk_status == "active",
        )
        .correlate(Document)
        .scalar_subquery()
    )


if __name__ == "__main__":
    main()
