"""
Application Exceptions

负责：
1. 定义业务异常类型
2. 统一转换为标准 API 响应
3. 避免 Controller 层吞掉异常
"""

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError

from app.core.response import fail

logger = logging.getLogger(__name__)

MYSQL_LOCK_ERROR_CODES = {1205, 1213}


class AppException(Exception):
    """
    业务异常

    职责：
    - 表达可预期的业务错误
    - 携带 HTTP 状态码和业务错误码
    """

    def __init__(self, message: str, status_code: int = 400, code: int = 400, data: Any = None) -> None:
        self.message = message
        self.status_code = status_code
        self.code = code
        self.data = data
        super().__init__(message)


def is_database_lock_error(exc: BaseException) -> bool:
    """
    判断数据库异常是否为可重试的锁等待/死锁。

    MySQL 1205/1213 通常由并发任务短暂争用同一业务记录导致，应转换为业务提示，
    避免把 SQL 和内部堆栈暴露给前端。
    """

    if not isinstance(exc, OperationalError):
        return False

    orig = getattr(exc, "orig", None)
    args = getattr(orig, "args", ())
    if args and isinstance(args[0], int) and args[0] in MYSQL_LOCK_ERROR_CODES:
        return True

    message = str(orig or exc).lower()
    return "lock wait timeout exceeded" in message or "deadlock found" in message


def register_exception_handlers(app: FastAPI) -> None:
    """
    注册全局异常处理器

    参数:
        app: FastAPI 应用实例
    """

    @app.exception_handler(AppException)
    async def handle_app_exception(_: Request, exc: AppException) -> JSONResponse:
        logger.warning("业务异常: %s", exc.message)
        return JSONResponse(status_code=exc.status_code, content=fail(exc.message, exc.code, exc.data))

    @app.exception_handler(HTTPException)
    async def handle_http_exception(_: Request, exc: HTTPException) -> JSONResponse:
        logger.warning("HTTP异常: %s", exc.detail)
        return JSONResponse(status_code=exc.status_code, content=fail(str(exc.detail), exc.status_code))

    @app.exception_handler(OperationalError)
    async def handle_operational_error(request: Request, exc: OperationalError) -> JSONResponse:
        if is_database_lock_error(exc):
            logger.warning(
                "数据库锁等待异常: method=%s path=%s status=%s",
                request.method,
                request.url.path,
                "lock_wait_timeout",
            )
            return JSONResponse(status_code=409, content=fail("当前数据正在被其他任务处理，请稍后重试", 409))

        logger.error(
            "数据库操作异常: method=%s path=%s error_type=%s",
            request.method,
            request.url.path,
            type(getattr(exc, "orig", exc)).__name__,
        )
        return JSONResponse(status_code=500, content=fail("系统异常，请联系管理员", 500))

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("未处理异常: %s", exc)
        return JSONResponse(status_code=500, content=fail("系统异常，请联系管理员", 500))
