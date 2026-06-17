"""
Milvus Client

负责：
1. 根据 .env 创建真实 Milvus 连接
2. 为索引和检索模块提供统一连接入口
3. 在配置缺失或依赖缺失时给出明确异常
"""

from app.core.config import get_settings
from app.core.exceptions import AppException


def get_milvus_connection_alias() -> str:
    """
    获取 Milvus 连接别名。

    返回:
        已连接 Milvus 的 alias。
    """

    settings = get_settings()
    if not settings.milvus_enabled:
        raise AppException("未配置 MILVUS_HOST，无法连接真实 Milvus", status_code=500, code=500)
    try:
        from pymilvus import connections
    except Exception as exc:
        raise AppException("当前环境缺少 pymilvus，无法连接真实 Milvus", status_code=500, code=500) from exc

    alias = "botree_milvus"
    connections.connect(alias=alias, host=settings.milvus_host, port=str(settings.milvus_port))
    return alias
