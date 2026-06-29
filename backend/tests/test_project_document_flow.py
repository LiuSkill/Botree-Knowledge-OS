"""Project document closed-loop tests."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.models import (  # noqa: E402
    Base,
    ChatMessage,
    ChatSession,
    Document,
    DocumentChunk,
    DocumentVersion,
    KnowledgeBase,
    KnowledgeCategory,
    OperationLog,
    Project,
    Role,
    User,
)
from app.core.project_directory_template import DEFAULT_PROJECT_DIRECTORY_TEMPLATE  # noqa: E402
from app.core.security_levels import DEFAULT_SECURITY_LEVEL  # noqa: E402
from app.schemas.document import DocumentOut  # noqa: E402
from app.schemas.project import ProjectCreate  # noqa: E402
from app.services.document_service import (  # noqa: E402
    ACTION_DELETE_DOCUMENT,
    ACTION_UPLOAD_DOCUMENT,
    ACTION_UPLOAD_NEW_VERSION,
    DocumentService,
    INDEX_STATUS_INDEXED,
    PARSE_STATUS_SUCCESS,
    PROJECT_DOCUMENT_STATUS_PENDING,
    PROJECT_DOCUMENT_STATUS_PUBLISHED,
)
from app.services.project_document_policy_service import ProjectDocumentPolicyService  # noqa: E402
from app.services.project_service import ProjectService  # noqa: E402


def make_session() -> Session:
    """创建独立内存数据库，保持与现有 Service 单测一致。"""

    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def create_user(
    db: Session,
    *,
    user_id: int,
    username: str,
    role_code: str,
    security_level: str,
    data_scope: str = "all",
) -> User:
    """创建带角色的测试用户；管理员角色用于穿透 RBAC 操作权限。"""

    role = Role(
        id=user_id,
        name=f"{role_code}-{user_id}",
        code=role_code,
        enabled=True,
        security_level=security_level,
        data_scope=data_scope,
    )
    user = User(
        id=user_id,
        username=username,
        password_hash="x",
        real_name=username.title(),
    )
    user.roles = [role]
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def mark_current_document_indexed(db: Session, document_id: int) -> None:
    """模拟解析索引成功，只更新准入策略依赖的轻量状态字段。"""

    document = db.get(Document, document_id)
    assert document is not None
    document.parse_status = PARSE_STATUS_SUCCESS
    document.index_status = INDEX_STATUS_INDEXED
    current_version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version_no == document.version_no,
        )
    )
    assert current_version is not None
    current_version.parse_status = PARSE_STATUS_SUCCESS
    current_version.index_status = INDEX_STATUS_INDEXED
    db.commit()


def upload_info(file_name: str, file_size: int) -> dict[str, Any]:
    return {
        "file_name": file_name,
        "file_type": Path(file_name).suffix.lstrip(".") or "txt",
        "file_size": file_size,
        "storage_path": f"storage/uploads/{file_name}",
    }


def create_project_record(
    db: Session,
    *,
    name: str,
    code: str,
    security_level: str,
    project_status: str = "进行中",
    status: str = "active",
    created_by: int | None = None,
) -> Project:
    project = Project(
        name=name,
        code=code,
        project_short_name=name,
        client="Customer",
        customer_name="Customer",
        manager="Owner",
        owner_name="Owner",
        description=f"{name} description",
        status=status,
        project_status=project_status,
        progress=0,
        security_level=security_level,
        created_by=created_by,
        is_deleted=False,
    )
    db.add(project)
    db.flush()
    db.add(
        KnowledgeBase(
            name=f"{name}知识库",
            code=f"project-{code}",
            type="project",
            project_id=project.id,
            enabled=True,
            created_by=created_by,
        )
    )
    db.flush()
    return project


def create_document_record(
    db: Session,
    *,
    project: Project,
    knowledge_base_id: int,
    file_name: str,
    security_level: str,
    parse_status: str = "unparsed",
    index_status: str = "not_indexed",
    document_status: str = "published",
    review_status: str = "approved",
    is_deleted: bool = False,
) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        knowledge_type="project",
        project_id=project.id,
        file_name=file_name,
        file_type=Path(file_name).suffix.lstrip(".") or "txt",
        file_size=1,
        storage_path=f"storage/uploads/{file_name}",
        document_status=document_status,
        parse_status=parse_status,
        review_status=review_status,
        index_status=index_status,
        security_level=security_level,
        is_deleted=is_deleted,
    )
    db.add(document)
    return document


def assert_default_project_directories(categories: list[KnowledgeCategory]) -> dict[str, KnowledgeCategory]:
    """校验新项目自动生成的默认资料目录必须与统一模板完全一致。"""

    expected_count = sum(1 + len(children) for _, _, children in DEFAULT_PROJECT_DIRECTORY_TEMPLATE)
    assert len(categories) == expected_count
    assert all(category.enabled for category in categories)
    assert all(category.default_security_level == DEFAULT_SECURITY_LEVEL for category in categories)
    assert all(category.is_deleted is False for category in categories)

    roots = sorted((category for category in categories if category.parent_id is None), key=lambda item: item.sort_order)
    assert [(root.code, root.name) for root in roots] == [
        (root_code, root_name) for root_code, root_name, _ in DEFAULT_PROJECT_DIRECTORY_TEMPLATE
    ]

    for group_index, (root, (root_code, _root_name, child_items)) in enumerate(
        zip(roots, DEFAULT_PROJECT_DIRECTORY_TEMPLATE, strict=True),
        start=1,
    ):
        assert root.code == root_code
        assert root.sort_order == group_index * 100
        children = sorted(
            (category for category in categories if category.parent_id == root.id),
            key=lambda item: item.sort_order,
        )
        assert [(child.code, child.name) for child in children] == child_items
        assert [child.sort_order for child in children] == [
            group_index * 100 + child_index for child_index in range(1, len(child_items) + 1)
        ]

    return {category.code: category for category in roots}


def test_list_projects_uses_single_query_for_accessible_stats() -> None:
    """项目列表必须在 SQL 中完成权限过滤和统计聚合，避免按项目循环查询。"""

    db = make_session()
    try:
        low_admin = create_user(
            db,
            user_id=1,
            username="low-admin",
            role_code="admin",
            security_level="public",
        )
        project_one = create_project_record(
            db,
            name="Stats One",
            code="PRJ-STATS-001",
            security_level="public",
            created_by=low_admin.id,
        )
        project_two = create_project_record(
            db,
            name="Stats Two",
            code="PRJ-STATS-002",
            security_level="public",
            project_status="待启动",
            status="pending",
            created_by=low_admin.id,
        )
        hidden_project = create_project_record(
            db,
            name="Hidden Internal",
            code="PRJ-STATS-003",
            security_level="internal",
            created_by=low_admin.id,
        )
        deleted_project = create_project_record(
            db,
            name="Deleted Public",
            code="PRJ-STATS-004",
            security_level="public",
            created_by=low_admin.id,
        )
        deleted_project.is_deleted = True

        knowledge_bases = {
            item.project_id: item
            for item in db.scalars(select(KnowledgeBase).where(KnowledgeBase.type == "project")).all()
        }
        project_one_kb = knowledge_bases[project_one.id]
        project_two_kb = knowledge_bases[project_two.id]
        hidden_project_kb = knowledge_bases[hidden_project.id]

        create_document_record(
            db,
            project=project_one,
            knowledge_base_id=project_one_kb.id,
            file_name="indexed-public.pdf",
            security_level="public",
            parse_status=PARSE_STATUS_SUCCESS,
            index_status=INDEX_STATUS_INDEXED,
            document_status="pending_review",
            review_status="draft",
        )
        create_document_record(
            db,
            project=project_one,
            knowledge_base_id=project_one_kb.id,
            file_name="ordinary-public.pdf",
            security_level="public",
        )
        create_document_record(
            db,
            project=project_one,
            knowledge_base_id=project_one_kb.id,
            file_name="hidden-confidential.pdf",
            security_level="confidential",
            parse_status=PARSE_STATUS_SUCCESS,
            index_status=INDEX_STATUS_INDEXED,
        )
        create_document_record(
            db,
            project=project_one,
            knowledge_base_id=project_one_kb.id,
            file_name="deleted-public.pdf",
            security_level="public",
            is_deleted=True,
        )
        create_document_record(
            db,
            project=project_two,
            knowledge_base_id=project_two_kb.id,
            file_name="pending-public.pdf",
            security_level="public",
            parse_status=PARSE_STATUS_SUCCESS,
            index_status=INDEX_STATUS_INDEXED,
        )
        create_document_record(
            db,
            project=hidden_project,
            knowledge_base_id=hidden_project_kb.id,
            file_name="hidden-project-public.pdf",
            security_level="public",
            parse_status=PARSE_STATUS_SUCCESS,
            index_status=INDEX_STATUS_INDEXED,
        )
        project_one_id = project_one.id
        project_two_id = project_two.id
        project_one_kb_id = project_one_kb.id
        project_two_kb_id = project_two_kb.id
        db.commit()

        for role in low_admin.roles:
            _ = role.code

        statements: list[str] = []

        def capture_sql(conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001, ARG001
            if statement.lstrip().upper().startswith("SELECT"):
                statements.append(statement)

        bind = db.get_bind()
        event.listen(bind, "before_cursor_execute", capture_sql)
        try:
            in_progress_projects = ProjectService(db).list_projects(low_admin, project_status="进行中")
        finally:
            event.remove(bind, "before_cursor_execute", capture_sql)

        assert len(statements) == 1
        assert [item["id"] for item in in_progress_projects] == [project_one_id]
        project_one_payload = in_progress_projects[0]
        assert project_one_payload["knowledge_base_id"] == project_one_kb_id
        assert project_one_payload["document_count"] == 2
        assert project_one_payload["knowledge_count"] == 1
        assert project_one_payload["parsed_document_count"] == 1
        assert project_one_payload["indexed_document_count"] == 1
        assert project_one_payload["pending_review_document_count"] == 1

        all_projects = ProjectService(db).list_projects(low_admin)
        assert [item["id"] for item in all_projects] == [project_two_id, project_one_id]
        assert all_projects[0]["knowledge_base_id"] == project_two_kb_id
        assert all_projects[0]["document_count"] == 1
        keyword_projects = ProjectService(db).list_projects(low_admin, keyword="Stats One")
        assert [item["id"] for item in keyword_projects] == [project_one_id]
        assert [item["id"] for item in ProjectService(db).list_projects(low_admin, security_level="public")] == [
            project_two_id,
            project_one_id,
        ]
    finally:
        db.close()


def test_project_document_lifecycle_controls_project_chat_access() -> None:
    """验证项目创建、默认目录、上传、发布、AI、版本、删除和问答准入闭环。"""

    db = make_session()
    try:
        admin = create_user(
            db,
            user_id=1,
            username="admin",
            role_code="admin",
            security_level="confidential",
        )

        project_result = ProjectService(db).create_project(
            ProjectCreate(
                name="Flow Project",
                code="PRJ-FLOW-001",
                project_short_name="Flow",
                client="Customer A",
                manager="Owner A",
                status="active",
                security_level="public",
                description="Closed loop project",
            ),
            admin,
        )
        project_id = int(project_result["id"])
        project = db.get(Project, project_id)
        assert project is not None
        other_project_result = ProjectService(db).create_project(
            ProjectCreate(
                name="Other Project",
                code="PRJ-FLOW-OTHER",
                project_short_name="Other",
                client="Customer B",
                manager="Owner B",
                status="active",
                security_level="public",
                description="Other project",
            ),
            admin,
        )
        other_project_id = int(other_project_result["id"])

        categories = list(
            db.scalars(
                select(KnowledgeCategory).where(
                    KnowledgeCategory.project_id == project_id,
                    KnowledgeCategory.scope_type == "project",
                    KnowledgeCategory.is_deleted.is_(False),
                )
            ).all()
        )
        roots = assert_default_project_directories(categories)
        directory = next(category for category in categories if category.parent_id == roots["E"].id)
        knowledge_base = db.scalar(select(KnowledgeBase).where(KnowledgeBase.project_id == project_id, KnowledgeBase.type == "project"))
        assert knowledge_base is not None

        document_service = DocumentService(db)
        with (
            patch("app.services.document_service.UploadService.save", new=AsyncMock(return_value=upload_info("basis-v1.pdf", 120))),
            patch("app.services.document_service.IndexTaskService.create_parse_task") as create_parse_task,
        ):
            document = asyncio.run(
                document_service.upload_document(
                    knowledge_base.id,
                    object(),  # type: ignore[arg-type]
                    admin,
                    directory.id,
                    security_level="confidential",
                )
            )

        create_parse_task.assert_called_once()
        assert document.project_id == project_id
        assert document.directory_id == directory.id
        assert document.status == PROJECT_DOCUMENT_STATUS_PENDING
        assert document.ai_enabled is False
        assert document.is_current_version is True

        project_session = ChatSession(
            user_id=admin.id,
            title="Project QA",
            chat_type="project_chat",
            mode="project_only",
            project_id=project_id,
        )
        other_project_session = ChatSession(
            user_id=admin.id,
            title="Other Project QA",
            chat_type="project_chat",
            mode="project_only",
            project_id=other_project_id,
        )
        base_session = ChatSession(
            user_id=admin.id,
            title="Base QA",
            chat_type="base_chat",
            mode="auto",
            project_id=project_id,
        )
        db.add_all([project_session, other_project_session, base_session])
        db.flush()
        db.add_all(
            [
                ChatMessage(session_id=project_session.id, user_id=admin.id, role="user", content="问题 1"),
                ChatMessage(session_id=project_session.id, user_id=None, role="assistant", content="回答 1"),
                ChatMessage(session_id=project_session.id, user_id=admin.id, role="user", content="问题 2"),
                ChatMessage(session_id=project_session.id, user_id=None, role="assistant", content="回答 2"),
                ChatMessage(session_id=other_project_session.id, user_id=None, role="assistant", content="其他项目回答"),
                ChatMessage(session_id=base_session.id, user_id=None, role="assistant", content="基础问答回答"),
            ]
        )
        db.commit()

        overview = ProjectService(db).get_project_overview(project_id, admin)
        assert overview["qa_count"] == 2
        assert overview["pending_review_document_count"] == 1
        assert overview["recent_documents"][0]["file_type"] == "pdf"
        assert overview["recent_documents"][0]["file_size"] == 120
        assert overview["recent_documents"][0]["uploader_name"] == "Admin"
        assert overview["recent_documents"][0]["uploader_username"] == "admin"
        assert overview["recent_documents"][0]["directory_name"] == directory.name
        root_stat_by_code = {item["directory_code"]: item for item in overview["first_level_directory_stats"]}
        assert root_stat_by_code["E"]["document_count"] == 1

        project_documents = document_service.list_documents(admin, project_id=project_id, knowledge_type="project")
        project_document_payload = DocumentOut.model_validate(project_documents[0]).model_dump(mode="json")
        assert project_document_payload["uploader_name"] == "Admin"
        assert project_document_payload["uploader_username"] == "admin"

        policy = ProjectDocumentPolicyService(db)
        assert (
            policy.project_chat_document_reject_reason(document, user=admin, project_id=project_id)
            == "document_not_published"
        )

        document_service.publish_document(document.id, admin)
        mark_current_document_indexed(db, document.id)
        document = document_service.toggle_document_ai(document.id, True, admin)
        db.refresh(document)
        assert document.status == PROJECT_DOCUMENT_STATUS_PUBLISHED
        assert document.ai_enabled is True
        assert policy.project_chat_document_reject_reason(document, user=admin, project_id=project_id) is None

        old_chunk = DocumentChunk(
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            project_id=project_id,
            knowledge_type="project",
            version_no=document.version_no,
            chunk_status="active",
            chunk_index=1,
            content="current evidence",
            page_number=1,
            security_level=document.security_level,
        )
        db.add(old_chunk)
        db.commit()
        assert policy.project_chat_evidence_reject_reason(document=document, chunk=old_chunk, user=admin, project_id=project_id) is None

        low_user = User(id=99, username="low", password_hash="x", real_name="Low")
        low_user.roles = [Role(id=99, name="Low", code="admin", enabled=True, security_level="public", data_scope="all")]
        assert (
            policy.project_chat_document_reject_reason(document, user=low_user, project_id=project_id)
            == "permission_denied"
        )

        with (
            patch("app.services.document_service.UploadService.save", new=AsyncMock(return_value=upload_info("basis-v2.pdf", 220))),
            patch("app.services.document_service.IndexTaskService.create_parse_task") as create_parse_task,
        ):
            new_version = asyncio.run(document_service.create_version(document.id, object(), admin, "v2 update"))  # type: ignore[arg-type]

        create_parse_task.assert_called_once()
        db.refresh(document)
        versions = {
            version.version_no: version
            for version in db.scalars(select(DocumentVersion).where(DocumentVersion.document_id == document.id)).all()
        }
        assert new_version.version_no == 2
        assert document.version_no == 2
        assert document.status == PROJECT_DOCUMENT_STATUS_PENDING
        assert document.ai_enabled is False
        assert versions[1].is_current_version is False
        assert versions[1].ai_enabled is False
        assert versions[2].is_current_version is True
        assert policy.project_chat_document_reject_reason(document, user=admin, project_id=project_id) == "document_not_published"

        document_service.publish_document(document.id, admin)
        mark_current_document_indexed(db, document.id)
        document = document_service.toggle_document_ai(document.id, True, admin)
        new_chunk = DocumentChunk(
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            project_id=project_id,
            knowledge_type="project",
            version_no=document.version_no,
            chunk_status="active",
            chunk_index=2,
            content="new evidence",
            page_number=2,
            security_level=document.security_level,
        )
        db.add(new_chunk)
        db.commit()
        assert (
            policy.project_chat_evidence_reject_reason(document=document, chunk=old_chunk, user=admin, project_id=project_id)
            == "version_not_current"
        )
        assert policy.project_chat_evidence_reject_reason(document=document, chunk=new_chunk, user=admin, project_id=project_id) is None

        delete_result = document_service.delete_document(document.id, admin)
        db.refresh(document)
        assert delete_result["deleted"] is True
        assert document.is_deleted is True
        assert document.ai_enabled is False
        assert policy.project_chat_document_reject_reason(document, user=admin, project_id=project_id) == "document_deleted"

        logs = list(db.scalars(select(OperationLog).where(OperationLog.project_id == project_id)).all())
        actions = {log.action for log in logs}
        assert ACTION_UPLOAD_DOCUMENT in actions
        assert ACTION_UPLOAD_NEW_VERSION in actions
        assert ACTION_DELETE_DOCUMENT in actions
        assert any(log.target_type == "project" and log.target_id == str(project_id) for log in logs)
        assert any("发布" in log.action for log in logs)
        assert any("AI" in log.action for log in logs)
    finally:
        db.close()
