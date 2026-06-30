"""Department Repository."""

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.models.department import Department
from app.models.user import User


class DepartmentRepository:
    """部门数据库访问。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(
        self,
        keyword: str | None = None,
        status: str | None = None,
        parent_id: int | None = None,
        include_deleted: bool = False,
    ) -> list[Department]:
        """查询部门列表。"""

        stmt = (
            select(Department)
            .options(selectinload(Department.parent), selectinload(Department.leader))
            .order_by(Department.sort_order.asc(), Department.id.asc())
        )
        if not include_deleted:
            stmt = stmt.where(Department.is_deleted.is_(False))
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where((Department.name.like(like)) | (Department.code.like(like)))
        if status:
            stmt = stmt.where(Department.status == status)
        if parent_id is not None:
            stmt = stmt.where(Department.parent_id == parent_id)
        return list(self.db.scalars(stmt).all())

    def get_by_id(self, department_id: int, include_deleted: bool = False) -> Department | None:
        """按 ID 查询部门。"""

        stmt = (
            select(Department)
            .options(selectinload(Department.parent), selectinload(Department.leader))
            .where(Department.id == department_id)
        )
        if not include_deleted:
            stmt = stmt.where(Department.is_deleted.is_(False))
        return self.db.scalar(stmt)

    def get_by_code(self, code: str) -> Department | None:
        """按编码查询部门，包含软删除记录以保证编码不可复用。"""

        return self.db.scalar(select(Department).where(func.lower(Department.code) == code.lower()))

    def exists_name_under_parent(self, name: str, parent_id: int | None, exclude_id: int | None = None) -> bool:
        """检查同一上级下部门名称是否重复。"""

        stmt = select(Department.id).where(
            Department.is_deleted.is_(False),
            Department.parent_id.is_(parent_id) if parent_id is None else Department.parent_id == parent_id,
            func.lower(Department.name) == name.lower(),
        )
        if exclude_id is not None:
            stmt = stmt.where(Department.id != exclude_id)
        return self.db.scalar(stmt.limit(1)) is not None

    def has_children(self, department_id: int) -> bool:
        """检查部门是否存在未删除子部门。"""

        stmt = select(Department.id).where(Department.parent_id == department_id, Department.is_deleted.is_(False)).limit(1)
        return self.db.scalar(stmt) is not None

    def count_users(self, department_id: int) -> int:
        """统计直属归属用户数量。"""

        return int(self.db.scalar(select(func.count(User.id)).where(User.department_id == department_id)) or 0)

    def list_descendant_ids(self, department_id: int) -> list[int]:
        """查询部门的所有未删除子孙部门 ID，用于用户列表包含子部门筛选。"""

        departments = self.list()
        children_by_parent: dict[int, list[int]] = {}
        for department in departments:
            if department.parent_id is None:
                continue
            children_by_parent.setdefault(department.parent_id, []).append(department.id)

        descendant_ids: list[int] = []
        pending = list(children_by_parent.get(department_id, []))
        while pending:
            current_id = pending.pop(0)
            descendant_ids.append(current_id)
            pending.extend(children_by_parent.get(current_id, []))
        return descendant_ids

    def add(self, department: Department) -> Department:
        """新增部门。"""

        self.db.add(department)
        self.db.flush()
        return department
