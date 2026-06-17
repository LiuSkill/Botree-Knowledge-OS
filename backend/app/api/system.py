"""
System API

负责：
1. 工作台统计
2. 操作日志
3. 问答审计和健康检查
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_admin
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.system import OperationLogOut
from app.services.system_service import SystemService

router = APIRouter(prefix="/system", tags=["系统管理"])
health_router = APIRouter(tags=["健康检查"])


@router.get("/dashboard", summary="首页工作台统计")
def dashboard(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询首页统计和最近数据。"""

    return success(SystemService(db).dashboard(current_user))


@router.get("/operation-logs", summary="操作日志")
def operation_logs(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """查询操作日志。"""

    logs = SystemService(db).list_logs()
    return success([OperationLogOut.model_validate(item).model_dump(mode="json") for item in logs])


@router.get("/qa-audits", summary="问答审计")
def qa_audits(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """查询问答审计。"""

    return success(SystemService(db).qa_audits())


@router.get("/retrieval-traces", summary="检索链路审计")
def retrieval_traces(_: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """查询 LangGraph 检索链路审计记录。"""

    return success(SystemService(db).retrieval_traces())


@health_router.get("/health", summary="健康检查")
def health() -> dict:
    """系统健康检查。"""

    return success({"status": "ok", "service": "botree-knowledge-backend"})
