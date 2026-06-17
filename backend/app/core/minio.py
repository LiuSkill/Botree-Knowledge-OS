"""
MinIO Client

负责：
1. 根据 .env 创建真实 MinIO 客户端
2. 确保对象存储 Bucket 可用
3. 为上传服务提供统一对象存储入口
"""

from app.core.config import get_settings
from app.core.exceptions import AppException


def get_minio_client():
    """
    获取 MinIO 客户端。

    返回:
        配置完整时返回真实 MinIO 客户端；未启用时返回 None。
    """

    settings = get_settings()
    if not settings.minio_enabled:
        return None
    try:
        from minio import Minio
    except Exception as exc:
        raise AppException("当前环境缺少 minio，无法连接真实对象存储", status_code=500, code=500) from exc

    client = Minio(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
    )
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
    return client
