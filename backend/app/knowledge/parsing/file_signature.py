"""
文件签名校验工具。

职责：
1. 复用轻量文件头校验逻辑，尽早识别扩展名正确但内容损坏的文件
2. 为不同解析入口提供一致的错误提示
"""

from __future__ import annotations

from pathlib import Path

from app.core.exceptions import AppException


PDF_HEADER_MARKER = b"%PDF-"
PDF_HEADER_SCAN_BYTES = 1024


def ensure_pdf_header(path: Path) -> None:
    """
    校验 PDF 文件头是否包含合法 PDF 标识。

    说明：
    - 按 PDF 规范，文件头通常以 `%PDF-` 开始；
    - 少数文件可能在前面带少量前导字节，因此这里放宽为前 1024 字节内可找到标识；
    - 若未找到，则说明该文件虽然扩展名是 `.pdf`，但内容并不是合法 PDF。
    """

    with path.open("rb") as file_obj:
        header = file_obj.read(PDF_HEADER_SCAN_BYTES)
    if PDF_HEADER_MARKER not in header:
        raise AppException("PDF文件头无效，文件内容不是合法PDF，请重新上传原始文件", status_code=400)
