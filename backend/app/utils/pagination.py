"""
Pagination Utilities

负责：
1. 提供简单分页函数
2. 统一列表接口分页结构
3. MVP 阶段为前端分页预留能力
"""

from typing import TypeVar

T = TypeVar("T")


def paginate(items: list[T], page: int = 1, page_size: int = 20) -> dict:
    """
    对列表分页

    参数:
        items: 原始列表
        page: 页码
        page_size: 每页数量

    返回:
        包含 total/items/page/page_size 的分页对象。
    """

    safe_page = max(page, 1)
    safe_size = max(min(page_size, 100), 1)
    start = (safe_page - 1) * safe_size
    return {"total": len(items), "page": safe_page, "page_size": safe_size, "items": items[start : start + safe_size]}
