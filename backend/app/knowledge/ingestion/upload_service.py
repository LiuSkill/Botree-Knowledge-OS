"""
Upload Service

负责：
1. 保存上传文件到本地 storage/uploads
2. 返回文件大小、类型和存储路径
3. 在 MinIO 配置完整时同步写入真实对象存储
"""

import logging
from pathlib import Path
import shutil

from fastapi import UploadFile

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.minio import get_minio_client
from app.utils.file_utils import file_type, safe_storage_name

logger = logging.getLogger(__name__)


class UploadService:
    """
    文件上传服务

    职责：
    - 将上传文件持久化
    - 生成安全存储文件名
    - 同步对象存储副本
    - 返回文档元数据
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.settings.upload_path.mkdir(parents=True, exist_ok=True)

    async def save(self, upload_file: UploadFile) -> dict:
        """
        保存上传文件

        参数:
            upload_file: FastAPI 上传文件对象

        返回:
            文件元数据字典。
        """

        storage_name = safe_storage_name(upload_file.filename or "unknown")
        storage_path = self.settings.upload_path / storage_name
        content = await upload_file.read()
        storage_path.write_bytes(content)
        self._upload_to_minio(storage_name, storage_path)
        return {
            "file_name": upload_file.filename or storage_name,
            "file_type": file_type(upload_file.filename or storage_name),
            "file_size": len(content),
            "storage_path": self.settings.to_relative_local_path(storage_path),
        }

    def save_local_file(self, source_path: str | Path, original_file_name: str | None = None) -> dict:
        """
        以流式复制方式保存本地导入文件，避免大文件一次性读入内存。

        参数:
            source_path: 待导入的本地真实文件路径。
            original_file_name: 展示给业务侧的原始文件名；为空时使用源文件名。

        返回:
            文件元数据字典。
        """

        resolved_source = Path(source_path)
        if not resolved_source.is_file():
            raise AppException(f"导入源文件不存在：{resolved_source}", status_code=400, code=400)

        file_name = original_file_name or resolved_source.name
        storage_name = safe_storage_name(file_name)
        storage_path = self.settings.upload_path / storage_name
        with resolved_source.open("rb") as source, storage_path.open("wb") as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)
        self._upload_to_minio(storage_name, storage_path)
        return {
            "file_name": file_name,
            "file_type": file_type(file_name),
            "file_size": int(storage_path.stat().st_size),
            "storage_path": self.settings.to_relative_local_path(storage_path),
        }

    def remove(self, storage_path: str) -> None:
        """
        删除本地文件

        参数:
            storage_path: 文件存储路径
        """

        path = self.settings.resolve_local_path(storage_path)
        if path.exists() and path.is_file():
            path.unlink()
        self._remove_from_minio(path.name)

    def _upload_to_minio(self, object_name: str, storage_path: Path) -> None:
        """
        同步上传文件到 MinIO。

        参数:
            object_name: 对象名。
            storage_path: 本地文件路径。
        """

        client = get_minio_client()
        if client is None:
            logger.info("MinIO未启用，文件仅保存到本地真实存储: path=%s", storage_path)
            return
        client.fput_object(self.settings.minio_bucket, object_name, str(storage_path))
        logger.info("文件已同步到MinIO: bucket=%s object=%s", self.settings.minio_bucket, object_name)

    def _remove_from_minio(self, object_name: str) -> None:
        """
        从 MinIO 删除对象。

        参数:
            object_name: 对象名。
        """

        client = get_minio_client()
        if client is None:
            return
        client.remove_object(self.settings.minio_bucket, object_name)
        logger.info("MinIO对象已删除: bucket=%s object=%s", self.settings.minio_bucket, object_name)
