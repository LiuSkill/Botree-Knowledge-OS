"""
LibreOffice Conversion Service

负责：
1. 将 Office 非 PDF 文档转换为 PDF
2. 复用同一文档版本的转换结果，避免重复执行 CLI
3. 为 MinerU 解析准备稳定、可追踪的 PDF 输入
"""

from __future__ import annotations

import logging
import os
import shutil
import signal
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)
PROCESS_TERMINATE_GRACE_SECONDS = 5

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

        self._cleanup_stale_target_artifacts(output_dir, output_pdf)

        profile_dir = Path(tempfile.mkdtemp(prefix=".libreoffice-profile-", dir=str(output_dir)))
        command = self._build_command(binary, output_dir, source_path, profile_dir)
        logger.info(
            "开始执行 LibreOffice 转换: document_id=%s version_no=%s source=%s output_dir=%s timeout_seconds=%s profile_dir=%s",
            document_id,
            version_no,
            source_path.name,
            output_dir,
            self.settings.libreoffice_timeout_seconds,
            profile_dir,
        )

        try:
            completed = self._run_command(command, self.settings.libreoffice_timeout_seconds)
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
        finally:
            shutil.rmtree(profile_dir, ignore_errors=True)

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

    def _build_command(self, binary: str, output_dir: Path, source_path: Path, profile_dir: Path) -> list[str]:
        """构建带独立用户 profile 的 LibreOffice 转换命令。"""

        profile_uri = profile_dir.resolve().as_uri()
        return [
            binary,
            f"-env:UserInstallation={profile_uri}",
            "--headless",
            "--nologo",
            "--nofirststartwizard",
            "--nodefault",
            "--norestore",
            "--nolockcheck",
            "--convert-to",
            "pdf",
            "--outdir",
            str(output_dir),
            str(source_path),
        ]

    def _run_command(self, command: list[str], timeout_seconds: int) -> subprocess.CompletedProcess[str]:
        """运行 LibreOffice 命令，并在超时时终止整个进程组。"""

        popen_kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "shell": False,
        }
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True

        process = subprocess.Popen(command, **popen_kwargs)
        try:
            stdout, stderr = process.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            self._terminate_process_tree(process)
            raise

        return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)

    def _terminate_process_tree(self, process: subprocess.Popen[str]) -> None:
        """终止 LibreOffice launcher 以及它派生出的 soffice.bin。"""

        if process.poll() is not None:
            return

        try:
            if os.name == "nt":
                process.terminate()
            else:
                os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        except OSError:
            logger.warning("LibreOffice 进程组 SIGTERM 失败，尝试终止主进程: pid=%s", process.pid, exc_info=True)
            process.terminate()

        try:
            process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
            return
        except subprocess.TimeoutExpired:
            pass

        try:
            if os.name == "nt":
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            logger.warning("LibreOffice 进程组 SIGKILL 失败，尝试强杀主进程: pid=%s", process.pid, exc_info=True)
            process.kill()

        try:
            process.wait(timeout=PROCESS_TERMINATE_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            logger.error("LibreOffice 进程超时后仍未退出: pid=%s", process.pid)

    def _cleanup_stale_target_artifacts(self, output_dir: Path, output_pdf: Path) -> None:
        """清理当前目标 PDF 的陈旧 LibreOffice 锁文件。"""

        if output_pdf.exists() and output_pdf.is_file() and output_pdf.stat().st_size <= 0:
            output_pdf.unlink(missing_ok=True)

        lock_path = output_dir / f".~lock.{output_pdf.name}#"
        lock_path.unlink(missing_ok=True)
