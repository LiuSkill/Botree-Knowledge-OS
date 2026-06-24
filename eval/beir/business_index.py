"""Import BEIR corpora into the real business RAG index."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import logging
from pathlib import Path
import re
import secrets
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from eval.beir.business_mapping import BusinessDocMapping, compute_text_hash, mapping_path, write_doc_id_mapping
from eval.beir.types import BeirCorpus

logger = logging.getLogger(__name__)

SAFE_PROJECT_PREFIX = "EVAL_BEIR_"


@dataclass(frozen=True)
class BusinessIndexConfig:
    """Configuration for importing BEIR data into business tables."""

    dataset: str
    split: str
    business_project_code: str
    business_user_id: str
    business_index_targets: tuple[str, ...] = ("milvus", "bm25", "ripgrep")
    force_reindex: bool = False
    embedding_batch_size: int = 32


@dataclass
class BusinessIndexResult:
    """Business import summary persisted to reports."""

    status: str
    dataset: str
    split: str
    project_id: int
    business_project_code: str
    business_user_id: str
    business_index_targets: tuple[str, ...]
    corpus_count: int
    imported_count: int = 0
    indexed_count: int = 0
    skipped: bool = False
    mapping_path: str = ""
    warnings: list[str] = field(default_factory=list)
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result."""

        return {
            "status": self.status,
            "dataset": self.dataset,
            "split": self.split,
            "project_id": self.project_id,
            "business_project_code": self.business_project_code,
            "business_user_id": self.business_user_id,
            "business_index_targets": list(self.business_index_targets),
            "corpus_count": self.corpus_count,
            "imported_count": self.imported_count,
            "indexed_count": self.indexed_count,
            "skipped": self.skipped,
            "mapping_path": self.mapping_path,
            "warnings": self.warnings,
            "elapsed_ms": self.elapsed_ms,
        }


