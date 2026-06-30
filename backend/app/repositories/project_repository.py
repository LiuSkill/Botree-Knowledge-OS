"""Project repository."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import String, and_, case, cast, false, func, literal, or_, select
from sqlalchemy.orm import Session

from app.core.data_scope import DATA_SCOPE_ALL, DATA_SCOPE_DEPARTMENT, DATA_SCOPE_OWN, DATA_SCOPE_PUBLIC_ONLY
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.models.project import Project, ProjectMember


@dataclass(frozen=True)
class ProjectListStatsRow:
    """项目列表聚合行，避免 Service 层为了统计字段循环查询。"""

    project: Project
    knowledge_base_id: int | None
    document_count: int
    knowledge_count: int
    parsed_document_count: int
    indexed_document_count: int
    pending_review_document_count: int


class ProjectRepository:
    """项目仓储。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, keyword: str | None = None, user_id: int | None = None, admin: bool = False) -> list[Project]:
        """查询未删除项目列表。"""

        stmt = select(Project).where(Project.is_deleted.is_(False)).order_by(Project.id.desc())
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(
                (Project.name.like(like))
                | (Project.code.like(like))
                | (Project.project_short_name.like(like))
                | (Project.customer_name.like(like))
                | (Project.client.like(like))
            )
        if user_id is not None and not admin:
            stmt = stmt.join(ProjectMember, ProjectMember.project_id == Project.id).where(
                ProjectMember.user_id == user_id
            )
        return list(self.db.scalars(stmt).unique().all())

    def list_with_stats(
        self,
        *,
        user_id: int,
        user_department: str | None,
        is_admin: bool,
        data_scopes: set[str],
        project_security_levels: list[str],
        document_security_levels: list[str],
        include_document_stats: bool,
        pending_review_statuses: set[str],
        keyword: str | None = None,
        project_status: str | None = None,
        security_level: str | None = None,
    ) -> list[ProjectListStatsRow]:
        """一次性查询用户可访问项目、项目知识库 ID 和文档统计。"""

        document_stats = self._document_stats_subquery(
            document_security_levels=document_security_levels,
            include_document_stats=include_document_stats,
            pending_review_statuses=pending_review_statuses,
        )
        knowledge_base_stats = (
            select(
                KnowledgeBase.project_id.label("project_id"),
                func.min(KnowledgeBase.id).label("knowledge_base_id"),
            )
            .where(KnowledgeBase.type == "project")
            .group_by(KnowledgeBase.project_id)
            .subquery()
        )

        stmt = (
            select(
                Project,
                knowledge_base_stats.c.knowledge_base_id,
                func.coalesce(document_stats.c.document_count, 0).label("document_count"),
                func.coalesce(document_stats.c.knowledge_count, 0).label("knowledge_count"),
                func.coalesce(document_stats.c.parsed_document_count, 0).label("parsed_document_count"),
                func.coalesce(document_stats.c.indexed_document_count, 0).label("indexed_document_count"),
                func.coalesce(document_stats.c.pending_review_document_count, 0).label("pending_review_document_count"),
            )
            .outerjoin(knowledge_base_stats, knowledge_base_stats.c.project_id == Project.id)
            .outerjoin(document_stats, document_stats.c.project_id == Project.id)
            .where(Project.is_deleted.is_(False))
            .order_by(Project.id.desc())
        )

        filters = self._project_list_filters(
            user_id=user_id,
            user_department=user_department,
            is_admin=is_admin,
            data_scopes=data_scopes,
            project_security_levels=project_security_levels,
            keyword=keyword,
            project_status=project_status,
            security_level=security_level,
        )
        if filters:
            stmt = stmt.where(*filters)

        return [
            ProjectListStatsRow(
                project=project,
                knowledge_base_id=knowledge_base_id,
                document_count=int(document_count or 0),
                knowledge_count=int(knowledge_count or 0),
                parsed_document_count=int(parsed_document_count or 0),
                indexed_document_count=int(indexed_document_count or 0),
                pending_review_document_count=int(pending_review_document_count or 0),
            )
            for (
                project,
                knowledge_base_id,
                document_count,
                knowledge_count,
                parsed_document_count,
                indexed_document_count,
                pending_review_document_count,
            ) in self.db.execute(stmt).all()
        ]

    def list_accessible_ids(
        self,
        *,
        user_id: int,
        user_department: str | None,
        is_admin: bool,
        data_scopes: set[str],
        project_security_levels: list[str],
    ) -> list[int]:
        """查询当前用户可访问项目 ID，供跨项目资料列表做数据库级权限过滤。"""

        stmt = select(Project.id).where(Project.is_deleted.is_(False)).order_by(Project.id.desc())
        filters = self._project_list_filters(
            user_id=user_id,
            user_department=user_department,
            is_admin=is_admin,
            data_scopes=data_scopes,
            project_security_levels=project_security_levels,
            keyword=None,
            project_status=None,
            security_level=None,
        )
        if filters:
            stmt = stmt.where(*filters)
        return list(self.db.scalars(stmt).all())

    def document_stats_for_project(
        self,
        project_id: int,
        *,
        document_security_levels: list[str],
        include_document_stats: bool,
        pending_review_statuses: set[str],
    ) -> dict[str, int]:
        """按项目聚合文档统计，供详情接口直接返回统计字段。"""

        document_stats = self._document_stats_subquery(
            document_security_levels=document_security_levels,
            include_document_stats=include_document_stats,
            pending_review_statuses=pending_review_statuses,
        )
        row = self.db.execute(
            select(
                func.coalesce(document_stats.c.document_count, 0),
                func.coalesce(document_stats.c.knowledge_count, 0),
                func.coalesce(document_stats.c.parsed_document_count, 0),
                func.coalesce(document_stats.c.indexed_document_count, 0),
                func.coalesce(document_stats.c.pending_review_document_count, 0),
            ).where(document_stats.c.project_id == project_id)
        ).one_or_none()
        if row is None:
            return {
                "document_count": 0,
                "knowledge_count": 0,
                "parsed_document_count": 0,
                "indexed_document_count": 0,
                "pending_review_document_count": 0,
            }
        return {
            "document_count": int(row[0] or 0),
            "knowledge_count": int(row[1] or 0),
            "parsed_document_count": int(row[2] or 0),
            "indexed_document_count": int(row[3] or 0),
            "pending_review_document_count": int(row[4] or 0),
        }

    def _document_stats_subquery(
        self,
        *,
        document_security_levels: list[str],
        include_document_stats: bool,
        pending_review_statuses: set[str],
    ) -> Any:
        document_filters = [Document.is_deleted.is_(False)]
        if include_document_stats:
            document_filters.append(Document.security_level.in_(document_security_levels))
        else:
            document_filters.append(false())

        pending_review_condition = or_(
            Document.document_status == "pending_review",
            Document.review_status.in_(pending_review_statuses),
        )
        return (
            select(
                Document.project_id.label("project_id"),
                func.count(Document.id).label("document_count"),
                func.sum(case((Document.index_status == "indexed", 1), else_=0)).label("knowledge_count"),
                func.sum(case((Document.parse_status == "success", 1), else_=0)).label("parsed_document_count"),
                func.sum(case((Document.index_status == "indexed", 1), else_=0)).label("indexed_document_count"),
                func.sum(case((pending_review_condition, 1), else_=0)).label("pending_review_document_count"),
            )
            .where(*document_filters)
            .group_by(Document.project_id)
            .subquery()
        )

    def _project_list_filters(
        self,
        *,
        user_id: int,
        user_department: str | None,
        is_admin: bool,
        data_scopes: set[str],
        project_security_levels: list[str],
        keyword: str | None,
        project_status: str | None,
        security_level: str | None,
    ) -> list[Any]:
        filters: list[Any] = [Project.security_level.in_(project_security_levels)]
        if keyword:
            like = f"%{keyword}%"
            filters.append(
                (Project.name.like(like))
                | (Project.code.like(like))
                | (Project.project_short_name.like(like))
                | (Project.customer_name.like(like))
                | (Project.client.like(like))
            )
        if project_status:
            filters.append(self._project_status_expr() == project_status)
        if security_level:
            filters.append(Project.security_level == security_level)
        if not is_admin and DATA_SCOPE_ALL not in data_scopes:
            filters.append(self._data_scope_filter(user_id, user_department, data_scopes))
        return filters

    def _data_scope_filter(self, user_id: int, user_department: str | None, data_scopes: set[str]) -> Any:
        active_member_exists = self._active_member_exists(user_id)
        scope_conditions: list[Any] = []
        if DATA_SCOPE_DEPARTMENT in data_scopes:
            if user_department:
                scope_conditions.append(
                    and_(
                        Project.department_id.is_not(None),
                        cast(Project.department_id, String) == user_department,
                    )
                )
            scope_conditions.append(active_member_exists)
        if DATA_SCOPE_OWN in data_scopes:
            scope_conditions.append(or_(Project.created_by == user_id, active_member_exists))
        if DATA_SCOPE_PUBLIC_ONLY in data_scopes:
            scope_conditions.append(func.lower(Project.security_level) == "public")
        return or_(*scope_conditions) if scope_conditions else false()

    def _active_member_exists(self, user_id: int) -> Any:
        return (
            select(literal(1))
            .select_from(ProjectMember)
            .where(
                ProjectMember.project_id == Project.id,
                ProjectMember.user_id == user_id,
                ProjectMember.status == "active",
            )
            .exists()
        )

    def _project_status_expr(self) -> Any:
        project_status = func.trim(func.coalesce(Project.project_status, ""))
        legacy_status = func.trim(func.coalesce(Project.status, ""))
        legacy_project_status = case(
            (legacy_status == "pending", "待启动"),
            (legacy_status == "active", "进行中"),
            (legacy_status == "completed", "已完成"),
            (legacy_status.in_(("archived", "inactive")), "已暂停"),
            else_="进行中",
        )
        return case(
            (project_status.in_(("待启动", "进行中", "已完成", "已暂停")), project_status),
            (project_status == "pending", "待启动"),
            (project_status == "active", "进行中"),
            (project_status == "completed", "已完成"),
            (project_status.in_(("archived", "inactive")), "已暂停"),
            (project_status == "", legacy_project_status),
            else_="进行中",
        )

    def get(self, project_id: int) -> Project | None:
        """按 ID 查询项目。"""

        return self.db.get(Project, project_id)

    def get_by_code(self, code: str) -> Project | None:
        """按项目编号查询项目。"""

        return self.db.scalar(select(Project).where(Project.code == code))

    def add(self, project: Project) -> Project:
        """新增项目。"""

        self.db.add(project)
        self.db.flush()
        return project

    def delete(self, project: Project) -> None:
        """物理删除项目，仅保留给维护场景。业务删除请使用 Service 软删除。"""

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
