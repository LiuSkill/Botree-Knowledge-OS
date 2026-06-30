"""
System API

负责：
1. 工作台统计
2. 操作日志
3. 问答审计和健康检查
"""

from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.system import OperationLogOut
from app.services.system_service import SystemService

router = APIRouter(prefix="/system", tags=["系统管理"])
health_router = APIRouter(tags=["健康检查"])


@router.get("/dashboard", summary="首页工作台统计")
def dashboard(current_user: User = Depends(require_permission("dashboard:view")), db: Session = Depends(get_db)) -> dict:
    """查询首页统计和最近数据。"""

    return success(SystemService(db).dashboard(current_user))


@router.get("/menus", summary="系统菜单权限树")
def menus(_: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询后端注册的真实菜单路由树。"""

    return success(SystemService(db).list_menus())


@router.get("/permissions/actions", summary="按钮级权限清单")
def action_permissions(_: User = Depends(require_permission("system:permission:view")), db: Session = Depends(get_db)) -> dict:
    """查询当前系统所有按钮级权限。"""

    return success(SystemService(db).list_action_permissions())


@router.get("/operation-logs", summary="操作日志")
def operation_logs(
    keyword: str | None = None,
    result: str | None = None,
    target_type: str | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("system:log:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询操作日志。"""

    logs = SystemService(db).list_logs(
        keyword=keyword,
        result=result,
        target_type=target_type,
        started_at=started_at,
        ended_at=ended_at,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            **logs,
            "items": [OperationLogOut.model_validate(item).model_dump(mode="json") for item in logs["items"]],
        }
    )


@router.get("/qa-audit-sessions", summary="问答会话审计")
def qa_audit_sessions(
    user_id: int | None = None,
    project_id: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("system:qa-audit:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询用户会话维度的问答审计。"""

    return success(
        SystemService(db).qa_audit_sessions(
            user_id=user_id,
            project_id=project_id,
            started_at=started_at,
            ended_at=ended_at,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/qa-audits", summary="问答审计")
def qa_audits(
    user_id: int | None = None,
    project_id: int | None = None,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
    feedback_status: str | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_permission("system:qa-audit:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询问答审计。"""

    return success(
        SystemService(db).qa_audits(
            user_id=user_id,
            project_id=project_id,
            started_at=started_at,
            ended_at=ended_at,
            feedback_status=feedback_status,
            page=page,
            page_size=page_size,
        )
    )


@router.get("/retrieval-traces", summary="检索链路审计")
def retrieval_traces(_: User = Depends(require_permission("system:qa-audit:view")), db: Session = Depends(get_db)) -> dict:
    """查询 LangGraph 检索链路审计记录。"""

    return success(SystemService(db).retrieval_traces())


@health_router.get("/health", summary="健康检查")
def health() -> dict:
    """系统健康检查。"""

    return success({"status": "ok", "service": "botree-knowledge-backend"})
