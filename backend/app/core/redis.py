"""
Redis Infrastructure

负责：
1. 根据 .env 创建 Redis 连接
2. 为 RQ 离线索引队列提供统一入口
3. 在未配置 Redis 时提供清晰的诊断结果
"""

import logging
from typing import Any

from app.core.config import get_settings
from app.core.exceptions import AppException

logger = logging.getLogger(__name__)


def get_redis_connection() -> Any | None:
    """
    获取 Redis 连接。

    返回:
        已连接的 Redis 客户端；未配置 Redis 时返回 None。
    """

    settings = get_settings()
    if not settings.redis_url:
        logger.info("Redis未配置，离线任务队列不可用")
        return None
    try:
        from redis import Redis
    except Exception as exc:
        raise AppException("当前环境缺少 redis 依赖，无法创建任务队列", status_code=500, code=500) from exc
    return Redis.from_url(settings.redis_url)


def get_rq_queue() -> Any | None:
    """
    获取 RQ 队列。

    返回:
        RQ Queue 对象；Redis 未配置时返回 None。
    """

    connection = get_redis_connection()
    if connection is None:
        return None
    try:
        from rq import Queue
    except Exception as exc:
        raise AppException("当前环境缺少 rq 依赖，无法创建离线索引任务", status_code=500, code=500) from exc
    return Queue(get_settings().rq_queue_name, connection=connection)
