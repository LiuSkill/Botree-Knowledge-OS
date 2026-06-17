"""
Reviews API

负责：
1. 审核任务列表和详情
2. 审核通过、驳回
3. 审核日志查询
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.document import DocumentOut
from app.schemas.review import ReviewDecisionRequest, ReviewLogOut, ReviewTaskOut
from app.services.review_service import ReviewService

router = APIRouter(prefix="/review-tasks", tags=["审核中心"])


@router.get("", summary="审核任务列表")
def list_tasks(status: str | None = None, _: User = Depends(require_permission("review:view")), db: Session = Depends(get_db)) -> dict:
    """查询审核任务列表。"""

    tasks = ReviewService(db).list_tasks(status)
    return success([ReviewTaskOut.model_validate(item).model_dump(mode="json") for item in tasks])


@router.get("/approved-documents", summary="审核通过资料")
def list_approved_documents(
    scope_type: str | None = None,
    project_id: int | None = None,
    category_id: int | None = None,
    index_status: str | None = None,
    keyword: str | None = None,
    current_user: User = Depends(require_permission("review:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询已审核通过并可构建索引的资料。"""

    documents = ReviewService(db).list_approved_documents(current_user, scope_type, project_id, category_id, index_status, keyword)
    return success([DocumentOut.model_validate(item).model_dump(mode="json") for item in documents])


@router.get("/{task_id}", summary="审核任务详情")
def get_task(task_id: int, _: User = Depends(require_permission("review:view")), db: Session = Depends(get_db)) -> dict:
    """查询审核任务详情。"""

    task = ReviewService(db).get_task(task_id)
    return success(ReviewTaskOut.model_validate(task).model_dump(mode="json"))


@router.post("/{task_id}/approve", summary="审核通过")
def approve(task_id: int, payload: ReviewDecisionRequest | None = None, current_user: User = Depends(require_permission("review:review")), db: Session = Depends(get_db)) -> dict:
    """审核通过。"""

    task = ReviewService(db).approve(task_id, current_user, payload.comment if payload else None)
    return success(ReviewTaskOut.model_validate(task).model_dump(mode="json"))


@router.post("/{task_id}/reject", summary="审核驳回")
def reject(task_id: int, payload: ReviewDecisionRequest | None = None, current_user: User = Depends(require_permission("review:review")), db: Session = Depends(get_db)) -> dict:
    """审核驳回。"""

    task = ReviewService(db).reject(task_id, current_user, payload.comment if payload else None)
    return success(ReviewTaskOut.model_validate(task).model_dump(mode="json"))


document_review_router = APIRouter(prefix="/documents", tags=["审核日志"])


@document_review_router.get("/{document_id}/review-logs", summary="文档审核日志")
def list_review_logs(document_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询文档审核日志。"""

    logs = ReviewService(db).list_logs(document_id, current_user)
    return success([ReviewLogOut.model_validate(item).model_dump(mode="json") for item in logs])
