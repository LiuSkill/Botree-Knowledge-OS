"""
Project Metadata Retriever

轻量读取项目主数据，用于 project_overview 链路的低成本召回与权限校验。
该 retriever 不替代项目文档证据，项目介绍是否足够仍由 evidence judge 根据真实资料覆盖度判断。
"""

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.user import User
from app.retrieval.base import BaseRetriever, DEFAULT_RETRIEVER_TOP_K
from app.retrieval.schemas import Evidence
from app.services.project_access_service import ProjectAccessService


class ProjectMetadataRetriever(BaseRetriever):
    """从项目表读取名称、编码、客户、经理、状态和描述。"""

    name = "project_metadata"

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(
        self,
        query: str,
        mode: str,
        project_id: int | None,
        user: User,
        limit: int = DEFAULT_RETRIEVER_TOP_K,
    ) -> list[Evidence]:  # noqa: ARG002
        if mode != "project_chat" or project_id is None:
            return []

        ProjectAccessService(self.db).ensure_project_access(project_id, user, permission_codes=("project:chat",))
        project = self.db.get(Project, project_id)
        if project is None:
            return []

        lines = [
            f"项目名称：{project.name}",
            f"项目编码：{project.code}",
        ]
        if project.client:
            lines.append(f"客户：{project.client}")
        if project.manager:
            lines.append(f"项目经理：{project.manager}")
        if project.status:
            lines.append(f"项目状态：{project.status}")
        if project.progress is not None:
            lines.append(f"项目进度：{project.progress}%")
        if project.description:
            lines.append(f"项目描述：{project.description}")

        return [
            Evidence(
                score=0.35,
                source_type="project_metadata",
                knowledge_base_id=0,
                project_id=project.id,
                document_id=0,
                chunk_id=project.id,
                drawing_no=None,
                file_name="项目基础信息",
                page_number=None,
                content="\n".join(lines),
                retriever=self.name,
                metadata={
                    "project_id": project.id,
                    "metadata_only": True,
                    "source_scope": "project",
                    "security_level": project.security_level,
                    "project_security_level": project.security_level,
                },
            )
        ][:limit]
