"""Project directory import service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppException
from app.core.project_directory_template import DEFAULT_PROJECT_DIRECTORY_TEMPLATE
from app.core.security_levels import DEFAULT_SECURITY_LEVEL, normalize_security_level
from app.models.document import Document
from app.models.knowledge_category import KnowledgeCategory
from app.models.project import Project
from app.models.user import User
from app.repositories.knowledge_base_repository import KnowledgeBaseRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.user_repository import UserRepository
from app.schemas.knowledge_category import KnowledgeCategoryCreate
from app.schemas.project import ProjectCreate
from app.services.document_service import (
    INDEX_STATUS_INDEXED,
    PARSE_STATUS_SUCCESS,
    PROJECT_DOCUMENT_STATUS_PUBLISHED,
    REVIEW_STATUS_APPROVED,
    DocumentService,
)
from app.services.knowledge_category_service import KnowledgeCategoryService
from app.services.project_service import ProjectService
from app.services.system_service import SystemService
from app.utils.time_utils import now_utc

logger = logging.getLogger(__name__)

ACTION_IMPORT_PROJECT_DIRECTORY = "导入项目目录"
ACTION_REMOVE_DUPLICATE_PROJECT_IMPORTS = "清理项目导入重复数据"
TARGET_TYPE_PROJECT = "project"
IMPORT_SOURCE = "project_directory_import"
LEGACY_ARCHIVE_IMPORT_SOURCE = "archive_original_second_level_import"
SUPPORTED_IMPORT_SOURCES = frozenset({IMPORT_SOURCE, LEGACY_ARCHIVE_IMPORT_SOURCE})
DEFAULT_PLACEHOLDER = "待补充"
DEFAULT_PROJECT_DESCRIPTION = "BC2413 西班牙LFP项目资料建档导入"
DIRECTORY_CODE_PREFIX = "IMP-"
HASH_CHUNK_SIZE = 1024 * 1024 * 4

KNOWLEDGE_FILE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
}
PARSABLE_FILE_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".txt",
    ".md",
    ".csv",
}
FILE_SCOPE_EXTENSIONS = {
    "knowledge": KNOWLEDGE_FILE_EXTENSIONS,
    "parsable": PARSABLE_FILE_EXTENSIONS,
}
BLOCKED_EXTENSIONS = {
    ".dwg",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".bz2",
    ".xz",
    ".eml",
    ".msg",
    ".step",
    ".stp",
    ".igs",
    ".iges",
    ".x_t",
    ".sldasm",
    ".sldprt",
    ".ifc",
    ".rvt",
    ".bak",
    ".tmp",
    ".temp",
    ".old",
    ".swp",
    ".dwl",
    ".dwl2",
    ".lnk",
}
BLOCKED_FILE_NAMES = {"thumbs.db", ".ds_store"}
ROOT_PRIORITY = {"公用信息": 0, "设计": 1, "采购": 2, "项目管理": 3}

TEMPLATE_ROOT_CODES = {root_code for root_code, _root_name, _children in DEFAULT_PROJECT_DIRECTORY_TEMPLATE}
TEMPLATE_CHILD_CODES_BY_ROOT = {
    root_code: {child_code for child_code, _child_name in children}
    for root_code, _root_name, children in DEFAULT_PROJECT_DIRECTORY_TEMPLATE
}


@dataclass(frozen=True, slots=True)
class ImportAnchor:
    """导入目录在项目默认目录模板中的锚点。"""

    root_code: str
    child_code: str | None
    consumed_parts: int


@dataclass(frozen=True, slots=True)
class ScannedFile:
    """扫描阶段保留的文件信息，供去重、建档和报告复用。"""

    path: Path
    relative_path: str
    relative_parts: tuple[str, ...]
    extension: str
    file_size: int
    sha256: str
    modified_at: float


@dataclass(frozen=True, slots=True)
class ImportCandidate:
    """按 SHA-256 去重后的单个导入候选。"""

    sha256: str
    canonical: ScannedFile
    source_files: tuple[ScannedFile, ...]


@dataclass(frozen=True, slots=True)
class ScanResult:
    scanned_files: int
    scanned_directories: int
    included_files: tuple[ScannedFile, ...]
    skipped_files: int
    skipped_by_extension: dict[str, int]
    failed_files: list[dict[str, str]]
    limited: bool


class ProjectDirectoryImportService:
    """项目目录导入服务，仅建档保存原始文件，不触发解析、发布或索引。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.project_repository = ProjectRepository(db)
        self.kb_repository = KnowledgeBaseRepository(db)
        self.user_repository = UserRepository(db)
        self.project_service = ProjectService(db)
        self.category_service = KnowledgeCategoryService(db)
        self.document_service = DocumentService(db)

    def import_directory(
        self,
        *,
        source: str | Path,
        operator_username: str,
        project_code: str = "BC2413",
        project_name: str = "西班牙LFP项目",
        project_short_name: str | None = None,
        client: str = DEFAULT_PLACEHOLDER,
        manager: str = DEFAULT_PLACEHOLDER,
        description: str | None = None,
        status: str = "进行中",
        security_level: str = DEFAULT_SECURITY_LEVEL,
        file_scope: str = "knowledge",
        dry_run: bool = True,
        resume_project_id: int | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        """执行项目资料目录导入，并返回可审计的汇总报告。"""

        started_at = time.perf_counter()
        source_path = self._resolve_source_path(source)
        normalized_security_level = normalize_security_level(security_level, default=DEFAULT_SECURITY_LEVEL)
        operator = self._resolve_operator(operator_username)
        existing_project = self.project_repository.get_by_code(project_code)
        project = self._resolve_existing_project(
            project_code=project_code,
            resume_project_id=resume_project_id,
            existing_project=existing_project,
        )

        extensions = self._extensions_for_scope(file_scope)
        scan_result = self._scan_source_directory(
            source_path=source_path,
            file_scope=file_scope,
            extensions=extensions,
            limit=limit,
        )
        candidates = self._deduplicate_files(scan_result.included_files)
        existing_hashes = self._existing_import_hashes(project.id) if project is not None else set()
        import_candidates = [candidate for candidate in candidates if candidate.sha256 not in existing_hashes]
        planned_directory_count = self._planned_directory_count(import_candidates)
        report = self._build_base_report(
            source_path=source_path,
            project_code=project_code,
            project_name=project_name,
            file_scope=file_scope,
            dry_run=dry_run,
            scan_result=scan_result,
            candidates=candidates,
            import_candidates=import_candidates,
            existing_hashes=existing_hashes,
            planned_directory_count=planned_directory_count,
            started_at=started_at,
        )
        if dry_run:
            logger.info(
                "项目目录导入 dry-run 完成: project_code=%s source=%s included=%s unique=%s would_import=%s",
                project_code,
                source_path,
                report["included_files"],
                report["unique_content_files"],
                report["would_import_documents"],
            )
            return report

        project = project or self._create_project(
            operator=operator,
            project_code=project_code,
            project_name=project_name,
            project_short_name=project_short_name,
            client=client,
            manager=manager,
            description=description or DEFAULT_PROJECT_DESCRIPTION,
            status=status,
            security_level=normalized_security_level,
        )
        self._ensure_default_project_directories(project.id, operator)
        knowledge_base = self.kb_repository.get_project_base(project.id)
        if knowledge_base is None:
            raise AppException(f"项目 {project.code} 缺少项目知识库，无法导入资料", status_code=400, code=400)

        category_lookup = self._load_category_lookup(project.id)
        imported_documents = 0
        created_directories = 0
        imported_document_ids: list[int] = []
        failed_files = list(scan_result.failed_files)

        for candidate in import_candidates:
            try:
                category, created_count = self._ensure_candidate_category(
                    project_id=project.id,
                    candidate=candidate,
                    operator=operator,
                    security_level=normalized_security_level,
                    category_lookup=category_lookup,
                )
                created_directories += created_count
                remark = self._candidate_remark(
                    source_path=source_path,
                    project_code=project_code,
                    candidate=candidate,
                )
                document = self.document_service.create_imported_project_document(
                    knowledge_base.id,
                    candidate.canonical.path,
                    operator,
                    category.id,
                    security_level=normalized_security_level,
                    remark=remark,
                )
                imported_documents += 1
                imported_document_ids.append(document.id)
            except Exception as exc:
                self.db.rollback()
                failed_files.append(
                    {
                        "relative_path": candidate.canonical.relative_path,
                        "error": self._safe_error_message(exc),
                    }
                )
                logger.exception(
                    "项目目录导入单文件失败: project_id=%s relative_path=%s sha256=%s",
                    project.id,
                    candidate.canonical.relative_path,
                    candidate.sha256,
                )

        report.update(
            {
                "project_id": project.id,
                "knowledge_base_id": knowledge_base.id,
                "imported_documents": imported_documents,
                "created_directories": created_directories,
                "failed_files": failed_files,
                "failed_file_count": len(failed_files),
                "imported_document_ids_sample": imported_document_ids[:20],
                "elapsed_ms": self._elapsed_ms(started_at),
            }
        )
        self._record_import_operation(operator, project, report)
        logger.info(
            "项目目录导入完成: project_id=%s project_code=%s imported=%s failed=%s elapsed_ms=%s",
            project.id,
            project.code,
            imported_documents,
            len(failed_files),
            report["elapsed_ms"],
        )
        return report

    def remove_duplicate_imports(
        self,
        *,
        project_id: int,
        operator_username: str,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """清理同一项目中由目录导入产生的重复内容文档。"""

        started_at = time.perf_counter()
        operator = self._resolve_operator(operator_username)
        project = self.project_repository.get(project_id)
        if project is None or project.is_deleted:
            raise AppException(f"项目不存在或已删除：{project_id}", status_code=404, code=404)
        self.document_service.access_service.ensure_project_access(
            project.id,
            operator,
            permission_codes=("project:document:delete",),
        )

        duplicate_groups = self._existing_duplicate_import_groups(project.id)
        duplicate_document_ids = [
            duplicate.id
            for _source_sha256, _keeper, duplicates in duplicate_groups
            for duplicate in duplicates
        ]
        report: dict[str, Any] = {
            "dry_run": dry_run,
            "project_id": project.id,
            "project_code": project.code,
            "duplicate_group_count": len(duplicate_groups),
            "duplicate_document_count": len(duplicate_document_ids),
            "would_remove_documents": len(duplicate_document_ids),
            "duplicate_document_ids_sample": duplicate_document_ids[:100],
            "keeper_document_ids_sample": [keeper.id for _hash, keeper, _duplicates in duplicate_groups[:100]],
            "removed_documents": 0,
            "deleted_chunks": 0,
            "deleted_pages": 0,
            "failed_documents": [],
            "failed_document_count": 0,
            "elapsed_ms": self._elapsed_ms(started_at),
        }
        if dry_run:
            logger.info(
                "项目导入重复数据 dry-run 完成: project_id=%s groups=%s would_remove=%s",
                project.id,
                len(duplicate_groups),
                len(duplicate_document_ids),
            )
            return report

        removed_documents = 0
        deleted_chunks = 0
        deleted_pages = 0
        failed_documents: list[dict[str, Any]] = []
        for source_sha256, keeper, duplicates in duplicate_groups:
            for duplicate in duplicates:
                duplicate_id = duplicate.id
                try:
                    keeper.remark = self._merged_import_remark(keeper, (duplicate,))
                    cleanup = self.document_service.purge_document(duplicate_id, operator)
                    removed_documents += 1
                    deleted_chunks += int(cleanup["document_chunks"])
                    deleted_pages += int(cleanup["document_pages"])
                except Exception as exc:
                    self.db.rollback()
                    failed_documents.append(
                        {
                            "source_sha256": source_sha256,
                            "keeper_document_id": keeper.id,
                            "duplicate_document_id": duplicate_id,
                            "error": self._safe_error_message(exc),
                        }
                    )
                    logger.exception(
                        "项目导入重复文档物理删除失败: project_id=%s keeper_id=%s duplicate_id=%s",
                        project.id,
                        keeper.id,
                        duplicate_id,
                    )

        report.update(
            {
                "removed_documents": removed_documents,
                "deleted_chunks": deleted_chunks,
                "deleted_pages": deleted_pages,
                "failed_documents": failed_documents,
                "failed_document_count": len(failed_documents),
                "elapsed_ms": self._elapsed_ms(started_at),
            }
        )
        detail = json.dumps(
            {
                key: report[key]
                for key in (
                    "project_code",
                    "duplicate_group_count",
                    "duplicate_document_count",
                    "removed_documents",
                    "deleted_chunks",
                    "deleted_pages",
                    "failed_document_count",
                    "elapsed_ms",
                )
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        SystemService(self.db).record_operation(
            operator,
            ACTION_REMOVE_DUPLICATE_PROJECT_IMPORTS,
            TARGET_TYPE_PROJECT,
            project.id,
            detail,
            result="success" if not failed_documents else "partial_failed",
            project_id=project.id,
            auto_commit=True,
        )
        logger.info(
            "项目导入重复数据清理完成: project_id=%s removed=%s elapsed_ms=%s",
            project.id,
            removed_documents,
            report["elapsed_ms"],
        )
        return report

    def _resolve_source_path(self, source: str | Path) -> Path:
        source_path = Path(source).expanduser()
        try:
            source_path = source_path.resolve()
        except OSError:
            source_path = source_path.absolute()
        if not source_path.is_dir():
            raise AppException(f"导入源目录不存在或不是目录：{source_path}", status_code=400, code=400)
        return source_path

    def _resolve_operator(self, operator_username: str) -> User:
        operator = self.user_repository.get_by_username(operator_username)
        if operator is None:
            raise AppException(f"导入操作人不存在：{operator_username}", status_code=404, code=404)
        return operator

    def _resolve_existing_project(
        self,
        *,
        project_code: str,
        resume_project_id: int | None,
        existing_project: Project | None,
    ) -> Project | None:
        if existing_project is not None and resume_project_id is None:
            raise AppException(
                f"项目编号 {project_code} 已存在；如需继续导入，请指定 --resume-project-id {existing_project.id}",
                status_code=409,
                code=409,
            )
        if resume_project_id is None:
            return None
        project = self.project_repository.get(resume_project_id)
        if project is None or project.is_deleted:
            raise AppException(f"续导项目不存在或已删除：{resume_project_id}", status_code=404, code=404)
        if project.code != project_code:
            raise AppException(
                f"续导项目编号不匹配：project_id={resume_project_id} code={project.code} expected={project_code}",
                status_code=400,
                code=400,
            )
        return project

    def _extensions_for_scope(self, file_scope: str) -> set[str] | None:
        if file_scope == "all":
            return None
        extensions = FILE_SCOPE_EXTENSIONS.get(file_scope)
        if extensions is None:
            raise AppException("file-scope 仅支持 knowledge、parsable 或 all", status_code=400, code=400)
        return extensions

    def _scan_source_directory(
        self,
        *,
        source_path: Path,
        file_scope: str,
        extensions: set[str] | None,
        limit: int | None,
    ) -> ScanResult:
        scanned_files = 0
        scanned_directories = 0
        skipped_files = 0
        skipped_by_extension: dict[str, int] = {}
        failed_files: list[dict[str, str]] = []
        included_files: list[ScannedFile] = []
        limited = False

        for current_dir, dir_names, file_names in os.walk(source_path):
            scanned_directories += len(dir_names)
            for file_name in file_names:
                scanned_files += 1
                path = Path(current_dir) / file_name
                extension = path.suffix.lower()
                skip_reason = self._skip_reason(path.name, extension, file_scope, extensions)
                if skip_reason:
                    skipped_files += 1
                    key = extension or "[no-extension]"
                    skipped_by_extension[key] = skipped_by_extension.get(key, 0) + 1
                    continue
                try:
                    stat = path.stat()
                    relative = path.relative_to(source_path)
                    relative_parts = tuple(relative.parts)
                    included_files.append(
                        ScannedFile(
                            path=path,
                            relative_path="\\".join(relative_parts),
                            relative_parts=relative_parts,
                            extension=extension,
                            file_size=int(stat.st_size),
                            sha256=self._sha256_file(path),
                            modified_at=float(stat.st_mtime),
                        )
                    )
                except OSError as exc:
                    failed_files.append({"relative_path": str(path), "error": self._safe_error_message(exc)})
                    logger.warning("项目目录扫描文件失败: path=%s error=%s", path, exc)
                if limit is not None and len(included_files) >= limit:
                    limited = True
                    break
            if limited:
                break

        return ScanResult(
            scanned_files=scanned_files,
            scanned_directories=scanned_directories,
            included_files=tuple(included_files),
            skipped_files=skipped_files,
            skipped_by_extension=dict(sorted(skipped_by_extension.items())),
            failed_files=failed_files,
            limited=limited,
        )

    def _skip_reason(
        self,
        file_name: str,
        extension: str,
        file_scope: str,
        extensions: set[str] | None,
    ) -> str | None:
        lower_name = file_name.lower()
        if lower_name in BLOCKED_FILE_NAMES or lower_name.startswith("~$"):
            return "temporary_file"
        if extension in BLOCKED_EXTENSIONS:
            return "blocked_extension"
        if file_scope != "all" and extensions is not None and extension not in extensions:
            return "unsupported_extension"
        return None

    def _sha256_file(self, path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source_file:
            for chunk in iter(lambda: source_file.read(HASH_CHUNK_SIZE), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def _deduplicate_files(self, files: tuple[ScannedFile, ...]) -> list[ImportCandidate]:
        groups: dict[str, list[ScannedFile]] = {}
        for file_item in files:
            groups.setdefault(file_item.sha256, []).append(file_item)
        candidates: list[ImportCandidate] = []
        for sha256, source_files in groups.items():
            ordered_files = tuple(sorted(source_files, key=self._canonical_sort_key))
            candidates.append(ImportCandidate(sha256=sha256, canonical=ordered_files[0], source_files=ordered_files))
        return sorted(candidates, key=lambda item: item.canonical.relative_path.casefold())

    def _canonical_sort_key(self, file_item: ScannedFile) -> tuple[int, int, int, str]:
        root_name = file_item.relative_parts[0] if file_item.relative_parts else ""
        return (
            ROOT_PRIORITY.get(root_name, 50),
            len(file_item.relative_parts),
            len(file_item.relative_path),
            file_item.relative_path.casefold(),
        )

    def _existing_import_hashes(self, project_id: int) -> set[str]:
        hashes: set[str] = set()
        remarks = self.db.scalars(
            select(Document.remark).where(
                Document.project_id == project_id,
                Document.is_deleted.is_(False),
                Document.remark.is_not(None),
            )
        ).all()
        for remark in remarks:
            if not remark:
                continue
            try:
                metadata = json.loads(remark)
            except json.JSONDecodeError:
                continue
            if not isinstance(metadata, dict):
                continue
            if metadata.get("import_source") == IMPORT_SOURCE or metadata.get("source_sha256"):
                source_sha256 = metadata.get("source_sha256")
                if isinstance(source_sha256, str) and source_sha256:
                    hashes.add(source_sha256)
        return hashes

    def _existing_duplicate_import_groups(
        self,
        project_id: int,
    ) -> list[tuple[str, Document, tuple[Document, ...]]]:
        documents = self.db.scalars(
            select(Document).where(
                Document.project_id == project_id,
                Document.is_deleted.is_(False),
                Document.remark.is_not(None),
            )
        ).all()
        by_hash: dict[str, list[Document]] = {}
        for document in documents:
            metadata = self._import_metadata(document.remark)
            if metadata is None or metadata.get("import_source") not in SUPPORTED_IMPORT_SOURCES:
                continue
            source_sha256 = metadata.get("source_sha256")
            if not isinstance(source_sha256, str) or not source_sha256.strip():
                continue
            by_hash.setdefault(source_sha256.strip().lower(), []).append(document)

        groups: list[tuple[str, Document, tuple[Document, ...]]] = []
        for source_sha256, grouped_documents in by_hash.items():
            if len(grouped_documents) < 2:
                continue
            ordered_documents = sorted(grouped_documents, key=self._duplicate_keeper_sort_key)
            groups.append((source_sha256, ordered_documents[0], tuple(ordered_documents[1:])))
        return sorted(groups, key=lambda group: (group[1].id, group[0]))

    def _duplicate_keeper_sort_key(self, document: Document) -> tuple[int, int, int, str, int]:
        workflow_score = 0
        if document.status == PROJECT_DOCUMENT_STATUS_PUBLISHED:
            workflow_score += 8
        if document.index_status == INDEX_STATUS_INDEXED:
            workflow_score += 4
        if document.parse_status == PARSE_STATUS_SUCCESS:
            workflow_score += 2
        if document.review_status == REVIEW_STATUS_APPROVED:
            workflow_score += 1
        metadata = self._import_metadata(document.remark) or {}
        relative_path = str(metadata.get("source_relative_path") or document.file_name or "")
        normalized_parts = tuple(part for part in re.split(r"[\\/]", relative_path) if part)
        root_name = normalized_parts[0] if normalized_parts else ""
        return (
            -workflow_score,
            ROOT_PRIORITY.get(root_name, 50),
            len(normalized_parts),
            relative_path.casefold(),
            document.id,
        )

    def _merged_import_remark(self, keeper: Document, duplicates: tuple[Document, ...]) -> str:
        keeper_metadata = dict(self._import_metadata(keeper.remark) or {})
        keeper_path = str(keeper_metadata.get("source_relative_path") or "").strip()
        all_paths: list[str] = []
        for document in (keeper, *duplicates):
            metadata = self._import_metadata(document.remark) or {}
            metadata_paths = metadata.get("source_relative_paths")
            if isinstance(metadata_paths, list):
                all_paths.extend(str(path).strip() for path in metadata_paths if str(path).strip())
            source_relative_path = str(metadata.get("source_relative_path") or "").strip()
            if source_relative_path:
                all_paths.append(source_relative_path)
        unique_paths = list(dict.fromkeys(all_paths))
        if keeper_path:
            unique_paths = [keeper_path, *(path for path in unique_paths if path != keeper_path)]
        keeper_metadata["source_relative_paths"] = unique_paths
        keeper_metadata["duplicate_source_paths"] = [path for path in unique_paths if path != keeper_path]
        existing_document_ids = keeper_metadata.get("deduplicated_document_ids")
        deduplicated_document_ids = (
            [int(document_id) for document_id in existing_document_ids if isinstance(document_id, int)]
            if isinstance(existing_document_ids, list)
            else []
        )
        deduplicated_document_ids.extend(document.id for document in duplicates)
        keeper_metadata["deduplicated_document_ids"] = list(dict.fromkeys(deduplicated_document_ids))
        keeper_metadata["deduplicated_at"] = now_utc().isoformat()
        return json.dumps(keeper_metadata, ensure_ascii=False, sort_keys=True)

    def _import_metadata(self, remark: str | None) -> dict[str, Any] | None:
        if not remark:
            return None
        try:
            metadata = json.loads(remark)
        except (json.JSONDecodeError, TypeError):
            return None
        return metadata if isinstance(metadata, dict) else None

    def _planned_directory_count(self, candidates: list[ImportCandidate]) -> int:
        planned_keys: set[str] = set()
        for candidate in candidates:
            anchor, residual_dirs = self._directory_plan(candidate.canonical)
            parts: list[str] = []
            for directory_name in residual_dirs:
                parts.append(directory_name)
                planned_keys.add(f"{anchor.root_code}/{anchor.child_code or ''}/{'/'.join(parts)}")
        return len(planned_keys)

    def _build_base_report(
        self,
        *,
        source_path: Path,
        project_code: str,
        project_name: str,
        file_scope: str,
        dry_run: bool,
        scan_result: ScanResult,
        candidates: list[ImportCandidate],
        import_candidates: list[ImportCandidate],
        existing_hashes: set[str],
        planned_directory_count: int,
        started_at: float,
    ) -> dict[str, Any]:
        duplicate_group_count = sum(1 for candidate in candidates if len(candidate.source_files) > 1)
        duplicate_file_count = scan_result.included_files and len(scan_result.included_files) - len(candidates)
        return {
            "dry_run": dry_run,
            "source": str(source_path),
            "project_code": project_code,
            "project_name": project_name,
            "file_scope": file_scope,
            "scanned_files": scan_result.scanned_files,
            "scanned_directories": scan_result.scanned_directories,
            "included_files": len(scan_result.included_files),
            "skipped_files": scan_result.skipped_files,
            "skipped_by_extension": scan_result.skipped_by_extension,
            "unique_content_files": len(candidates),
            "duplicate_group_count": duplicate_group_count,
            "duplicate_file_count": int(duplicate_file_count or 0),
            "existing_import_hash_count": len(existing_hashes),
            "existing_duplicate_files": len(candidates) - len(import_candidates),
            "would_import_documents": len(import_candidates),
            "planned_directory_count": planned_directory_count,
            "failed_files": list(scan_result.failed_files),
            "failed_file_count": len(scan_result.failed_files),
            "limited": scan_result.limited,
            "elapsed_ms": self._elapsed_ms(started_at),
        }

    def _create_project(
        self,
        *,
        operator: User,
        project_code: str,
        project_name: str,
        project_short_name: str | None,
        client: str,
        manager: str,
        description: str,
        status: str,
        security_level: str,
    ) -> Project:
        result = self.project_service.create_project(
            ProjectCreate(
                name=project_name,
                code=project_code,
                project_short_name=project_short_name or project_name,
                client=client,
                manager=manager,
                status=status,
                security_level=security_level,
                description=description,
            ),
            operator,
        )
        project = self.project_repository.get(int(result["id"]))
        if project is None:
            raise AppException(f"项目创建后无法读取：{project_code}", status_code=500, code=500)
        return project

    def _ensure_default_project_directories(self, project_id: int, operator: User) -> None:
        categories = self.category_service.repository.list_by_scope("project", project_id)
        by_parent_code = {(category.parent_id, category.code) for category in categories}
        root_id_by_code = {category.code: category.id for category in categories if category.parent_id is None}
        missing = False
        for root_code, _root_name, children in DEFAULT_PROJECT_DIRECTORY_TEMPLATE:
            root_id = root_id_by_code.get(root_code)
            if root_id is None:
                missing = True
                break
            for child_code, _child_name in children:
                if (root_id, child_code) not in by_parent_code:
                    missing = True
                    break
            if missing:
                break
        if missing:
            self.category_service.init_default_project_template(project_id, operator)

    def _load_category_lookup(self, project_id: int) -> dict[tuple[int | None, str], KnowledgeCategory]:
        return {
            (category.parent_id, category.code): category
            for category in self.category_service.repository.list_by_scope("project", project_id)
        }

    def _ensure_candidate_category(
        self,
        *,
        project_id: int,
        candidate: ImportCandidate,
        operator: User,
        security_level: str,
        category_lookup: dict[tuple[int | None, str], KnowledgeCategory],
    ) -> tuple[KnowledgeCategory, int]:
        anchor, residual_dirs = self._directory_plan(candidate.canonical)
        parent = self._anchor_category(anchor, category_lookup)
        created_count = 0
        consumed_dirs: list[str] = []
        for directory_name in residual_dirs:
            normalized_name = self._safe_category_name(directory_name)
            consumed_dirs.append(directory_name)
            source_key = f"{anchor.root_code}/{anchor.child_code or ''}/{'/'.join(consumed_dirs)}"
            directory_code = self._directory_code(source_key)
            existing = category_lookup.get((parent.id, directory_code))
            if existing is None:
                existing = self.category_service.create_category(
                    KnowledgeCategoryCreate(
                        scope_type="project",
                        project_id=project_id,
                        parent_id=parent.id,
                        name=normalized_name,
                        code=self._unique_directory_code(parent.id, directory_code, category_lookup),
                        description=self._category_description(directory_name),
                        sort_order=10000 + len(category_lookup),
                        enabled=True,
                        default_security_level=security_level,
                    ),
                    operator,
                )
                category_lookup[(existing.parent_id, existing.code)] = existing
                created_count += 1
            parent = existing
        return parent, created_count

    def _anchor_category(
        self,
        anchor: ImportAnchor,
        category_lookup: dict[tuple[int | None, str], KnowledgeCategory],
    ) -> KnowledgeCategory:
        root = category_lookup.get((None, anchor.root_code))
        if root is None:
            raise AppException(f"项目默认目录缺失：{anchor.root_code}", status_code=400, code=400)
        if anchor.child_code is None:
            return root
        child = category_lookup.get((root.id, anchor.child_code))
        if child is None:
            raise AppException(f"项目默认目录缺失：{anchor.root_code}/{anchor.child_code}", status_code=400, code=400)
        return child

    def _directory_plan(self, file_item: ScannedFile) -> tuple[ImportAnchor, tuple[str, ...]]:
        anchor = self._resolve_anchor(file_item.relative_parts)
        directory_parts = file_item.relative_parts[:-1]
        residual_dirs = tuple(directory_parts[anchor.consumed_parts :])
        return anchor, residual_dirs

    def _resolve_anchor(self, relative_parts: tuple[str, ...]) -> ImportAnchor:
        directory_parts = relative_parts[:-1]
        for index, segment in enumerate(directory_parts):
            explicit_anchor = self._explicit_template_anchor(segment, index + 1)
            if explicit_anchor is not None:
                return explicit_anchor
        if not directory_parts:
            return ImportAnchor("A", None, 0)

        top = directory_parts[0].strip()
        if "设计" in top:
            return self._design_anchor(directory_parts)
        if "采购" in top:
            return self._purchase_anchor(directory_parts)
        if "项目管理" in top:
            return self._project_management_anchor(directory_parts)
        if "公用信息" in top:
            consumed_parts = 2 if len(directory_parts) > 1 and "公用信息" in directory_parts[1] else 1
            return ImportAnchor("A", None, consumed_parts)
        return ImportAnchor("A", None, 0)

    def _explicit_template_anchor(self, segment: str, consumed_parts: int) -> ImportAnchor | None:
        code = self._leading_letter_code(segment)
        if code is None:
            return None
        if code in TEMPLATE_ROOT_CODES:
            return ImportAnchor(code, None, consumed_parts)
        for root_code, child_codes in TEMPLATE_CHILD_CODES_BY_ROOT.items():
            if code in child_codes:
                return ImportAnchor(root_code, code, consumed_parts)
        if code.startswith("P") and code[1:] in TEMPLATE_CHILD_CODES_BY_ROOT["P"]:
            return ImportAnchor("P", code[1:], consumed_parts)
        if code.startswith("D") and code[1:] in TEMPLATE_CHILD_CODES_BY_ROOT["D"]:
            return ImportAnchor("D", code[1:], consumed_parts)
        return None

    def _design_anchor(self, directory_parts: tuple[str, ...]) -> ImportAnchor:
        code = self._leading_numeric_code(directory_parts[1]) if len(directory_parts) > 1 else None
        if code in TEMPLATE_CHILD_CODES_BY_ROOT["D"]:
            return ImportAnchor("D", code, 2)
        return ImportAnchor("E", None, 1)

    def _purchase_anchor(self, directory_parts: tuple[str, ...]) -> ImportAnchor:
        code = self._leading_numeric_code(directory_parts[1]) if len(directory_parts) > 1 else None
        if code in TEMPLATE_CHILD_CODES_BY_ROOT["P"]:
            return ImportAnchor("P", code, 2)
        return ImportAnchor("P", None, 1)

    def _project_management_anchor(self, directory_parts: tuple[str, ...]) -> ImportAnchor:
        if len(directory_parts) == 1:
            return ImportAnchor("A", None, 1)
        second = directory_parts[1]
        if "采购" in second:
            code = self._leading_numeric_code(second) or "02"
            if code in TEMPLATE_CHILD_CODES_BY_ROOT["P"]:
                return ImportAnchor("P", code, 2)
            return ImportAnchor("P", None, 2)
        if "项目管理" in second:
            third_code = self._leading_numeric_code(directory_parts[2]) if len(directory_parts) > 2 else None
            child_code = f"A{third_code}" if third_code and f"A{third_code}" in TEMPLATE_CHILD_CODES_BY_ROOT["A"] else None
            if child_code:
                return ImportAnchor("A", child_code, 3)
            return ImportAnchor("A", None, 2)
        if "公用信息" in second:
            return ImportAnchor("A", None, 2)
        code = self._leading_numeric_code(second)
        if code in TEMPLATE_CHILD_CODES_BY_ROOT["D"]:
            return ImportAnchor("D", code, 2)
        return ImportAnchor("A", None, 1)

    def _leading_letter_code(self, segment: str) -> str | None:
        match = re.match(r"^\s*([ADEP])(?:\s*[-_ ]?(\d{1,2}))?", segment, re.IGNORECASE)
        if not match:
            return None
        letter = match.group(1).upper()
        digits = match.group(2)
        if digits is None:
            next_index = match.end(1)
            next_char = segment[next_index : next_index + 1]
            if next_char and next_char.isascii() and next_char.isalnum():
                return None
        return f"{letter}{digits}" if digits else letter

    def _leading_numeric_code(self, segment: str) -> str | None:
        match = re.match(r"^\s*(\d{1,2})", segment)
        if not match:
            return None
        value = int(match.group(1))
        return f"{value:02d}"

    def _directory_code(self, source_key: str) -> str:
        digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()[:12].upper()
        return f"{DIRECTORY_CODE_PREFIX}{digest}"

    def _unique_directory_code(
        self,
        parent_id: int,
        base_code: str,
        category_lookup: dict[tuple[int | None, str], KnowledgeCategory],
    ) -> str:
        if (parent_id, base_code) not in category_lookup:
            return base_code
        suffix = 2
        while True:
            suffix_text = f"-{suffix}"
            candidate = f"{base_code[: 100 - len(suffix_text)]}{suffix_text}"
            if (parent_id, candidate) not in category_lookup:
                return candidate
            suffix += 1

    def _safe_category_name(self, name: str) -> str:
        normalized = name.strip() or "未命名目录"
        return normalized[:100]

    def _category_description(self, original_name: str) -> str | None:
        if len(original_name) <= 100:
            return f"导入目录：{original_name}"
        return f"导入目录原始名称：{original_name}"

    def _candidate_remark(self, *, source_path: Path, project_code: str, candidate: ImportCandidate) -> str:
        source_relative_paths = [source_file.relative_path for source_file in candidate.source_files]
        metadata = {
            "import_source": IMPORT_SOURCE,
            "project_code": project_code,
            "source_root": str(source_path),
            "source_relative_path": candidate.canonical.relative_path,
            "source_relative_paths": source_relative_paths,
            "duplicate_source_paths": [
                source_file.relative_path
                for source_file in candidate.source_files
                if source_file.relative_path != candidate.canonical.relative_path
            ],
            "source_sha256": candidate.sha256,
            "source_file_size": candidate.canonical.file_size,
            "source_modified_at": datetime.fromtimestamp(candidate.canonical.modified_at).isoformat(),
        }
        return json.dumps(metadata, ensure_ascii=False, sort_keys=True)

    def _record_import_operation(self, operator: User, project: Project, report: dict[str, Any]) -> None:
        detail_keys = (
            "source",
            "project_code",
            "file_scope",
            "scanned_files",
            "included_files",
            "skipped_files",
            "unique_content_files",
            "duplicate_file_count",
            "would_import_documents",
            "imported_documents",
            "created_directories",
            "failed_file_count",
            "elapsed_ms",
        )
        detail = json.dumps({key: report.get(key) for key in detail_keys}, ensure_ascii=False, sort_keys=True)
        result = "success" if report.get("failed_file_count", 0) == 0 else "partial_failed"
        SystemService(self.db).record_operation(
            operator,
            ACTION_IMPORT_PROJECT_DIRECTORY,
            TARGET_TYPE_PROJECT,
            project.id,
            detail,
            result=result,
            project_id=project.id,
            auto_commit=True,
        )

    def _elapsed_ms(self, started_at: float) -> int:
        return int((time.perf_counter() - started_at) * 1000)

    def _safe_error_message(self, exc: Exception) -> str:
        message = str(exc).strip()
        return message[:500] if message else exc.__class__.__name__
