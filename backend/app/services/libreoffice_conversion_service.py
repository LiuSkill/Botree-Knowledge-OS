"""
LibreOffice Conversion Service

负责：
1. 将 Office 非 PDF 文档转换为 PDF
2. 复用同一文档版本的转换结果，避免重复执行 CLI
3. 为 MinerU 解析准备稳定、可追踪的 PDF 输入
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)

OFFICE_CONVERTIBLE_SUFFIXES = {
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".odt",
    ".odp",
    ".ods",
    ".rtf",
}


@dataclass(slots=True)
class LibreOfficeConversionResult:
    """
    LibreOffice 转换结果

    职责：
    - 暴露转换后 PDF 路径
    - 标记本次是否复用缓存
    - 为后续资产落库提供文件名信息
    """

    pdf_path: str
    reused: bool
    source_path: str


class LibreOfficeConversionService:
    """
    LibreOffice 转换服务

    职责：
    - 识别 Office 可转换格式
    - 调用本机 soffice CLI 执行无界面转换
    - 对超时、缺失和输出异常返回标准业务错误
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def should_convert(self, storage_path: str) -> bool:
        """判断当前文件是否需要先转换为 PDF。"""

        return Path(storage_path).suffix.lower() in OFFICE_CONVERTIBLE_SUFFIXES

    def convert(self, storage_path: str, document_id: int, version_no: int) -> LibreOfficeConversionResult:
        """
        将 Office 文档转换为 PDF。

        参数:
            storage_path: 原始文件路径
            document_id: 文档ID
            version_no: 文档版本号

        返回:
            转换结果对象
        """

        source_path = self.settings.resolve_local_path(storage_path)
        if not source_path.is_file():
            raise AppException("待转换的原始文件不存在，无法执行 LibreOffice 转换", status_code=400, code=400)
        if not self.should_convert(storage_path):
            raise AppException("当前文件类型不需要 LibreOffice 转换", status_code=400, code=400)

        binary = self._resolve_binary()
        output_dir = self.settings.libreoffice_work_path / str(document_id) / f"v{version_no}" / "converted"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_pdf = output_dir / f"{source_path.stem}.pdf"

        if output_pdf.exists() and output_pdf.is_file() and output_pdf.stat().st_size > 0:
            logger.info(
                "复用 LibreOffice 转换缓存: document_id=%s version_no=%s source=%s pdf=%s",
                document_id,
                version_no,
                source_path.name,
                output_pdf,
            )
            return LibreOfficeConversionResult(pdf_path=str(output_pdf), reused=True, source_path=str(source_path))

        command = [
            binary,
            "--headless",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(source_path),
        ]
        logger.info(
            "开始执行 LibreOffice 转换: document_id=%s version_no=%s source=%s output_dir=%s timeout_seconds=%s",
            document_id,
            version_no,
            source_path.name,
            output_dir,
            self.settings.libreoffice_timeout_seconds,
        )

        try:
            completed = subprocess.run(
                command,
                check=False,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.settings.libreoffice_timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            logger.exception("LibreOffice 转换超时: document_id=%s version_no=%s source=%s", document_id, version_no, source_path.name)
            raise AppException(
                f"LibreOffice 转换超时：file={source_path.name} timeout_seconds={self.settings.libreoffice_timeout_seconds}",
                status_code=504,
                code=504,
            ) from exc
        except OSError as exc:
            logger.exception("LibreOffice 转换执行失败: document_id=%s version_no=%s source=%s", document_id, version_no, source_path.name)
            raise AppException(f"LibreOffice 转换执行失败：file={source_path.name} error={exc}", status_code=500, code=500) from exc

        if completed.returncode != 0:
            logger.error(
                "LibreOffice 转换失败: document_id=%s version_no=%s source=%s returncode=%s stdout=%s stderr=%s",
                document_id,
                version_no,
                source_path.name,
                completed.returncode,
                completed.stdout[:1000],
                completed.stderr[:1000],
            )
            raise AppException(
                f"LibreOffice 转换失败：file={source_path.name} returncode={completed.returncode}",
                status_code=500,
                code=500,
            )

        if not output_pdf.exists() or output_pdf.stat().st_size <= 0:
            logger.error(
                "LibreOffice 转换后未生成有效 PDF: document_id=%s version_no=%s source=%s expected_pdf=%s",
                document_id,
                version_no,
                source_path.name,
                output_pdf,
            )
            raise AppException(f"LibreOffice 转换失败：未生成 PDF 文件 file={source_path.name}", status_code=500, code=500)

        logger.info(
            "LibreOffice 转换完成: document_id=%s version_no=%s source=%s pdf=%s",
            document_id,
            version_no,
            source_path.name,
            output_pdf,
        )
        return LibreOfficeConversionResult(pdf_path=str(output_pdf), reused=False, source_path=str(source_path))

    def _resolve_binary(self) -> str:
        """解析 LibreOffice CLI 可执行文件路径。"""

        configured = self.settings.libreoffice_binary.strip()
        if not configured:
            raise AppException("未配置 LIBREOFFICE_BINARY，无法执行 Office 转 PDF", status_code=500, code=500)

        configured_path = Path(configured)
        if configured_path.exists():
            return str(configured_path)

        resolved = shutil.which(configured)
        if resolved:
            return resolved

        raise AppException(f"未找到 LibreOffice 可执行文件：{configured}", status_code=500, code=500)
