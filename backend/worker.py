"""
Botree RQ Worker

负责：
1. 启动离线索引构建 Worker
2. 监听 .env 中配置的 RQ 队列
3. 在不同操作系统上选择兼容的 Worker 实现
"""

from __future__ import annotations

import logging
import platform
from typing import Any

from rq import SimpleWorker
from rq.timeouts import TimerDeathPenalty

from app.core.config import get_settings
from app.core.redis import get_redis_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

WINDOWS_PLATFORM = "Windows"


class WindowsSimpleWorker(SimpleWorker):
    """
    Windows 平台专用的 RQ Worker。

    说明：
    1. `rq.Worker` 依赖 `os.fork()`，Windows 环境无法使用。
    2. `rq.SimpleWorker` 虽然不再依赖 `fork`，但默认超时机制仍是
       `UnixSignalDeathPenalty`，会继续使用 `SIGALRM`。
    3. 因此这里统一切换为 `TimerDeathPenalty`，保证 Windows 下
       的任务执行和超时控制都可正常工作。
    """

    death_penalty_class = TimerDeathPenalty


def resolve_worker_class() -> type[Any]:
    """
    根据当前平台选择兼容的 RQ Worker 类型。

    返回：
        可直接实例化的 Worker 类。
    """

    from rq import Worker

    current_platform = platform.system()
    if current_platform == WINDOWS_PLATFORM:
        logger.info("检测到 Windows 平台，RQ Worker 自动切换为 WindowsSimpleWorker")
        return WindowsSimpleWorker
    return Worker


def main() -> None:
    """
    启动 RQ Worker。

    说明：
    1. Redis 未配置时直接报错，避免误以为后台任务已启动。
    2. 直接传入队列名称，由 Worker 按当前 death_penalty_class
       创建 Queue，避免复用带有 Unix 默认超时策略的旧 Queue 实例。
    """

    settings = get_settings()
    connection = get_redis_connection()
    if connection is None:
        raise RuntimeError("未配置 Redis，无法启动 RQ Worker")

    worker_class = resolve_worker_class()
    logger.info(
        "RQ Worker启动: queue=%s worker_class=%s platform=%s",
        settings.rq_queue_name,
        worker_class.__name__,
        platform.system(),
    )

    worker = worker_class([settings.rq_queue_name], connection=connection)
    worker.death_penalty_class = getattr(worker_class, "death_penalty_class", worker.death_penalty_class)
    worker.work()


if __name__ == "__main__":
    main()
