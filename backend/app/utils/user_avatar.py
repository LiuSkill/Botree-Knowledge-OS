"""
User Avatar Utilities

负责：
1. 统一生成受鉴权保护的用户头像访问地址
2. 避免接口和服务层散落头像 URL 拼接规则
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.models.user import User


def avatar_url_for_user(user: User) -> str | None:
    """
    生成用户头像访问地址。

    说明：
        头像文件不公开静态暴露，前端需携带登录态通过该地址读取。
    """

    if not user.avatar_object_key:
        return None
    return f"{get_settings().api_prefix}/users/{user.id}/avatar"
