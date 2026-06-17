"""
Simple Text Parser

负责：
1. 解析 txt/md/csv/log 等文本文件
2. 尝试解析 docx/pdf 的基础文本
3. 在不支持格式时返回清晰错误
"""

from pathlib import Path

from app.core.exceptions import AppException


class SimpleTextParser:
    """
    简单文本解析器

    职责：
    - 在未配置 MinerU 时直接读取真实文件文本
    - 作为本地解析执行器处理常见文档格式
    """

    text_suffixes = {".txt", ".md", ".markdown", ".csv", ".log"}
    supported_suffixes = text_suffixes | {".docx", ".pdf"}

    def supports_file(self, storage_path: str) -> bool:
        """
        判断本地解析器是否支持指定文件类型。
        参数:
            storage_path: 文件存储路径。
        返回:
            True 表示可由本地解析器兜底处理。
        """

        return Path(storage_path).suffix.lower() in self.supported_suffixes

    def parse(self, storage_path: str) -> list[dict]:
        """
        解析文档内容

        参数:
            storage_path: 文件存储路径

        返回:
            包含 page_number/content 的页面列表。
        """

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
        except Exception as exc:
            raise AppException("当前环境缺少 python-docx，无法解析 docx") from exc

        document = DocxDocument(path)
        return "\n".join(paragraph.text for paragraph in document.paragraphs if paragraph.text.strip())

    def _read_pdf(self, path: Path) -> list[dict]:
        """读取 PDF 文本。"""

        try:
            from pypdf import PdfReader
        except Exception as exc:
            raise AppException("当前环境缺少 pypdf，无法解析 pdf") from exc

        self._validate_pdf_header(path)
        reader = PdfReader(str(path))
        pages: list[dict] = []
        for index, page in enumerate(reader.pages, start=1):
            pages.append({"page_number": index, "content": page.extract_text() or ""})
        return pages

    def _validate_pdf_header(self, path: Path) -> None:
        """
        检查 PDF 文件头，尽早识别扩展名正确但内容损坏的文件。
        参数:
            path: PDF 文件路径。
        """

        with path.open("rb") as file_obj:
            header = file_obj.read(5)
        if header != b"%PDF-":
            raise AppException("PDF文件头无效，文件内容不是合法PDF，请重新上传原始文件", status_code=400)
