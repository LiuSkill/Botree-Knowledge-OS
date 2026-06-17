"""
Unified API Response

负责：
1. 生成统一接口返回格式
2. 降低前端处理响应结构的复杂度
3. 让错误和成功响应保持一致
"""

from typing import Any


def success(data: Any = None, message: str = "success") -> dict[str, Any]:
    """
    生成成功响应

    参数:
        data: 业务数据
        message: 成功提示

    返回:
        标准 API 响应对象。
    """

    return {"code": 0, "message": message, "data": data}


def fail(message: str, code: int = 400, data: Any = None) -> dict[str, Any]:
    """
    生成失败响应

    参数:
        message: 错误提示
        code: 错误码
        data: 附加错误数据

    返回:
        标准 API 错误对象。
    """

    return {"code": code, "message": message, "data": data}