class BeirBusinessIndexService:
    """Create eval-only business documents and build real RAG indexes."""

    def __init__(self, db: Session, settings: Any, config: BusinessIndexConfig) -> None:
        self.db = db
        self.settings = settings
        self.config = config
        self.targets = _normalize_targets(config.business_index_targets)

    def run(self, corpus: BeirCorpus) -> BusinessIndexResult:
        """Import or reuse BEIR business index data."""

        started_at = time.perf_counter()
        logger.info(
            "stage=business_index status=started dataset=%s split=%s project_code=%s user=%s targets=%s force=%s corpus_count=%s",
            self.config.dataset,
            self.config.split,
            self.config.business_project_code,
            self.config.business_user_id,
            ",".join(self.targets),
            self.config.force_reindex,
            len(corpus),
        )

        user = self._ensure_user()
        project = self._ensure_project(user.id)
        self._ensure_project_member(project.id, user.id)
        knowledge_base = self._ensure_project_knowledge_base(project.id, user.id)
        category = self._ensure_category(project.id, user.id)
        warnings = self._target_warnings()

        if self.config.force_reindex:
            self._clear_eval_documents(project.id)

        path = mapping_path(self.config.dataset)
        if not self.config.force_reindex and self._mapping_ready(path, project.id, len(corpus)):
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            logger.info(
                "stage=business_index status=skipped reason=mapping_ready project_id=%s mapping_path=%s elapsed_ms=%s",
                project.id,
                path,
                elapsed_ms,
            )
            return BusinessIndexResult(
                status="skipped",
                dataset=self.config.dataset,
                split=self.config.split,
                project_id=project.id,
                business_project_code=project.code,
                business_user_id=self.config.business_user_id,
                business_index_targets=self.targets,
                corpus_count=len(corpus),
                imported_count=len(corpus),
                indexed_count=len(corpus),
                skipped=True,
                mapping_path=str(path),
                warnings=warnings,
                elapsed_ms=elapsed_ms,
            )

        rows, chunks = self._import_documents(
            corpus=corpus,
            project_id=project.id,
            user_id=user.id,
            knowledge_base_id=knowledge_base.id,
            category_id=category.id,
        )
        if "milvus" in self.targets:
            self._index_milvus(chunks)
        else:
            logger.info("stage=corpus_indexing status=skipped target=milvus reason=not_requested")

        write_doc_id_mapping(path, rows)
        self.db.commit()
        elapsed_ms = int((time.perf_counter() - started_at) * 1000)
        logger.info(
            "stage=business_index status=completed project_id=%s imported=%s indexed=%s mapping_path=%s elapsed_ms=%s",
            project.id,
            len(rows),
            len(chunks) if "milvus" in self.targets else 0,
            path,
            elapsed_ms,
        )
        return BusinessIndexResult(
            status="indexed",
            dataset=self.config.dataset,
            split=self.config.split,
            project_id=project.id,
            business_project_code=project.code,
            business_user_id=self.config.business_user_id,
            business_index_targets=self.targets,
            corpus_count=len(corpus),
            imported_count=len(rows),
            indexed_count=len(chunks) if "milvus" in self.targets else 0,
            skipped=False,
            mapping_path=str(path),
            warnings=warnings,
            elapsed_ms=elapsed_ms,
        )

    def _ensure_user(self):
        from app.core.security import hash_password
        from app.models.user import User
        from app.repositories.user_repository import UserRepository

        repository = UserRepository(self.db)
        user = repository.get_by_username(self.config.business_user_id)
        if user is not None:
            return user
        user = User(
            username=self.config.business_user_id,
            password_hash=hash_password(secrets.token_urlsafe(32)),
            real_name="BEIR Eval User",
            status="enabled",
            department="evaluation",
        )
        repository.add(user)
        logger.info("stage=business_index action=create_eval_user status=created user_id=%s username=%s", user.id, user.username)
        return user

    def _ensure_project(self, user_id: int):
        from app.models.project import Project
        from app.repositories.project_repository import ProjectRepository

        repository = ProjectRepository(self.db)
        project = repository.get_by_code(self.config.business_project_code)
        if project is not None:
            return project
        project = Project(
            name=self.config.business_project_code,
            code=self.config.business_project_code,
            description=f"BEIR evaluation project for {self.config.dataset}/{self.config.split}",
            client="BEIR",
            manager="beir_eval",
            status="active",
            progress=0,
            created_by=user_id,
        )
        repository.add(project)
        logger.info("stage=business_index action=create_eval_project status=created project_id=%s code=%s", project.id, project.code)
        return project

    def _ensure_project_member(self, project_id: int, user_id: int) -> None:
        from app.models.project import ProjectMember
        from app.repositories.project_repository import ProjectRepository

        repository = ProjectRepository(self.db)
        member = repository.get_member(project_id, user_id)
        if member is None:
            repository.add_member(
                ProjectMember(
                    project_id=project_id,
                    user_id=user_id,
                    role="owner",
                    permission_scope="project_manage",
                    external_user=False,
                    status="active",
                )
            )
            logger.info("stage=business_index action=grant_project_access status=created project_id=%s user_id=%s", project_id, user_id)
            return
        member.role = "owner"
        member.permission_scope = "project_manage"
        member.status = "active"
        logger.info("stage=business_index action=grant_project_access status=ready project_id=%s user_id=%s", project_id, user_id)

    def _ensure_project_knowledge_base(self, project_id: int, user_id: int):
        from app.models.knowledge_base import KnowledgeBase
        from app.repositories.knowledge_base_repository import KnowledgeBaseRepository

        repository = KnowledgeBaseRepository(self.db)
        knowledge_base = repository.get_project_base(project_id)
        if knowledge_base is not None:
            knowledge_base.enabled = True
            return knowledge_base
        code = f"project-{self.config.business_project_code.lower()}"
        knowledge_base = KnowledgeBase(
            name=f"{self.config.business_project_code} Knowledge Base",
            code=code[:100],
            type="project",
            project_id=project_id,
            description=f"BEIR evaluation knowledge base for {self.config.dataset}",
            visibility="private",
            enabled=True,
            created_by=user_id,
        )
        repository.add(knowledge_base)
        logger.info(
            "stage=business_index action=create_project_knowledge_base status=created project_id=%s knowledge_base_id=%s",
            project_id,
            knowledge_base.id,
        )
        return knowledge_base

    def _ensure_category(self, project_id: int, user_id: int):
        from app.models.knowledge_category import KnowledgeCategory
        from app.repositories.knowledge_category_repository import KnowledgeCategoryRepository

        repository = KnowledgeCategoryRepository(self.db)
        category = repository.get_by_code("project", "beir_eval", project_id=project_id)
        if category is not None:
            category.enabled = True
            return category
        category = KnowledgeCategory(
            scope_type="project",
            project_id=project_id,
            name="BEIR Evaluation",
            code="beir_eval",
            description=f"BEIR evaluation corpus for {self.config.dataset}",
            sort_order=0,
            enabled=True,
            created_by=user_id,
        )
        repository.add(category)
        logger.info("stage=business_index action=create_category status=created project_id=%s category_id=%s", project_id, category.id)
        return category

    def _mapping_ready(self, path: Path, project_id: int, corpus_count: int) -> bool:
        from app.models.document import DocumentChunk

        if not path.exists():
            return False
        rows: list[BusinessDocMapping] = []
        try:
            with path.open("r", encoding="utf-8") as file:
                rows = [BusinessDocMapping.from_dict(json.loads(line)) for line in file if line.strip()]
        except Exception:
            logger.warning("stage=business_index action=read_mapping status=failed path=%s", path, exc_info=True)
            return False
        rows = [row for row in rows if row.dataset == self.config.dataset and row.split == self.config.split and row.project_id == project_id]
        if len(rows) != corpus_count:
            return False
        chunk_ids = [row.business_chunk_id for row in rows]
        existing_count = int(
            self.db.scalar(
                select(func.count(DocumentChunk.id)).where(
                    DocumentChunk.id.in_(chunk_ids),
                    DocumentChunk.project_id == project_id,
                    DocumentChunk.chunk_status == "active",
                )
            )
            or 0
        )
        return existing_count == corpus_count

    def _import_documents(
        self,
        corpus: BeirCorpus,
        project_id: int,
        user_id: int,
        knowledge_base_id: int,
        category_id: int,
    ) -> tuple[list[BusinessDocMapping], list[Any]]:
        from app.models.document import Document, DocumentChunk, DocumentVersion
        from app.repositories.document_repository import DocumentRepository
        from app.services.page_index_service import PageIndexService

        repository = DocumentRepository(self.db)
        page_index_service = PageIndexService(self.db)
        rows: list[BusinessDocMapping] = []
        chunks: list[DocumentChunk] = []
        now = datetime.utcnow()
        total = len(corpus)
        logger.info("stage=corpus_indexing status=started action=business_document_import total=%s", total)

        for index, (beir_doc_id, document_payload) in enumerate(corpus.items(), start=1):
            title = str(document_payload.get("title") or "").strip()
            text = str(document_payload.get("text") or "").strip()
            content = _document_content(title, text)
            storage_path = self._write_document_file(beir_doc_id, content)
            file_name = f"{_safe_filename(self.config.dataset)}_{_safe_filename(beir_doc_id)}.txt"
            file_size = Path(storage_path).stat().st_size

            document = repository.add(
                Document(
                    knowledge_base_id=knowledge_base_id,
                    knowledge_type="project",
                    project_id=project_id,
                    file_name=file_name,
                    file_type="txt",
                    file_size=file_size,
                    storage_path=self.settings.to_relative_local_path(storage_path),
                    category_id=category_id,
                    document_status="active",
                    parse_status="success",
                    parse_started_at=now,
                    parse_finished_at=now,
                    review_status="approved",
                    index_status="indexed",
                    version_no=1,
                    current_version=True,
                    created_by=user_id,
                    submitted_by=user_id,
                    reviewed_by=user_id,
                    submitted_at=now,
                    reviewed_at=now,
                    review_comment="BEIR evaluation import",
                    build_started_at=now,
                    built_by=user_id,
                )
            )
            repository.add_version(
                DocumentVersion(
                    document_id=document.id,
                    version_no=1,
                    category_id=category_id,
                    file_name=file_name,
                    file_type="txt",
                    file_size=file_size,
                    storage_path=document.storage_path,
                    change_summary=f"BEIR doc_id={beir_doc_id}",
                    version_status="current",
                    parse_status="success",
                    parse_started_at=now,
                    parse_finished_at=now,
                    review_status="approved",
                    index_status="indexed",
                    is_current=True,
                    reviewed_by=user_id,
                    reviewed_at=now,
                    review_comment="BEIR evaluation import",
                    build_started_at=now,
                    created_by=user_id,
                )
            )
            chunk = DocumentChunk(
                knowledge_base_id=knowledge_base_id,
                document_id=document.id,
                project_id=project_id,
                knowledge_type="project",
                version_no=1,
                chunk_status="active",
                chunk_index=1,
                content=content,
                page_number=1,
                section_title=_truncate_varchar(title, 255) or None,
                metadata_json=json.dumps(
                    {
                        "dataset": self.config.dataset,
                        "split": self.config.split,
                        "beir_doc_id": beir_doc_id,
                        "text_hash": compute_text_hash(title, text),
                    },
                    ensure_ascii=False,
                ),
            )
            repository.replace_chunks(document.id, [chunk], version_no=1)
            document.build_finished_at = now

            if {"ripgrep", "pageindex"} & set(self.targets):
                page_index_service.replace_pages_from_parse(
                    document,
                    [
                        {
                            "page_number": 1,
                            "title": _truncate_varchar(title, 255),
                            "content": content,
                            "blocks": [{"type": "text", "text": content, "metadata": {"beir_doc_id": beir_doc_id}}],
                        }
                    ],
                )
                page_index_service.build_page_indexes(document)
                page_index_service.publish_page_indexes(document)

            rows.append(
                BusinessDocMapping(
                    dataset=self.config.dataset,
                    split=self.config.split,
                    beir_doc_id=str(beir_doc_id),
                    business_document_id=int(document.id),
                    business_chunk_id=int(chunk.id),
                    project_id=int(project_id),
                    title=title,
                    text_hash=compute_text_hash(title, text),
                )
            )
            chunks.append(chunk)
            if index % 200 == 0 or index == total:
                self.db.flush()
                logger.info("stage=corpus_indexing action=business_document_import_progress imported=%s total=%s", index, total)

        logger.info("stage=corpus_indexing status=completed action=business_document_import imported=%s", len(rows))
        return rows, chunks

    def _index_milvus(self, chunks: list[Any]) -> None:
        from app.knowledge.indexing.milvus_indexer import MilvusIndexer
        from app.models.document import Document
        from app.services.embedding_service import EmbeddingService

        if not chunks:
            return
        embedding_service = EmbeddingService(self.db)
        milvus_indexer = MilvusIndexer()
        total = len(chunks)
        batch_size = max(1, int(self.config.embedding_batch_size or 32))
        indexed = 0
        started_at = time.perf_counter()
        logger.info("stage=corpus_indexing status=started action=business_milvus_index total=%s batch_size=%s", total, batch_size)
        for start in range(0, total, batch_size):
            batch = chunks[start : start + batch_size]
            vectors = embedding_service.embed_texts([chunk.content for chunk in batch])
            records: list[dict[str, Any]] = []
            for chunk, vector in zip(batch, vectors, strict=True):
                document = self.db.get(Document, chunk.document_id)
                vector_id = f"doc_{chunk.document_id}_chunk_{chunk.id}_v{chunk.version_no}"
                chunk.vector_id = vector_id
                if document is not None:
                    document.index_status = "indexed"
                    document.build_finished_at = datetime.utcnow()
                records.append(
                    {
                        "id": vector_id,
                        "knowledge_base_id": int(chunk.knowledge_base_id),
                        "project_id": int(chunk.project_id or 0),
                        "document_id": int(chunk.document_id),
                        "chunk_id": int(chunk.id),
                        "page_no": int(chunk.page_number or 0),
                        "version_no": int(chunk.version_no),
                        "drawing_no": str(getattr(document, "drawing_no", "") or ""),
                        "embedding": vector,
                    }
                )
            milvus_indexer.upsert_chunks(records)
            indexed += len(records)
            self.db.flush()
            logger.info(
                "stage=corpus_indexing action=business_milvus_batch_completed indexed=%s total=%s elapsed_ms=%s",
                indexed,
                total,
                int((time.perf_counter() - started_at) * 1000),
            )
        logger.info(
            "stage=corpus_indexing status=completed action=business_milvus_index indexed=%s elapsed_ms=%s",
            indexed,
            int((time.perf_counter() - started_at) * 1000),
        )

    def _clear_eval_documents(self, project_id: int) -> None:
        from app.knowledge.indexing.milvus_indexer import MilvusIndexer
        from app.repositories.document_repository import DocumentRepository
        from app.repositories.graph_repository import GraphRepository
        from app.repositories.page_index_repository import PageIndexRepository

        if not self.config.business_project_code.startswith(SAFE_PROJECT_PREFIX):
            raise RuntimeError(
                f"Refuse to clear business data for non-eval project_code={self.config.business_project_code}; "
                f"expected prefix {SAFE_PROJECT_PREFIX}"
            )
        document_repository = DocumentRepository(self.db)
        page_repository = PageIndexRepository(self.db)
        graph_repository = GraphRepository(self.db)
        milvus_indexer = MilvusIndexer() if "milvus" in self.targets else None
        documents = document_repository.list(project_id=project_id)
        logger.info("stage=corpus_indexing action=clear_eval_project_documents status=started project_id=%s count=%s", project_id, len(documents))
        for document in documents:
            chunks = document_repository.list_chunks(document.id, include_obsolete=True)
            if milvus_indexer is not None:
                vector_ids = [chunk.vector_id for chunk in chunks if chunk.vector_id]
                if vector_ids:
                    milvus_indexer.delete_vectors(document.id, vector_ids)
                else:
                    milvus_indexer.delete_vectors(document.id, None)
            graph_repository.clear_all_document_graph(document.id)
            page_repository.clear_all_document_pages(document.id)
            document_repository.clear_chunks(document.id)
            document_repository.clear_versions(document.id)
            document_repository.delete(document)
        self.db.flush()
        logger.info("stage=corpus_indexing action=clear_eval_project_documents status=completed project_id=%s count=%s", project_id, len(documents))

    def _write_document_file(self, beir_doc_id: str, content: str) -> Path:
        base_dir = self.settings.upload_path / "eval" / "beir" / self.config.dataset / self.config.split
        base_dir.mkdir(parents=True, exist_ok=True)
        path = base_dir / f"{_safe_filename(beir_doc_id)}.txt"
        path.write_text(content, encoding="utf-8")
        return path

    def _target_warnings(self) -> list[str]:
        warnings: list[str] = []
        if "graphrag" in self.targets:
            warnings.append("GRAPHRAG_INDEX_UNSUPPORTED_FOR_BEIR_BUSINESS_IMPORT: skipped graph construction for BEIR one-doc-one-chunk import.")
        if "pageindex" not in self.targets and "ripgrep" not in self.targets:
            warnings.append("PAGEINDEX_NOT_REQUESTED: ripgrep/page_index retrievers may not have BEIR mirror files.")
        return warnings


def _document_content(title: str, text: str) -> str:
    if title and text:
        return f"{title}\n\n{text}"
    return title or text


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value)).strip("._")
    return (cleaned or "doc")[:120]


def _truncate_varchar(value: str, max_length: int) -> str:
    text = str(value or "")
    return text if len(text) <= max_length else text[:max_length]


def _normalize_targets(targets: tuple[str, ...]) -> tuple[str, ...]:
    normalized: list[str] = []
    for target in targets:
        value = str(target or "").strip().lower().replace("-", "_")
        if value == "bm25":
            value = "keyword"
        if value and value not in normalized:
            normalized.append(value)
    if not normalized:
        normalized = ["milvus", "keyword", "ripgrep"]
    return tuple(normalized)
