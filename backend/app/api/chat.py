"""
Chat API

负责：
1. 问答会话管理
2. 知识问答同步与流式接口
3. 返回答案、引用来源和 Agent 执行过程
"""

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, require_permission
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.chat import ChatCompletionRequest, ChatMessageFeedbackUpdate, ChatSessionCreate, ChatSessionOut
from app.services.chat_service import ChatService

router = APIRouter(prefix="/chat", tags=["AI中心"])


@router.get("/sessions", summary="会话列表")
def list_sessions(
    chat_type: str | None = None,
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询当前用户会话列表。"""

    sessions = ChatService(db).list_sessions(current_user, chat_type, project_id)
    return success([ChatSessionOut.model_validate(item).model_dump(mode="json") for item in sessions])


@router.post("/sessions", summary="创建会话")
def create_session(payload: ChatSessionCreate, current_user: User = Depends(require_permission("ai:chat")), db: Session = Depends(get_db)) -> dict:
    """创建问答会话。"""

    session = ChatService(db).create_session(payload, current_user)
    return success(ChatSessionOut.model_validate(session).model_dump(mode="json"))


@router.get("/sessions/{session_id}/messages", summary="会话消息")
def list_messages(session_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询会话消息。"""

    messages = ChatService(db).list_messages(session_id, current_user)
    return success(messages)


@router.get("/messages/{message_id}/trace", summary="问答检索轨迹")
def message_trace(message_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询指定助手消息对应的 LangGraph 检索执行轨迹。"""

    return success(ChatService(db).message_trace(message_id, current_user))


@router.patch("/messages/{message_id}/feedback", summary="更新回答反馈")
def update_message_feedback(
    message_id: int,
    payload: ChatMessageFeedbackUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """更新指定助手回答的点赞/点踩反馈。"""

    return success(ChatService(db).update_message_feedback(message_id, payload, current_user))


@router.delete("/sessions/{session_id}", summary="删除会话")
def delete_session(session_id: int, current_user: User = Depends(require_permission("ai:delete-session")), db: Session = Depends(get_db)) -> dict:
    """删除问答会话。"""

    ChatService(db).delete_session(session_id, current_user)
    return success({"deleted": True})


@router.post("/completions", summary="知识问答")
def completions(payload: ChatCompletionRequest, current_user: User = Depends(require_permission("ai:chat")), db: Session = Depends(get_db)) -> dict:
    """执行同步知识问答。"""

    return success(ChatService(db).complete(payload, current_user))


@router.post("/completions/stream", summary="知识问答流式输出")
def completions_stream(
    payload: ChatCompletionRequest,
    current_user: User = Depends(require_permission("ai:chat")),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    """执行流式知识问答。"""

    stream = ChatService(db).complete_stream(payload, current_user)
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
