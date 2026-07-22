"""首页知识资产分布统计测试。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-dashboard-assets-32bytes")

from app.models import Base, Document, DocumentVersion, KnowledgeBase, Project  # noqa: E402
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


def _document(base_id: int, *, project_id: int | None = None, **fields: object) -> Document:
    values: dict[str, object] = {
        "review_status": "approved",
        "security_level": "public",
        "is_deleted": False,
        **fields,
    }
    return Document(
        knowledge_base_id=base_id,
        knowledge_type="project" if project_id is not None else "base",
        project_id=project_id,
        file_name="asset.pdf",
        file_type="pdf",
        file_size=1,
        storage_path="test/asset.pdf",
        **values,
    )


def test_repository_groups_accessible_effective_documents_once(db_session: Session) -> None:
    enterprise_base = KnowledgeBase(name="企业库", code="enterprise", type="base")
    visible_project = Project(name="可见项目", code="VISIBLE", security_level="public")
    hidden_project = Project(name="隐藏项目", code="HIDDEN", security_level="confidential")
    db_session.add_all([enterprise_base, visible_project, hidden_project])
    db_session.flush()
    visible_base = KnowledgeBase(name="可见项目库", code="visible-base", type="project", project_id=visible_project.id)
    hidden_base = KnowledgeBase(name="隐藏项目库", code="hidden-base", type="project", project_id=hidden_project.id)
    db_session.add_all([visible_base, hidden_base])
    db_session.flush()
    current_document = _document(visible_base.id, project_id=visible_project.id)
    db_session.add_all(
        [
            _document(enterprise_base.id),
            current_document,
            _document(visible_base.id, project_id=visible_project.id, is_deleted=True),
            _document(visible_base.id, project_id=visible_project.id, review_status="draft"),
            _document(visible_base.id, project_id=visible_project.id, security_level="confidential"),
            _document(hidden_base.id, project_id=hidden_project.id),
        ]
    )
    db_session.flush()
    db_session.add(
        DocumentVersion(
            document_id=current_document.id,
            project_id=visible_project.id,
            version_no=1,
            file_name="asset-v1.pdf",
            file_type="pdf",
            file_size=1,
            storage_path="test/asset-v1.pdf",
            is_current=False,
        )
    )
    db_session.commit()
    visible_project_id = visible_project.id

    query_count = 0

    def count_query(*_: object) -> None:
        nonlocal query_count
        query_count += 1

    event.listen(db_session.bind, "before_cursor_execute", count_query)
    try:
        rows = SystemRepository(db_session).list_knowledge_asset_distribution(
            security_levels=["public"],
            include_base_documents=True,
            include_project_documents=True,
            accessible_project_ids=[visible_project_id],
        )
    finally:
        event.remove(db_session.bind, "before_cursor_execute", count_query)

    assert query_count == 1
    assert {(project_id, name): count for project_id, name, count in rows} == {
        (None, None): 1,
        (visible_project_id, "可见项目"): 1,
    }


def test_builder_applies_top_five_stable_sort_and_other_projects(db_session: Session) -> None:
    rows = [
        (None, None, 10),
        (1, "项目 F", 1),
        (2, "项目 B", 5),
        (3, "项目 A", 5),
        (4, "项目 C", 4),
        (5, "项目 D", 3),
        (6, "项目 E", 2),
    ]

    result = SystemService(db_session)._build_knowledge_asset_distribution(rows)

    assert result["total_document_count"] == 30
    assert [item["name"] for item in result["items"]] == [
        "企业公共知识",
        "项目 A",
        "项目 B",
        "项目 C",
        "项目 D",
        "项目 E",
        "其他项目",
    ]
    assert result["items"][-1]["document_count"] == 1
    assert result["items"][-1]["project_count"] == 1
    assert sum(item["document_count"] for item in result["items"]) == result["total_document_count"]
    assert result["items"][0]["percentage"] == 33.3


def test_builder_omits_empty_groups_and_other_when_project_count_is_small(db_session: Session) -> None:
    service = SystemService(db_session)

    assert service._build_knowledge_asset_distribution([]) == {"total_document_count": 0, "items": []}
    result = service._build_knowledge_asset_distribution([(1, "单项目", 2)])
    assert result == {
        "total_document_count": 2,
        "items": [
            {
                "scope_type": "project",
                "scope_id": 1,
                "name": "单项目",
                "document_count": 2,
                "percentage": 100.0,
            }
        ],
    }
