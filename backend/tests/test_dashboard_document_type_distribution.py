"""首页文档类型分布统计测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-dashboard-types-32bytes")

from app.models import Base, Document, KnowledgeBase, Permission, Project, Role, User  # noqa: E402
from app.repositories.system_repository import SystemRepository  # noqa: E402
from app.services.system_service import SystemService  # noqa: E402


@pytest.fixture()
def db_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    with factory() as session:
        yield session
    engine.dispose()


def _document(knowledge_base_id: int, file_type: str, *, project_id: int | None = None, **fields: object) -> Document:
    values: dict[str, object] = {
        "review_status": "approved",
        "security_level": "public",
        **fields,
    }
    return Document(
        knowledge_base_id=knowledge_base_id,
        knowledge_type="project" if project_id else "base",
        project_id=project_id,
        file_name=f"archive.part.{file_type.strip() or 'no-extension'}",
        file_type=file_type,
        file_size=1,
        storage_path="test/path",
        **values,
    )


def test_distribution_maps_extensions_and_handles_unknown_values(db_session: Session) -> None:
    knowledge_base = KnowledgeBase(name="基础库", code="base", type="base")
    db_session.add(knowledge_base)
    db_session.flush()
    extensions = [" PDF ", "DOC", "docx", "XLS", "xlsx", "xlsm", "CSV", "ppt", "PPTX", "JPG", "tiff", "zip", ""]
    db_session.add_all([_document(knowledge_base.id, extension) for extension in extensions])
    db_session.commit()

    rows = SystemRepository(db_session).list_document_type_distribution(
        security_levels=["public"],
        include_base_documents=True,
        include_project_documents=False,
        accessible_project_ids=[],
    )
    result = SystemService(db_session)._build_document_type_distribution(rows)

    assert [(item["type"], item["count"]) for item in result] == [
        ("excel", 4),
        ("word", 2),
        ("powerpoint", 2),
        ("image", 2),
        ("other", 2),
        ("pdf", 1),
    ]
    assert sum(int(item["count"]) for item in result) == len(extensions)
    assert all(round(float(item["percentage"]), 1) == item["percentage"] for item in result)


def test_dashboard_scope_reuses_role_security_and_project_permissions(db_session: Session) -> None:
    project_permission = Permission(module="project", action="view", code="project:view", description="查看项目")
    regular_role = Role(name="普通角色", code="regular", enabled=True, security_level="public", data_scope="own")
    admin_role = Role(name="管理员", code="admin", enabled=True, security_level="confidential", data_scope="all")
    admin_role.permissions.append(project_permission)
    regular_user = User(username="regular", password_hash="x", real_name="普通用户", roles=[regular_role])
    admin_user = User(username="admin", password_hash="x", real_name="管理员", roles=[admin_role])
    project = Project(name="项目", code="P001", security_level="internal", created_by=None)
    db_session.add_all([regular_user, admin_user, project])
    db_session.flush()
    knowledge_base = KnowledgeBase(name="项目库", code="project", type="project", project_id=project.id)
    db_session.add(knowledge_base)
    db_session.flush()
    db_session.add_all(
        [
            _document(knowledge_base.id, "pdf", project_id=project.id),
            _document(knowledge_base.id, "docx", security_level="confidential"),
            _document(knowledge_base.id, "xlsx", is_deleted=True),
            _document(knowledge_base.id, "pptx", review_status="draft"),
        ]
    )
    db_session.commit()

    regular_result = SystemService(db_session).dashboard(regular_user)
    admin_result = SystemService(db_session).dashboard(admin_user)

    assert regular_result["document_count"] == 0
    assert regular_result["document_type_distribution"] == []
    assert admin_result["document_count"] == 2
    assert {item["type"]: item["count"] for item in admin_result["document_type_distribution"]} == {
        "pdf": 1,
        "word": 1,
        "excel": 0,
        "powerpoint": 0,
        "image": 0,
        "other": 0,
    }
