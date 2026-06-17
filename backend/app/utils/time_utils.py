"""
Time Utilities

负责：
1. 提供统一时间函数
2. 避免业务层直接散落 datetime 调用
3. 便于后续统一时区策略
"""

from datetime import datetime


def now_utc() -> datetime:
    """
    获取当前 UTC 时间

    返回:
        当前 UTC datetime。
    """

    return datetime.utcnow()
