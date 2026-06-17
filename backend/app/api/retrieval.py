"""
Retrieval API

负责：
1. 知识检索接口
2. 返回引用来源
3. 供 AI 中心和知识中心复用
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.retrieval import RetrievalDebugRequest, RetrievalSearchRequest
from app.services.retrieval_service import RetrievalService

router = APIRouter(prefix="/retrieval", tags=["知识检索"])


@router.post("/search", summary="知识检索")
def search(payload: RetrievalSearchRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """执行知识检索。"""

    return success(
        RetrievalService(db).search(
            payload.query,
            payload.mode,
            payload.project_id,
            current_user,
            payload.limit,
            payload.chat_type,
            "planner",
        )
    )


@router.post("/debug", summary="检索调试")
def debug(payload: RetrievalDebugRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """执行检索调试，返回多路召回、重排和证据信息。"""

    return success(
        RetrievalService(db).search(
            payload.query,
            payload.mode,
            payload.project_id,
            current_user,
            payload.limit,
            payload.chat_type,
            payload.execution_mode,
        )
    )
