"""
Knowledge Categories API

负责：
1. 提供企业知识和项目资料分类树查询接口
2. 提供分类创建、编辑、删除接口
3. 保持 Controller 层只做参数接收和响应转换
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_permission
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.knowledge_category import KnowledgeCategoryCreate, KnowledgeCategoryOut, KnowledgeCategoryUpdate
from app.services.knowledge_category_service import KnowledgeCategoryService

router = APIRouter(prefix="/knowledge-categories", tags=["知识分类"])


@router.get("", summary="知识分类树")
def list_categories(
    scope_type: str,
    project_id: int | None = None,
    current_user: User = Depends(require_permission("knowledge:view")),
    db: Session = Depends(get_db),
) -> dict:
    """查询企业或项目范围内的知识分类树。"""

    tree = KnowledgeCategoryService(db).list_tree(current_user, scope_type, project_id)
    return success([KnowledgeCategoryOut.model_validate(item).model_dump(mode="json") for item in tree])


@router.post("", summary="创建知识分类")
def create_category(
    payload: KnowledgeCategoryCreate,
    current_user: User = Depends(require_permission("knowledge:update")),
    db: Session = Depends(get_db),
) -> dict:
    """创建知识分类。"""

    category = KnowledgeCategoryService(db).create_category(payload, current_user)
    tree = KnowledgeCategoryService(db).list_tree(current_user, category.scope_type, category.project_id)
    return success({"category_id": category.id, "tree": [KnowledgeCategoryOut.model_validate(item).model_dump(mode="json") for item in tree]})


@router.put("/{category_id}", summary="编辑知识分类")
def update_category(
    category_id: int,
    payload: KnowledgeCategoryUpdate,
    current_user: User = Depends(require_permission("knowledge:update")),
    db: Session = Depends(get_db),
) -> dict:
    """编辑知识分类。"""

    category = KnowledgeCategoryService(db).update_category(category_id, payload, current_user)
    tree = KnowledgeCategoryService(db).list_tree(current_user, category.scope_type, category.project_id)
    return success({"category_id": category.id, "tree": [KnowledgeCategoryOut.model_validate(item).model_dump(mode="json") for item in tree]})


@router.delete("/{category_id}", summary="删除知识分类")
def delete_category(category_id: int, current_user: User = Depends(require_permission("knowledge:update")), db: Session = Depends(get_db)) -> dict:
    """删除知识分类。"""

    KnowledgeCategoryService(db).delete_category(category_id, current_user)
    return success({"deleted": True})
