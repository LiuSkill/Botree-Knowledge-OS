"""Project directory import tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from app.core.config import get_settings  # noqa: E402
from app.core.security_levels import DEFAULT_SECURITY_LEVEL  # noqa: E402
from app.models import (  # noqa: E402
    Base,
    Document,
    DocumentVersion,
    IndexTask,
    KnowledgeCategory,
    Project,
    Role,
    User,
)
from app.services.project_directory_import_service import ProjectDirectoryImportService  # noqa: E402


def make_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return session_factory()


def create_admin_user(db: Session) -> User:
    role = Role(
        id=1,
        name="admin",
        code="admin",
        enabled=True,
        security_level="confidential",
        data_scope="all",
    )
    user = User(id=1, username="admin", password_hash="x", real_name="Admin")
    user.roles = [role]
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def isolate_storage(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-32-bytes-minimum-value")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    for env_name in ("MINIO_ENDPOINT", "MINIO_ACCESS_KEY", "MINIO_SECRET_KEY", "MINIO_BUCKET"):
        monkeypatch.setenv(env_name, "")
    get_settings.cache_clear()


def build_source_fixture(source_root: Path) -> None:
    duplicate_content = b"%PDF-1.4 duplicate equipment file"
    files = {
        source_root / "设计" / "3）设备" / "设备资料" / "duplicate.pdf": duplicate_content,
        source_root / "项目管理" / "3）设备" / "设备资料" / "duplicate.pdf": duplicate_content,
        source_root / "采购" / "2）采购管理" / "03采购合同" / "contract.docx": b"contract content",
        source_root / "设计" / "3）设备" / "设备资料" / "photo.png": b"png content",
        source_root / "设计" / "3）设备" / "model.dwg": b"unsupported drawing",
    }
    for path, content in files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def test_project_directory_import_dry_run_does_not_write_database(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    isolate_storage(monkeypatch, tmp_path)
    db = make_session()
    try:
        create_admin_user(db)
        source_root = tmp_path / "source"
        build_source_fixture(source_root)

        report = ProjectDirectoryImportService(db).import_directory(
            source=source_root,
            operator_username="admin",
            project_code="BC2413-DRY",
            project_name="西班牙LFP项目",
            dry_run=True,
        )

        assert report["dry_run"] is True
        assert report["scanned_files"] == 5
        assert report["included_files"] == 4
        assert report["skipped_files"] == 1
        assert report["skipped_by_extension"][".dwg"] == 1
        assert report["unique_content_files"] == 3
        assert report["duplicate_group_count"] == 1
        assert report["duplicate_file_count"] == 1
        assert report["would_import_documents"] == 3
        assert db.scalar(select(Project)) is None
        assert db.scalar(select(Document)) is None
    finally:
        db.close()
        get_settings.cache_clear()


def test_project_directory_import_commit_creates_project_documents_and_metadata(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    isolate_storage(monkeypatch, tmp_path)
    db = make_session()
    try:
        create_admin_user(db)
        source_root = tmp_path / "source"
        build_source_fixture(source_root)

        report = ProjectDirectoryImportService(db).import_directory(
            source=source_root,
            operator_username="admin",
            project_code="BC2413",
            project_name="西班牙LFP项目",
            dry_run=False,
        )

        project = db.scalar(select(Project).where(Project.code == "BC2413"))
        assert project is not None
        assert project.name == "西班牙LFP项目"
        assert project.client == "待补充"
        assert project.manager == "待补充"
        assert project.security_level == DEFAULT_SECURITY_LEVEL
        assert report["project_id"] == project.id
        assert report["imported_documents"] == 3
        assert report["failed_file_count"] == 0

        documents = list(db.scalars(select(Document).where(Document.project_id == project.id)).all())
        assert len(documents) == 3
        assert db.scalar(select(func.count(DocumentVersion.id))) == 3
        assert db.scalar(select(func.count(IndexTask.id))) == 0
        assert {document.parse_status for document in documents} == {"unparsed"}
        assert {document.index_status for document in documents} == {"not_indexed"}

        duplicate_document = next(document for document in documents if document.file_name == "duplicate.pdf")
        metadata = json.loads(duplicate_document.remark or "{}")
        assert metadata["import_source"] == "project_directory_import"
        assert metadata["source_relative_path"] == "设计\\3）设备\\设备资料\\duplicate.pdf"
        assert metadata["source_sha256"]
        assert set(metadata["source_relative_paths"]) == {
            "设计\\3）设备\\设备资料\\duplicate.pdf",
            "项目管理\\3）设备\\设备资料\\duplicate.pdf",
        }
        assert metadata["duplicate_source_paths"] == ["项目管理\\3）设备\\设备资料\\duplicate.pdf"]

        categories = list(
            db.scalars(
                select(KnowledgeCategory).where(
                    KnowledgeCategory.project_id == project.id,
                    KnowledgeCategory.scope_type == "project",
                    KnowledgeCategory.is_deleted.is_(False),
                )
            ).all()
        )
        root_by_code = {category.code: category for category in categories if category.parent_id is None}
        d03 = next(category for category in categories if category.parent_id == root_by_code["D"].id and category.code == "03")
        p02 = next(category for category in categories if category.parent_id == root_by_code["P"].id and category.code == "02")
        assert any(category.parent_id == d03.id and category.name == "设备资料" for category in categories)
        assert any(category.parent_id == p02.id and category.name == "03采购合同" for category in categories)
    finally:
        db.close()
        get_settings.cache_clear()
