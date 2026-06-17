"""
Parser Service

负责：
1. 统一封装文档解析入口
2. 在 Office 非 PDF 文件上接入 LibreOffice 转 PDF
3. 在 API、Worker、脚本环境中统一解析本地路径
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import get_settings
from app.knowledge.parsing.mineru_parser import MinerUParser
from app.knowledge.parsing.parsed_document import ParseSource, ParsedDocumentResult
from app.knowledge.parsing.simple_text_parser import SimpleTextParser
from app.services.libreoffice_conversion_service import LibreOfficeConversionService

logger = logging.getLogger(__name__)

SIMPLE_TEXT_SUFFIXES = {".txt", ".md", ".csv"}


class ParserService:
    """
    文档解析服务。

    职责：
    - 根据文件类型选择 MinerU、本地解析器或 LibreOffice 转换链路
    - 对外返回统一的页级结构化结果
    - 在进入解析前把数据库中的相对路径解析为稳定绝对路径
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.mineru_parser = MinerUParser()
        self.simple_parser = SimpleTextParser()
        self.libreoffice_service = LibreOfficeConversionService()

    def parse(self, storage_path: str) -> list[dict]:
        """
        兼容旧接口，仅返回页级结构。

        参数:
            storage_path: 源文件存储路径。

        返回：
            页级结构列表。
        """

        return self.parse_document(storage_path).pages

    def parse_document(
        self,
        storage_path: str,
        document_id: int | None = None,
        version_no: int | None = None,
    ) -> ParsedDocumentResult:
        """
        解析文档并返回统一结构化结果。

        参数:
            storage_path: 数据库存储路径或本地文件路径。
            document_id: 文档ID，供 Office 转 PDF 缓存复用。
            version_no: 文档版本号，供 Office 转 PDF 缓存复用。

        返回：
            统一结构化解析结果对象。
        """

        resolved_storage_path = str(self.settings.resolve_local_path(storage_path))
        source = self._resolve_parse_source(
            resolved_storage_path,
            document_id=document_id,
            version_no=version_no,
        )
        suffix = Path(resolved_storage_path).suffix.lower()

        if suffix in SIMPLE_TEXT_SUFFIXES:
            logger.info(
                "使用本地简单解析器处理文本型文档: original_path=%s resolved_path=%s suffix=%s",
                storage_path,
                resolved_storage_path,
                suffix,
            )
            return self._build_simple_result(source)

        if self.settings.mineru_enabled:
            logger.info(
                "使用MinerU解析文档: original_path=%s resolved_path=%s parse_source=%s source_kind=%s timeout_seconds=%s",
                storage_path,
                resolved_storage_path,
                source.source_path,
                source.source_kind,
                self.settings.mineru_task_timeout_seconds,
            )
            return self.mineru_parser.parse_document(source.source_path, parse_source=source)

        logger.info(
            "未配置MinerU，使用本地解析器: original_path=%s resolved_path=%s parse_source=%s",
            storage_path,
            resolved_storage_path,
            source.source_path,
        )
        return self._build_simple_result(source)

    def _resolve_parse_source(
        self,
        storage_path: str,
        document_id: int | None,
        version_no: int | None,
    ) -> ParseSource:
        """
        根据文件类型决定实际提交给解析器的文件来源。

        参数:
            storage_path: 已解析为绝对路径的原始文件路径。
            document_id: 文档ID。
            version_no: 版本号。

        返回：
            ParseSource 对象。
        """

        path = Path(storage_path)
        suffix = path.suffix.lower()

        if suffix in SIMPLE_TEXT_SUFFIXES or suffix == ".pdf":
            return ParseSource(
                source_path=storage_path,
                source_kind="original",
                original_path=storage_path,
                converted_pdf_path=None,
                document_id=document_id,
                version_no=version_no,
            )

        if self.libreoffice_service.should_convert(storage_path):
            conversion = self.libreoffice_service.convert(
                storage_path=storage_path,
                document_id=document_id or 0,
                version_no=version_no or 1,
            )
            return ParseSource(
                source_path=conversion.pdf_path,
                source_kind="converted_pdf",
                original_path=storage_path,
                converted_pdf_path=conversion.pdf_path,
                document_id=document_id,
                version_no=version_no,
            )

        return ParseSource(
            source_path=storage_path,
            source_kind="original",
            original_path=storage_path,
            converted_pdf_path=None,
            document_id=document_id,
            version_no=version_no,
        )

    def _build_simple_result(self, source: ParseSource) -> ParsedDocumentResult:
        """
        调用本地简单解析器并包装为统一结果对象。

        参数:
            source: 解析来源描述对象。

        返回：
            统一结构化解析结果对象。
        """

        pages = self.simple_parser.parse(source.source_path)
        return ParsedDocumentResult(
            pages=pages,
            parser_name="simple_text",
            parse_source=source,
            raw_payload=None,
            task_id=None,
            metadata={},
        )
