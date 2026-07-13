"""
PageIndex Service

负责：
1. 将 MinerU 或本地解析结果落库为统一页级文档模型
2. 构建 PageIndex 文档树和 ripgrep 文本镜像
3. 支持页级人工修正、质量确认和索引发布
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.knowledge.parsing.searchable_text import build_page_searchable_text, normalize_searchable_text
from app.models.document import Document, DocumentChunk
from app.models.page_index import DocumentPage, DocumentPageBlock, PageIndex
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.page_index_repository import PageIndexRepository
from app.services.system_service import SystemService

logger = logging.getLogger(__name__)
DRAWING_NO_MAX_LENGTH = 100

DRAWING_NO_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:图纸编号|图号|drawing\s*no\.?|dwg\s*no\.?)[:：\s]*([A-Za-z0-9_.\-/]+)", re.IGNORECASE),
    re.compile(r"\b([A-Z]{1,5}-\d{2,}[-A-Z0-9]*)\b"),
)

BLOCK_METADATA_EXCLUDED_KEYS = {
    "type",
    "block_type",
    "text",
    "content",
    "markdown",
    "md",
    "clean_text",
    "filter_status",
    "filter_reason",
    "bbox",
    "position",
    "metadata",
    "image_candidates",
}


@dataclass(slots=True)
class PageReplaceResult:
    """
    页级落库结果

    职责：
    - 返回新写入的页记录
    - 返回新写入的块记录
    - 便于后续把图片资产关联回页表和块表
    """

    pages: list[DocumentPage]
    blocks: list[DocumentPageBlock]


class PageIndexService:
    """
    PageIndex 服务

    职责：
    - 归一化页级解析结果
    - 管理页级修正和质量确认
    - 生成 PageIndex 与 ripgrep 文本文件
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.repository = PageIndexRepository(db)
        self.document_repository = DocumentRepository(db)

    def replace_pages_from_parse(self, document: Document, pages: list[dict[str, Any]]) -> PageReplaceResult:
        """
        用解析结果替换当前文档版本的页级模型。

        参数:
            document: 文档 ORM 对象
            pages: ParserService 返回的页级字典列表

        返回:
            新写入的页记录和块记录
        """

        self.repository.clear_document_pages(document.id, document.version_no)
        saved_pages: list[DocumentPage] = []
        saved_blocks: list[DocumentPageBlock] = []

        for index, raw_page in enumerate(pages, start=1):
            normalized = self._normalize_page(document, raw_page, index)
            page = self.repository.add_page(
                DocumentPage(
                    knowledge_base_id=document.knowledge_base_id,
                    project_id=document.project_id,
                    document_id=document.id,
                    version_no=document.version_no,
                    page_no=normalized["page_no"],
                    drawing_no=normalized["drawing_no"],
                    page_title=normalized["page_title"],
                    page_text=normalized["page_text"],
                    clean_content=normalized["clean_content"],
                    filtered_content=normalized["filtered_content"],
                    cleaning_metadata_json=normalized["cleaning_metadata_json"],
                    page_summary=normalized["page_summary"],
                    layout_json=json.dumps(normalized["layout"], ensure_ascii=False) if normalized["layout"] else None,
                    mineru_json_object_key=normalized["mineru_json_object_key"],
                    page_image_object_key=normalized["page_image_object_key"],
                    source_hash=normalized["source_hash"],
                    security_level=document.security_level,
                )
            )
            blocks = self._build_blocks(page, raw_page)
            self.repository.add_blocks(blocks)
            saved_pages.append(page)
            saved_blocks.extend(blocks)

        logger.info("PageIndex 页级模型已生成: document_id=%s pages=%s", document.id, len(saved_pages))
        return PageReplaceResult(pages=saved_pages, blocks=saved_blocks)

    def build_page_indexes(self, document: Document) -> dict[str, int]:
        """
        根据文档页和 Chunk 构建 PageIndex。

        参数:
            document: 文档 ORM 对象

        返回:
            构建结果摘要
        """

        pages = self.repository.list_pages(document.id, document.version_no)
        if not pages:
            raise AppException("文档尚未生成页级模型，无法构建 PageIndex")

        self.repository.clear_document_indexes(document.id, document.version_no)

        chunks = self.document_repository.list_chunks(document.id, version_no=document.version_no)
        chunk_by_page: dict[int, list[DocumentChunk]] = {}
        for chunk in chunks:
            if chunk.page_number is not None:
                chunk_by_page.setdefault(chunk.page_number, []).append(chunk)

        mirror_count = 0
        index_count = 0
        for page in pages:
            text = page.corrected_text or page.clean_content or ""
            mirror_path = self._write_text_mirror(document, page, text)
            mirror_count += 1
            page_chunks = chunk_by_page.get(page.page_no) or [None]
            for chunk in page_chunks:
                self.repository.add_page_index(
                    PageIndex(
                        knowledge_base_id=document.knowledge_base_id,
                        project_id=document.project_id,
                        document_id=document.id,
                        page_id=page.id,
                        chunk_id=chunk.id if chunk else None,
                        version_no=document.version_no,
                        page_no=page.page_no,
                        drawing_no=self._normalize_drawing_no(
                            page.drawing_no or document.drawing_no,
                            fallback_text=page.corrected_text or page.clean_content or page.page_text or "",
                        ),
                        index_text=text,
                        text_mirror_path=str(mirror_path),
                        status="staging",
                        security_level=document.security_level,
                    )
                )
                index_count += 1

        logger.info("PageIndex 构建完成: document_id=%s indexes=%s mirrors=%s", document.id, index_count, mirror_count)
        return {"page_count": len(pages), "page_index_count": index_count, "text_mirror_count": mirror_count}

    def list_pages(self, document_id: int, user: User, version_no: int | None = None) -> list[DocumentPage]:
        """查询文档页记录。"""

        document = self._ensure_document_access(document_id, user)
        return self.repository.list_pages(document.id, version_no or document.version_no)

    def list_blocks(self, document_id: int, user: User, version_no: int | None = None) -> list[DocumentPageBlock]:
        """查询文档当前版本的页块记录。"""

        document = self._ensure_document_access(document_id, user)
        return self.repository.list_blocks(document.id, version_no or document.version_no)

    def correct_page(
        self,
        document_id: int,
        page_no: int,
        corrected_text: str,
        user: User,
        drawing_no: str | None = None,
        page_title: str | None = None,
    ) -> DocumentPage:
        """人工修正文档页内容。"""

        document = self._ensure_document_access(document_id, user)
        page = self.repository.get_page(document.id, page_no, document.version_no)
        if not page:
            raise AppException("文档页不存在", status_code=404, code=404)

        page.corrected_text = corrected_text
        page.correction_status = "corrected"
        page.corrected_by = user.id
        if drawing_no is not None:
            page.drawing_no = self._normalize_drawing_no(
                drawing_no,
                fallback_text=corrected_text or page.clean_content or page.page_text or "",
            )
        if page_title is not None:
            page.page_title = page_title
        SystemService(self.db).record_operation(
            user,
            "修正文档页",
            "document_page",
            page.id,
            f"document_id={document.id}, page_no={page.page_no}",
        )
        self.db.commit()
        return page

    def quality_check(self, document_id: int, user: User, passed: bool, comment: str | None = None) -> dict[str, Any]:
        """确认页级解析质量。"""

        document = self._ensure_document_access(document_id, user)
        pages = self.repository.list_pages(document.id, document.version_no)
        if not pages:
            raise AppException("文档尚未解析，无法进行质量检查")

        if not passed:
            document.index_status = "failed"
            document.build_error = comment or "解析质量检查未通过"
        else:
            for page in pages:
                if page.correction_status == "raw":
                    page.correction_status = "confirmed"
            document.index_status = "parsed"
            document.build_error = None

        SystemService(self.db).record_operation(
            user,
            "解析质量检查",
            "document",
            document.id,
            comment or ("通过" if passed else "未通过"),
        )
        self.db.commit()
        return {"document_id": document.id, "page_count": len(pages), "passed": passed, "index_status": document.index_status}

    def publish_page_indexes(self, document: Document) -> dict[str, int]:
        """发布指定文档版本的 PageIndex。"""

        published_count = self.repository.publish_document_indexes(document.id, document.version_no)
        logger.info("PageIndex 发布完成: document_id=%s published=%s", document.id, published_count)
        return {"published_page_index_count": published_count}

    def _normalize_page(self, document: Document, raw_page: dict[str, Any], fallback_no: int) -> dict[str, Any]:
        """将不同解析器输出归一化为页级模型字段。"""

        raw_content = normalize_searchable_text(self._first_text(raw_page, ("content", "text", "markdown", "md")))
        clean_content = build_page_searchable_text(raw_page)
        filtered_content = normalize_searchable_text(str(raw_page.get("filtered_content") or ""))
        cleaning_metadata = raw_page.get("cleaning_metadata")
        page_no = int(raw_page.get("page_number") or raw_page.get("page_no") or raw_page.get("page") or fallback_no)
        drawing_no = self._normalize_drawing_no(
            raw_page.get("drawing_no") or document.drawing_no,
            fallback_text=clean_content or raw_content,
        )
        layout = raw_page.get("layout") or raw_page.get("layout_json") or raw_page.get("blocks") or raw_page.get("page_blocks")
        page_title = raw_page.get("page_title") or raw_page.get("title") or self._guess_page_title(clean_content or raw_content)
        return {
            "page_no": page_no,
            "drawing_no": drawing_no,
            "page_title": page_title,
            "page_text": raw_content,
            "clean_content": clean_content,
            "filtered_content": filtered_content or None,
            "cleaning_metadata_json": json.dumps(cleaning_metadata, ensure_ascii=False) if cleaning_metadata else None,
            "page_summary": clean_content[:500] if clean_content else None,
            "layout": layout,
            "mineru_json_object_key": raw_page.get("mineru_json_object_key"),
            "page_image_object_key": raw_page.get("page_image_object_key") or raw_page.get("image_object_key"),
            "source_hash": hashlib.sha256(clean_content.encode("utf-8")).hexdigest() if clean_content else None,
        }

    def _first_text(self, payload: dict[str, Any], keys: tuple[str, ...]) -> str:
        """读取原始解析文本，不回退到 clean_* 字段。"""

        for key in keys:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _build_blocks(self, page: DocumentPage, raw_page: dict[str, Any]) -> list[DocumentPageBlock]:
        """根据解析结果中的块结构生成页块记录。"""

        raw_blocks = raw_page.get("blocks") or raw_page.get("page_blocks") or []
        if not isinstance(raw_blocks, list) or not raw_blocks:
            return [
                DocumentPageBlock(
                    page_id=page.id,
                    document_id=page.document_id,
                    block_index=1,
                    block_type="text",
                    text=page.page_text,
                    clean_text=page.clean_content,
                    filter_status="kept" if page.clean_content else "filtered",
                    filter_reason=None if page.clean_content else "empty_after_cleaning",
                    bbox_json=None,
                    metadata_json=None,
                )
            ]

        blocks: list[DocumentPageBlock] = []
        for index, item in enumerate(raw_blocks, start=1):
            if isinstance(item, dict):
                block_type = str(item.get("type") or item.get("block_type") or "text")
                text = item.get("text") or item.get("content") or item.get("markdown") or item.get("md")
                clean_text = item.get("clean_text")
                filter_status = str(item.get("filter_status") or "kept")
                filter_reason = item.get("filter_reason")
                bbox = item.get("bbox") or item.get("position")
                metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else None
                if metadata is None:
                    metadata = {key: value for key, value in item.items() if key not in BLOCK_METADATA_EXCLUDED_KEYS}
            else:
                block_type = "text"
                text = str(item)
                clean_text = str(item)
                filter_status = "kept"
                filter_reason = None
                bbox = None
                metadata = {}

            blocks.append(
                DocumentPageBlock(
                    page_id=page.id,
                    document_id=page.document_id,
                    block_index=index,
                    block_type=block_type,
                    text=str(text) if text is not None else None,
                    clean_text=str(clean_text) if clean_text is not None else None,
                    filter_status=filter_status,
                    filter_reason=str(filter_reason) if filter_reason is not None else None,
                    bbox_json=json.dumps(bbox, ensure_ascii=False) if bbox is not None else None,
                    metadata_json=json.dumps(metadata, ensure_ascii=False) if metadata else None,
                )
            )
        return blocks

    def _write_text_mirror(self, document: Document, page: DocumentPage, text: str) -> Path:
        """写入供 ripgrep 使用的页级 Markdown 文本镜像。"""

        project_segment = str(document.project_id) if document.project_id is not None else "base"
        mirror_dir = self.settings.page_index_path / project_segment / str(document.id) / str(document.version_no)
        mirror_dir.mkdir(parents=True, exist_ok=True)
        mirror_path = mirror_dir / f"page_{page.page_no}.md"
        mirror_path.write_text(
            "\n".join(
                [
                    f"# {document.file_name} / page {page.page_no}",
                    f"document_id: {document.id}",
                    f"project_id: {document.project_id or ''}",
                    f"security_level: {document.security_level}",
                    f"drawing_no: {page.drawing_no or ''}",
                    "",
                    text,
                ]
            ),
            encoding="utf-8",
        )
        return mirror_path

    def _guess_drawing_no(self, text: str) -> str | None:
        """从页文本中猜测图纸编号。"""

        for pattern in DRAWING_NO_PATTERNS:
            for match in pattern.finditer(text):
                candidate = self._clean_drawing_no_candidate(match.group(1))
                if candidate is not None:
                    return candidate
        return None

    def _normalize_drawing_no(self, drawing_no: Any, *, fallback_text: str = "") -> str | None:
        """
        规范化图纸编号，避免异常 OCR 结果导致写库失败。

        规则：
        - 先清理空白和包裹符号；
        - 过长或明显带噪声时，优先尝试从自身或页文本中提取合理图号；
        - 提取失败时，按数据库字段上限截断并记录 warning。
        """

        raw_value = self._normalize_inline_text(drawing_no)
        if raw_value:
            guessed_from_raw = self._guess_drawing_no(raw_value)
            if guessed_from_raw is not None:
                return guessed_from_raw
            direct_candidate = self._clean_drawing_no_candidate(raw_value)
            if direct_candidate is not None:
                return direct_candidate
        if fallback_text:
            guessed_from_text = self._guess_drawing_no(fallback_text)
            if guessed_from_text is not None:
                return guessed_from_text
        if not raw_value:
            return None

        truncated = raw_value[:DRAWING_NO_MAX_LENGTH]
        logger.warning(
            "图纸编号超长，已截断后写入: original_length=%s truncated=%s",
            len(raw_value),
            truncated,
        )
        return truncated

    def _clean_drawing_no_candidate(self, value: str | None) -> str | None:
        """清洗并校验图号候选值。"""

        normalized = self._normalize_inline_text(value)
        if not normalized:
            return None
        if len(normalized) > DRAWING_NO_MAX_LENGTH:
            return None
        return normalized

    def _normalize_inline_text(self, value: Any) -> str:
        """把单行元数据文本归一化，移除多余空白和包裹符号。"""

        if value is None:
            return ""
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        return normalized.strip("()[]{}<>\"'`|,;:：")

    def _guess_page_title(self, text: str) -> str | None:
        """从页文本首行猜测页标题。"""

        first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
        if 0 < len(first_line) <= 120:
            return first_line
        return None

    def _ensure_document_access(self, document_id: int, user: User) -> Document:
        """复用 DocumentService 的文档访问控制。"""

        from app.services.document_service import DocumentService

        return DocumentService(self.db).get_document(document_id, user)
