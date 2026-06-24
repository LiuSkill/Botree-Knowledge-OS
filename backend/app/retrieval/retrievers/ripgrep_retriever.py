"""
ripgrep Retriever

负责：
1. 使用 ripgrep 对 PageIndex 文本镜像执行精确检索
2. 避免 shell 拼接，防止用户输入造成命令注入
3. 将命中文本文件映射回 PageIndex、Document 和 Chunk
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.document import Document
from app.models.page_index import PageIndex
from app.models.user import User
from app.repositories.document_repository import DocumentRepository
from app.repositories.page_index_repository import PageIndexRepository
from app.retrieval.base import BaseRetriever
from app.retrieval.query_utils import expand_search_phrases, score_text_relevance
from app.retrieval.retrievers.keyword_retriever import KeywordRetriever
from app.retrieval.schemas import Evidence
from app.services.project_service import ProjectService

logger = logging.getLogger(__name__)


class RipgrepRetriever(BaseRetriever):
    """
    ripgrep 精确检索器

    职责：
    - 对已授权的 PageIndex 文本镜像执行精确匹配
    - 将命中行回溯为统一 Evidence
    - 为设备位号、图纸号、标准号等精确问题提供高置信召回
    """

    name = "ripgrep"

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.page_repository = PageIndexRepository(db)
        self.document_repository = DocumentRepository(db)
        self.keyword_policy = KeywordRetriever(db)

    def search(self, query: str, mode: str, project_id: int | None, user: User, limit: int = 5) -> list[Evidence]:
        """执行 ripgrep 精确检索。"""

        allowed_indexes = self._allowed_page_indexes(mode, project_id, user)
        path_map = {str(Path(item.text_mirror_path).resolve()): item for item in allowed_indexes if item.text_mirror_path and item.chunk_id}
        patterns = expand_search_phrases(query)
        if not query.strip() or not path_map or not patterns:
            return []

        pattern_args = [value for pattern in patterns for value in ("-e", pattern)]
        try:
            completed = subprocess.run(
                [self.settings.ripgrep_binary, "--json", "--fixed-strings", "--ignore-case", *pattern_args, *path_map.keys()],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(int(self.settings.ripgrep_timeout_ms), 1) / 1000,
            )
        except FileNotFoundError:
            logger.warning("ripgrep未安装或不可执行: binary=%s", self.settings.ripgrep_binary)
            return []
        except subprocess.TimeoutExpired:
            logger.warning(
                "ripgrep timed out: timeout_ms=%s file_count=%s query_preview=%s",
                self.settings.ripgrep_timeout_ms,
                len(path_map),
                query[:120],
            )
            return []
        except subprocess.SubprocessError as exc:
            logger.warning("ripgrep检索失败: %s", exc)
            return []

        evidences: list[Evidence] = []
        seen_chunks: set[int] = set()
        max_candidates = max(limit * 5, limit)
        for line in completed.stdout.splitlines():
            hit = self._parse_rg_match(line)
            if not hit:
                continue
            page_index = path_map.get(hit["path"])
            if not page_index or page_index.chunk_id in seen_chunks:
                continue
            evidence = self._to_evidence(page_index, hit["line"], query, mode)
            if evidence:
                evidences.append(evidence)
                seen_chunks.add(page_index.chunk_id)
            if len(evidences) >= max_candidates:
                break
        return sorted(evidences, key=lambda item: item.score, reverse=True)[:limit]

    def _allowed_page_indexes(self, mode: str, project_id: int | None, user: User) -> list[PageIndex]:
        """按权限过滤可传给 rg 的文本镜像。"""

        result: list[PageIndex] = []
        project_service = ProjectService(self.db)
        for page_index in self.page_repository.list_published_indexes():
            document = self.db.get(Document, page_index.document_id)
            if not document or document.review_status != "approved" or document.index_status != "indexed":
                continue
            if document.version_no != page_index.version_no:
                continue
            if not self.keyword_policy._scope_allowed(document.knowledge_type, document.project_id, document.knowledge_base_id, mode, project_id, user):
                continue
            if document.project_id is not None:
                project_service.ensure_project_access(document.project_id, user)
            result.append(page_index)
        return result

    def _parse_rg_match(self, line: str) -> dict | None:
        """解析 ripgrep JSON match 行。"""

        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            return None
        if payload.get("type") != "match":
            return None
        data = payload.get("data") or {}
        path = str(Path(data.get("path", {}).get("text", "")).resolve())
        text = data.get("lines", {}).get("text", "").strip()
        if not path or not text:
            return None
        return {"path": path, "line": text}

    def _to_evidence(self, page_index: PageIndex, hit_line: str, query: str, mode: str) -> Evidence | None:
        """将 rg 命中转换为 Evidence。"""

        document = self.db.get(Document, page_index.document_id)
        chunk = self.document_repository.get_chunk(page_index.chunk_id) if page_index.chunk_id else None
        if not document or not chunk or chunk.chunk_status != "active":
            return None
        score = 10.0 + score_text_relevance(chunk.content, query)
        return Evidence(
            score=score,
            source_type=self.keyword_policy._source_type(document.knowledge_type, mode),
            knowledge_base_id=document.knowledge_base_id,
            project_id=document.project_id,
            document_id=document.id,
            chunk_id=chunk.id,
            drawing_no=page_index.drawing_no or document.drawing_no,
            file_name=document.file_name,
            page_number=page_index.page_no,
            content=chunk.content,
            retriever=self.name,
            metadata={"hit_line": hit_line, "page_index_id": page_index.id},
        )
