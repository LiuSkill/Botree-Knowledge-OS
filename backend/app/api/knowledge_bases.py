"""
Knowledge Bases API

负责：
1. 知识库 CRUD
2. 知识库文档入口
3. 知识授权中心摘要
"""

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.document import DocumentOut
from app.schemas.knowledge_base import KnowledgeBaseCreate, KnowledgeBaseOut, KnowledgeBaseUpdate
from app.services.document_service import DocumentService
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter(prefix="/knowledge-bases", tags=["知识库"])


@router.get("", summary="知识库列表")
def list_bases(
    type: str | None = None,
    project_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询知识库列表。"""

    return success(KnowledgeBaseService(db).list_bases(current_user, type, project_id))


@router.post("", summary="创建知识库")
def create_base(payload: KnowledgeBaseCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """创建知识库。"""

    kb = KnowledgeBaseService(db).create_base(payload, current_user)
    return success(KnowledgeBaseOut.model_validate(kb).model_dump(mode="json"))


@router.get("/authorization-summary", summary="授权中心摘要")
def authorization_summary(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询授权中心摘要。"""

    return success(KnowledgeBaseService(db).authorization_summary(current_user))


@router.get("/{kb_id}", summary="知识库详情")
def get_base(kb_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询知识库详情。"""

    return success(KnowledgeBaseService(db).get_base(kb_id, current_user))


@router.put("/{kb_id}", summary="编辑知识库")
def update_base(kb_id: int, payload: KnowledgeBaseUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """编辑知识库。"""

    kb = KnowledgeBaseService(db).update_base(kb_id, payload, current_user)
    return success(KnowledgeBaseOut.model_validate(kb).model_dump(mode="json"))


@router.delete("/{kb_id}", summary="删除知识库")
def delete_base(kb_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """删除知识库。"""

    KnowledgeBaseService(db).delete_base(kb_id, current_user)
    return success({"deleted": True})


@router.post("/{kb_id}/documents/upload", summary="上传资料")
async def upload_document(
    kb_id: int,
    file: UploadFile = File(...),
    category_id: int = Form(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """上传资料到知识库。"""

    document = await DocumentService(db).upload_document(kb_id, file, current_user, category_id)
    return success(DocumentOut.model_validate(document).model_dump(mode="json"))


@router.get("/{kb_id}/documents", summary="知识库文档")
def list_documents(
    kb_id: int,
    category_id: int | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict:
    """查询知识库文档。"""

    documents = DocumentService(db).list_documents(current_user, knowledge_base_id=kb_id, category_id=category_id)
    return success([DocumentOut.model_validate(item).model_dump(mode="json") for item in documents])
