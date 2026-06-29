"""Request-scoped audit context."""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass


@dataclass(frozen=True)
class RequestAuditContext:
    """保存当前请求的最小审计上下文，供 Service 层日志自动补齐。"""

    ip_address: str | None = None
    user_agent: str | None = None
    method: str | None = None
    path: str | None = None


_request_audit_context: ContextVar[RequestAuditContext | None] = ContextVar("request_audit_context", default=None)


def set_request_audit_context(context: RequestAuditContext) -> Token[RequestAuditContext | None]:
    return _request_audit_context.set(context)


def reset_request_audit_context(token: Token[RequestAuditContext | None]) -> None:
    _request_audit_context.reset(token)


def current_audit_context() -> RequestAuditContext | None:
    return _request_audit_context.get()
