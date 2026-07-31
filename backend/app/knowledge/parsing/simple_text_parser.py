"""
Simple Text Parser

职责：
1. 解析 txt/md/csv/log 等纯文本文件
2. 尝试解析 docx/pdf 的基础文本
3. 在不支持格式时返回清晰错误
"""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import AppException
from app.knowledge.parsing.file_signature import ensure_pdf_header


class SimpleTextParser:
    """
    简单文本解析器。

    职责：
    - 在未配置 MinerU 时直接读取本地文本文档
    - 作为本地兜底解析器处理常见文档格式
    """

    text_suffixes = {".txt", ".md", ".markdown", ".csv", ".log"}
    supported_suffixes = text_suffixes | {".docx", ".pdf"}

    def supports_file(self, storage_path: str) -> bool:
        """判断本地解析器是否支持指定文件类型。"""

        return Path(storage_path).suffix.lower() in self.supported_suffixes

    def parse(self, storage_path: str) -> list[dict]:
        """解析文档内容并返回页级结构。"""

        path = Path(storage_path)
        suffix = path.suffix.lower()
        if suffix in self.text_suffixes:
            return [{"page_number": 1, "content": self._read_text(path)}]
        if suffix == ".docx":
            return [{"page_number": 1, "content": self._read_docx(path)}]
        if suffix == ".pdf":
            return self._read_pdf(path)
        raise AppException(f"暂不支持解析该文件类型：{suffix or 'unknown'}", status_code=400)

    def _read_text(self, path: Path) -> str:
        """读取文本文件。"""

        for encoding in ("utf-8", "gb18030", "utf-16"):
            try:
                return path.read_text(encoding=encoding)
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="ignore")

    def _read_docx(self, path: Path) -> str:
        """读取 docx 文本。"""

        try:
            from docx import Document as DocxDocument
        except Exception as exc:  # pragma: no cover - 依赖缺失由运行环境决定
            raise AppException("当前环境缺少 python-docx，无法解析 docx") from exc

        document = DocxDocument(path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())

    def _read_pdf(self, path: Path) -> list[dict]:
        """读取 PDF 文本。"""

        try:
            from pypdf import PdfReader
        except Exception as exc:  # pragma: no cover - 依赖缺失由运行环境决定
            raise AppException("当前环境缺少 pypdf，无法解析 pdf") from exc

        ensure_pdf_header(path)
        reader = PdfReader(str(path))
        pages: list[dict] = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append({"page_number": index, "content": page.extract_text() or ""})
        return pages
