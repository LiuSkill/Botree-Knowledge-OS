"""Department Service."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.department import Department
from app.models.user import User
from app.repositories.department_repository import DepartmentRepository
from app.repositories.user_repository import UserRepository
from app.schemas.department import DepartmentCreate, DepartmentStatusUpdate, DepartmentUpdate
from app.services.system_service import SystemService


class DepartmentService:
    """部门业务服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.department_repository = DepartmentRepository(db)
        self.user_repository = UserRepository(db)

    def list_departments(
        self,
        keyword: str | None = None,
        status: str | None = None,
        parent_id: int | None = None,
    ) -> list[dict]:
        """查询部门平铺列表。"""

        self._validate_status_filter(status)
        return [
            self._department_to_dict(department)
            for department in self.department_repository.list(keyword=keyword, status=status, parent_id=parent_id)
        ]

    def list_department_tree(self, keyword: str | None = None, status: str | None = None) -> list[dict]:
        """查询部门树。"""

        self._validate_status_filter(status)
        departments = self.department_repository.list(keyword=keyword, status=status)
        return self._build_tree(departments)

    def get_department(self, department_id: int) -> dict:
        """查询部门详情。"""

        department = self.department_repository.get_by_id(department_id)
        if not department:
            raise AppException("部门不存在", status_code=404, code=404)
        return self._department_to_dict(department)

    def create_department(self, payload: DepartmentCreate, operator: User) -> dict:
        """创建部门。"""

        self._validate_code_unique(payload.code)
        self._validate_name_unique(payload.name, payload.parent_id)
        self._validate_parent(payload.parent_id)
        self._validate_leader(payload.leader_user_id)
        department = Department(
            name=payload.name,
            code=payload.code,
            parent_id=payload.parent_id,
            leader_user_id=payload.leader_user_id,
            sort_order=payload.sort_order,
            status=payload.status,
            description=payload.description,
            is_deleted=False,
        )
        self.department_repository.add(department)
        SystemService(self.db).record_operation(operator, "新增部门", "department", department.id, f"新增部门 {department.name}")
        self.db.commit()
        return self._department_to_dict(department)

    def update_department(self, department_id: int, payload: DepartmentUpdate, operator: User) -> dict:
        """更新部门。"""

        department = self.department_repository.get_by_id(department_id)
        if not department:
            raise AppException("部门不存在", status_code=404, code=404)

        fields_set = payload.model_fields_set
        next_name = payload.name if "name" in fields_set else department.name
        next_code = payload.code if "code" in fields_set else department.code
        next_parent_id = payload.parent_id if "parent_id" in fields_set else department.parent_id
        next_leader_user_id = payload.leader_user_id if "leader_user_id" in fields_set else department.leader_user_id

        if next_code != department.code:
            self._validate_code_unique(next_code, exclude_id=department.id)
        if next_name != department.name or next_parent_id != department.parent_id:
            self._validate_name_unique(next_name, next_parent_id, exclude_id=department.id)
        self._validate_parent(next_parent_id, current_department_id=department.id)
        self._validate_leader(next_leader_user_id)

        for field in ["name", "code", "parent_id", "leader_user_id", "sort_order", "status", "description"]:
            if field in fields_set:
                setattr(department, field, getattr(payload, field))
        if "name" in fields_set:
            self._sync_user_department_name(department)

        SystemService(self.db).record_operation(operator, "编辑部门", "department", department.id, f"编辑部门 {department.name}")
        self.db.commit()
        return self._department_to_dict(department)

    def update_status(self, department_id: int, payload: DepartmentStatusUpdate, operator: User) -> dict:
        """启用或停用部门。"""

        department = self.department_repository.get_by_id(department_id)
        if not department:
            raise AppException("部门不存在", status_code=404, code=404)
        department.status = payload.status
        action = "启用部门" if payload.status == "enabled" else "停用部门"
        SystemService(self.db).record_operation(operator, action, "department", department.id, f"{action} {department.name}")
        self.db.commit()
        return self._department_to_dict(department)

    def delete_department(self, department_id: int, operator: User) -> None:
        """软删除部门。"""

        department = self.department_repository.get_by_id(department_id)
        if not department:
            raise AppException("部门不存在", status_code=404, code=404)
        if self.department_repository.has_children(department_id):
            raise AppException("部门下存在子部门，不能删除")
        user_count = self.department_repository.count_users(department_id)
        if user_count > 0:
            raise AppException(f"部门下存在 {user_count} 个归属用户，不能删除")

        department.is_deleted = True
        department.deleted_at = datetime.utcnow()
        department.status = "disabled"
        SystemService(self.db).record_operation(operator, "删除部门", "department", department.id, f"删除部门 {department.name}")
        self.db.commit()

    def list_user_options(self) -> list[dict]:
        """查询部门负责人候选用户。"""

        return [
            {"id": user.id, "username": user.username, "real_name": user.real_name, "status": user.status}
            for user in self.user_repository.list(status="enabled")
        ]

    def _validate_status_filter(self, status: str | None) -> None:
        """校验状态筛选。"""

        if status is not None and status not in {"enabled", "disabled"}:
            raise AppException("部门状态仅支持 enabled/disabled")

    def _validate_code_unique(self, code: str, exclude_id: int | None = None) -> None:
        """校验部门编码唯一，软删除记录的编码也不可复用。"""

        exists = self.department_repository.get_by_code(code)
        if exists and exists.id != exclude_id:
            raise AppException("部门编码已存在")

    def _validate_name_unique(self, name: str, parent_id: int | None, exclude_id: int | None = None) -> None:
        """校验同一上级下部门名称唯一。"""

        if self.department_repository.exists_name_under_parent(name, parent_id, exclude_id=exclude_id):
            raise AppException("同一上级下部门名称已存在")

    def _validate_parent(self, parent_id: int | None, current_department_id: int | None = None) -> None:
        """校验上级部门存在，且不能选择自己或自己的子级。"""

        if parent_id is None:
            return
        parent = self.department_repository.get_by_id(parent_id)
        if not parent:
            raise AppException("上级部门不存在")
        if current_department_id is None:
            return
        current_parent = parent
        while current_parent:
            if current_parent.id == current_department_id:
                raise AppException("不能选择自己或自己的下级部门作为上级部门")
            if current_parent.parent_id is None:
                break
            current_parent = self.department_repository.get_by_id(current_parent.parent_id)

    def _validate_leader(self, leader_user_id: int | None) -> None:
        """校验负责人用户存在。"""

        if leader_user_id is None:
            return
        if not self.user_repository.get_by_id(leader_user_id):
            raise AppException("部门负责人不存在")

    def _build_tree(self, departments: list[Department]) -> list[dict]:
        """把部门平铺列表组装成树结构。"""

        node_by_id = {department.id: self._department_to_dict(department, include_children=True) for department in departments}
        roots: list[dict] = []
        for department in departments:
            node = node_by_id[department.id]
            if department.parent_id and department.parent_id in node_by_id:
                node_by_id[department.parent_id]["children"].append(node)
            else:
                roots.append(node)
        return roots

    def _department_to_dict(self, department: Department, include_children: bool = False) -> dict:
        """序列化部门，补齐上级和负责人名称。"""

        data = {
            "id": department.id,
            "name": department.name,
            "code": department.code,
            "parent_id": department.parent_id,
            "parent_name": department.parent.name if department.parent else None,
            "leader_user_id": department.leader_user_id,
            "leader_name": department.leader.real_name if department.leader else None,
            "sort_order": department.sort_order,
            "status": department.status,
            "description": department.description,
            "is_deleted": department.is_deleted,
            "created_at": department.created_at,
            "updated_at": department.updated_at,
        }
        if include_children:
            data["children"] = []
        return data

    def _sync_user_department_name(self, department: Department) -> None:
        """部门名称变更后同步用户冗余展示名，避免旧列表显示过期名称。"""

        for user in self.user_repository.list(department_id=department.id):
            user.department = department.name
