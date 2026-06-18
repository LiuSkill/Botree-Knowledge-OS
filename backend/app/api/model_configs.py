"""
Model Config API

负责：
1. 模型配置 CRUD
2. 模型测试
3. 默认模型设置
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import require_admin
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.model_config import ModelConfigCreate, ModelConfigOut, ModelConfigUpdate
from app.services.model_service import ModelService

router = APIRouter(prefix="/model-configs", tags=["模型配置"])


@router.get("", summary="模型配置列表")
def list_configs(
    keyword: str | None = None,
    model_type: str | None = None,
    enabled: bool | None = None,
    is_default: bool | None = None,
    page: int = 1,
    page_size: int = 10,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
) -> dict:
    """查询模型配置列表。"""

    result = ModelService(db).list_config_page(
        keyword=keyword,
        model_type=model_type,
        enabled=enabled,
        is_default=is_default,
        page=page,
        page_size=page_size,
    )
    return success(
        {
            **result,
            "items": [ModelConfigOut.model_validate(item).model_dump(mode="json") for item in result["items"]],
        }
    )


@router.post("", summary="新增模型配置")
def create_config(payload: ModelConfigCreate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """新增模型配置。"""

    config = ModelService(db).create_config(payload, current_user)
    return success(ModelConfigOut.model_validate(config).model_dump(mode="json"))


@router.put("/{config_id}", summary="编辑模型配置")
def update_config(config_id: int, payload: ModelConfigUpdate, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """编辑模型配置。"""

    config = ModelService(db).update_config(config_id, payload, current_user)
    return success(ModelConfigOut.model_validate(config).model_dump(mode="json"))


@router.delete("/{config_id}", summary="删除模型配置")
def delete_config(config_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """删除模型配置。"""

    ModelService(db).delete_config(config_id, current_user)
    return success({"deleted": True})


@router.post("/{config_id}/test", summary="测试模型配置")
def test_config(config_id: int, _: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """测试模型配置。"""

    return success(ModelService(db).test_config(config_id))


@router.post("/{config_id}/set-default", summary="设为默认模型")
def set_default(config_id: int, current_user: User = Depends(require_admin), db: Session = Depends(get_db)) -> dict:
    """设置默认模型。"""

    config = ModelService(db).set_default(config_id, current_user)
    return success(ModelConfigOut.model_validate(config).model_dump(mode="json"))
