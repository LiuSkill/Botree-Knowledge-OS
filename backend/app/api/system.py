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
from app.schemas.system import OperationLogOut, OperationLogUserOption
from app.services.system_service import SystemService
from app.services.question_answer_trace_service import QuestionAnswerTraceService

router = APIRouter(prefix="/system", tags=["系统管理"])
health_router = APIRouter(tags=["健康检查"])


@router.get("/dashboard", summary="首页工作台统计")
def dashboard(current_user: User = Depends(require_permission("dashboard:view")), db: Session = Depends(get_db)) -> dict:
    """查询当前用户权限范围内的首页统计数据。"""

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
    user_id: int | None = None,
    username: str | None = None,
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
        user_id=user_id,
        username=username,
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


@router.get("/operation-log-users", summary="操作日志用户选项")
def operation_log_users(
    _: User = Depends(require_permission("system:log:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询操作日志筛选下拉框可选用户。"""

    users = SystemService(db).list_operation_log_user_options()
    return success([OperationLogUserOption.model_validate(item).model_dump(mode="json") for item in users])


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


@router.get("/qa-audits/{trace_id}/debugger", summary="问答 Debugger Trace")
def qa_audit_debugger(
    trace_id: str,
    offset: int = 0,
    limit: int = 100,
    include_payload: bool = False,
    business_stage: str | None = None,
    _: User = Depends(require_permission("system:qa-audit:debug")),
    db: Session = Depends(get_db),
) -> dict:
    """按需读取完整问答 Trace；权限在服务端强制校验。"""

    offset = max(offset, 0)
    limit = min(max(limit, 1), 500)
    debugger = QuestionAnswerTraceService(db).get_debugger(
        trace_id,
        offset=offset,
        limit=limit,
        include_payload=include_payload,
        business_stage=business_stage,
    )
    if debugger is None:
        return success({"trace_id": trace_id, "status": "not_found", "events": [], "stages": []})
    return success(debugger)


@router.get("/qa-audits/{trace_id}/debugger/events/{event_id}", summary="问答 Debugger 节点详情")
def qa_audit_debugger_event(
    trace_id: str,
    event_id: str,
    _: User = Depends(require_permission("system:qa-audit:debug")),
    db: Session = Depends(get_db),
) -> dict:
    """懒加载单个真实事件的完整业务载荷。"""

    event = QuestionAnswerTraceService(db).get_debugger_event(trace_id, event_id)
    if event is None:
        return success({"trace_id": trace_id, "event_id": event_id, "status": "not_found", "payload": None})
    return success(event)


@router.delete("/qa-audits/{trace_id}/debugger", summary="清理问答 Debugger Trace")
def delete_qa_audit_debugger(
    trace_id: str,
    confirm: bool = False,
    current_user: User = Depends(require_permission("system:qa-audit:cleanup")),
    db: Session = Depends(get_db),
) -> dict:
    """仅在显式确认且具备清理权限时删除 Trace，并记录操作日志。"""

    return success(SystemService(db).cleanup_question_answer_trace(trace_id, current_user, confirm=confirm))


@router.get("/qa-debugger/metrics", summary="问答 Debugger 运维指标")
def qa_debugger_metrics(
    _: User = Depends(require_permission("system:qa-audit:debug")),
    db: Session = Depends(get_db),
) -> dict:
    """返回事件聚合异常与不完整 Trace 告警信号。"""

    return success(QuestionAnswerTraceService(db).operational_metrics())


@health_router.get("/health", summary="健康检查")
def health() -> dict:
    """系统健康检查。"""

    return success({"status": "ok", "service": "botree-knowledge-backend"})
