"""
Projects API

负责：
1. 项目 CRUD
2. 项目成员管理
3. 项目级权限隔离
"""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.response import success
from app.models.user import User
from app.schemas.project import ProjectCreate, ProjectMemberCreate, ProjectMemberOut, ProjectUpdate
from app.services.project_service import ProjectService

router = APIRouter(prefix="/projects", tags=["项目中心"])


@router.get("", summary="项目列表")
def list_projects(keyword: str | None = None, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询当前用户可访问项目。"""

    return success(ProjectService(db).list_projects(current_user, keyword))


@router.post("", summary="创建项目")
def create_project(payload: ProjectCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """创建项目。"""

    return success(ProjectService(db).create_project(payload, current_user))


@router.get("/{project_id}", summary="项目详情")
def get_project(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询项目详情。"""

    return success(ProjectService(db).get_project(project_id, current_user))


@router.put("/{project_id}", summary="编辑项目")
def update_project(project_id: int, payload: ProjectUpdate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """编辑项目。"""

    return success(ProjectService(db).update_project(project_id, payload, current_user))


@router.delete("/{project_id}", summary="删除项目")
def delete_project(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """删除项目。"""

    ProjectService(db).delete_project(project_id, current_user)
    return success({"deleted": True})


@router.get("/{project_id}/members", summary="项目成员")
def list_members(project_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """查询项目成员。"""

    members = ProjectService(db).list_members(project_id, current_user)
    return success([ProjectMemberOut.model_validate(item).model_dump(mode="json") for item in members])


@router.post("/{project_id}/members", summary="新增项目成员")
def add_member(project_id: int, payload: ProjectMemberCreate, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """新增项目成员。"""

    member = ProjectService(db).add_member(project_id, payload, current_user)
    return success(ProjectMemberOut.model_validate(member).model_dump(mode="json"))


@router.delete("/{project_id}/members/{user_id}", summary="删除项目成员")
def delete_member(project_id: int, user_id: int, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> dict:
    """删除项目成员。"""

    ProjectService(db).delete_member(project_id, user_id, current_user)
    return success({"deleted": True})
