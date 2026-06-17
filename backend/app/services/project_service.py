"""
Project Service

负责：
1. 项目 CRUD 业务
2. 创建项目时自动创建项目知识库
3. 校验项目成员权限，防止跨项目访问
"""

from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.models.knowledge_base import KnowledgeBase
from app.models.knowledge_category import KnowledgeCategory
from app.models.project import Project, ProjectMember
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.project import ProjectCreate, ProjectMemberCreate, ProjectUpdate
from app.services.system_service import SystemService


class ProjectService:
    """
    项目服务

    职责：
    - 管理项目基础信息
    - 管理项目成员授权
    - 维护项目知识库自动绑定关系
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.kb_repository = KnowledgeBaseRepository(db)

    def user_is_admin(self, user: User) -> bool:
        """判断用户是否管理员。"""

        return any(role.code == "admin" for role in user.roles)

    def ensure_project_access(self, project_id: int, user: User) -> None:
        """
        校验项目访问权限

        参数:
            project_id: 项目ID
            user: 当前用户
        """

        if self.user_is_admin(user):
            return
        if not self.project_repository.get_member(project_id, user.id):
            raise AppException("无权访问该项目", status_code=403, code=403)

    def list_projects(self, user: User, keyword: str | None = None) -> list[dict]:
        """查询当前用户可访问项目。"""

        projects = self.project_repository.list(keyword=keyword, user_id=user.id, admin=self.user_is_admin(user))
        doc_repo = DocumentRepository(self.db)
        result: list[dict] = []
        for project in projects:
            kb = self.kb_repository.get_project_base(project.id)
            documents = doc_repo.list(project_id=project.id)
            result.append(self._project_to_dict(project, kb.id if kb else None, len(documents), sum(1 for doc in documents if doc.index_status == "indexed")))
        return result

    def get_project(self, project_id: int, user: User) -> dict:
        """查询项目详情。"""

        self.ensure_project_access(project_id, user)
        project = self.project_repository.get(project_id)
        if not project:
            raise AppException("项目不存在", status_code=404, code=404)
        kb = self.kb_repository.get_project_base(project.id)
        documents = DocumentRepository(self.db).list(project_id=project.id)
        return self._project_to_dict(project, kb.id if kb else None, len(documents), sum(1 for doc in documents if doc.index_status == "indexed"))

    def create_project(self, payload: ProjectCreate, operator: User) -> dict:
        """创建项目并自动创建项目知识库。"""

        if self.project_repository.get_by_code(payload.code):
            raise AppException("项目编码已存在")
        project = Project(
            name=payload.name,
            code=payload.code,
            description=payload.description,
            client=payload.client,
            manager=payload.manager,
            status=payload.status,
            progress=payload.progress,
            created_by=operator.id,
        )
        self.project_repository.add(project)

        # 创建者自动成为项目 owner，确保项目创建后立刻具备访问权限。
        self.project_repository.add_member(
            ProjectMember(
                project_id=project.id,
                user_id=operator.id,
                role="owner",
                permission_scope="project_manage",
                external_user=False,
                status="active",
            )
        )
        kb = KnowledgeBase(
            name=f"{project.name}知识库",
            code=f"project-{project.code}",
            type="project",
            project_id=project.id,
            description=f"{project.name} 的项目资料与专业知识库",
            visibility="private",
            enabled=True,
            created_by=operator.id,
        )
        self.kb_repository.add(kb)
        self._seed_default_project_categories(project.id, operator.id)
        SystemService(self.db).record_operation(operator, "创建项目", "project", project.id, f"创建项目 {project.name}")
        self.db.commit()
        return self._project_to_dict(project, kb.id, 0, 0)

    def update_project(self, project_id: int, payload: ProjectUpdate, operator: User) -> dict:
        """更新项目。"""

        self.ensure_project_access(project_id, operator)
        project = self.project_repository.get(project_id)
        if not project:
            raise AppException("项目不存在", status_code=404, code=404)
        for field in ["name", "description", "client", "manager", "status", "progress"]:
            value = getattr(payload, field)
            if value is not None:
                setattr(project, field, value)
        SystemService(self.db).record_operation(operator, "编辑项目", "project", project.id, f"编辑项目 {project.name}")
        self.db.commit()
        return self.get_project(project_id, operator)

    def delete_project(self, project_id: int, operator: User) -> None:
        """删除项目。"""

        self.ensure_project_access(project_id, operator)
        project = self.project_repository.get(project_id)
        if not project:
            raise AppException("项目不存在", status_code=404, code=404)
        self.project_repository.delete(project)
        SystemService(self.db).record_operation(operator, "删除项目", "project", project_id, "删除项目")
        self.db.commit()

    def list_members(self, project_id: int, operator: User) -> list[ProjectMember]:
        """查询项目成员。"""

        self.ensure_project_access(project_id, operator)
        return self.project_repository.list_members(project_id)

    def add_member(self, project_id: int, payload: ProjectMemberCreate, operator: User) -> ProjectMember:
        """新增项目成员。"""

        self.ensure_project_access(project_id, operator)
        if not UserRepository(self.db).get_by_id(payload.user_id):
            raise AppException("用户不存在", status_code=404, code=404)
        existing = self.project_repository.get_member(project_id, payload.user_id)
        if existing:
            return existing
        member = ProjectMember(
            project_id=project_id,
            user_id=payload.user_id,
            role=payload.role,
            permission_scope=payload.permission_scope,
            external_user=payload.external_user,
            status="active",
        )
        self.project_repository.add_member(member)
        SystemService(self.db).record_operation(operator, "新增项目成员", "project_member", member.id, f"项目 {project_id} 新增成员")
        self.db.commit()
        return member

    def delete_member(self, project_id: int, user_id: int, operator: User) -> None:
        """删除项目成员。"""

        self.ensure_project_access(project_id, operator)
        member = self.project_repository.get_member(project_id, user_id)
        if not member:
            raise AppException("项目成员不存在", status_code=404, code=404)
        self.project_repository.delete_member(member)
        SystemService(self.db).record_operation(operator, "删除项目成员", "project_member", member.id, f"项目 {project_id} 删除成员")
        self.db.commit()

    def _project_to_dict(
        self,
        project: Project,
        knowledge_base_id: int | None,
        document_count: int,
        knowledge_count: int,
    ) -> dict:
        """
        转换项目响应字典

        参数:
            project: 项目 ORM 对象
            knowledge_base_id: 项目知识库ID
            document_count: 文档数量
            knowledge_count: 已索引知识数量

        返回:
            不包含 SQLAlchemy 内部状态的项目字典。
        """

        return {
            "id": project.id,
            "name": project.name,
            "code": project.code,
            "description": project.description,
            "client": project.client,
            "manager": project.manager,
            "status": project.status,
            "progress": project.progress,
            "created_by": project.created_by,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "knowledge_base_id": knowledge_base_id,
            "document_count": document_count,
            "knowledge_count": knowledge_count,
        }

    def _seed_default_project_categories(self, project_id: int, created_by: int | None) -> None:
        """
        初始化项目资料默认分类

        参数:
            project_id: 项目ID
            created_by: 创建人ID
        """

        defaults = {
            "设计资料": ["设计输入", "设计计算", "设计评审"],
            "实施资料": ["会议纪要", "现场记录", "变更资料"],
            "交付资料": ["验收资料", "运维手册", "归档文件"],
        }
        for group_index, (group_name, child_names) in enumerate(defaults.items(), start=1):
            parent = KnowledgeCategory(
                scope_type="project",
                project_id=project_id,
                parent_id=None,
                name=group_name,
                code=f"project-{project_id}-{group_index}",
                sort_order=group_index * 10,
                enabled=True,
                created_by=created_by,
            )
            self.db.add(parent)
            self.db.flush()
            for child_index, child_name in enumerate(child_names, start=1):
                self.db.add(
                    KnowledgeCategory(
                        scope_type="project",
                        project_id=project_id,
                        parent_id=parent.id,
                        name=child_name,
                        code=f"{parent.code}-{child_index}",
                        sort_order=child_index * 10,
                        enabled=True,
                        created_by=created_by,
                    )
                )
