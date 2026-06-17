"""
Project Repository

负责：
1. 项目和项目成员数据库访问
2. 支持项目级权限隔离
3. 为项目中心提供数据查询能力
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project, ProjectMember


class ProjectRepository:
    """
    项目仓储

    职责：
    - 项目 CRUD
    - 项目成员授权关系查询
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, keyword: str | None = None, user_id: int | None = None, admin: bool = False) -> list[Project]:
        """查询项目列表。"""

        stmt = select(Project).order_by(Project.id.desc())
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where((Project.name.like(like)) | (Project.code.like(like)) | (Project.client.like(like)))
        if user_id is not None and not admin:
            stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(ProjectMember.user_id == user_id)
        return list(self.db.scalars(stmt).unique().all())

    def get(self, project_id: int) -> Project | None:
        """按 ID 查询项目。"""

        return self.db.get(Project, project_id)

    def get_by_code(self, code: str) -> Project | None:
        """按项目编码查询。"""

        return self.db.scalar(select(Project).where(Project.code == code))

    def add(self, project: Project) -> Project:
        """新增项目。"""

        self.db.add(project)
        self.db.flush()
        return project

    def delete(self, project: Project) -> None:
        """删除项目。"""

        self.db.delete(project)
        self.db.flush()

    def list_members(self, project_id: int) -> list[ProjectMember]:
        """查询项目成员。"""

        return list(self.db.scalars(select(ProjectMember).where(ProjectMember.project_id == project_id)).all())

    def get_member(self, project_id: int, user_id: int) -> ProjectMember | None:
        """查询用户是否为项目成员。"""

        return self.db.scalar(
            select(ProjectMember).where(ProjectMember.project_id == project_id, ProjectMember.user_id == user_id)
        )

    def add_member(self, member: ProjectMember) -> ProjectMember:
        """新增项目成员。"""

        self.db.add(member)
        self.db.flush()
        return member

    def delete_member(self, member: ProjectMember) -> None:
        """删除项目成员。"""

        self.db.delete(member)
        self.db.flush()
