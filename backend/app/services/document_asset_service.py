"""
Document Asset Service

负责：
1. 保存 LibreOffice 转换 PDF、MinerU 原始结果和解析图片资产
2. 统一管理文档版本级派生资产状态
3. 为原始内容预览接口提供可查询的资产信息
"""

from __future__ import annotations

import base64
import json
import logging
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.minio import get_minio_client
from app.knowledge.parsing.parsed_document import ParsedDocumentResult
from app.models.document import Document
from app.models.document_asset import DocumentAsset
from app.models.page_index import DocumentPage, DocumentPageBlock
from app.repositories.document_asset_repository import DocumentAssetRepository

logger = logging.getLogger(__name__)

ASSET_TYPE_CONVERTED_PDF = "converted_pdf"
ASSET_TYPE_MINERU_RESULT = "mineru_result"
ASSET_TYPE_PAGE_PREVIEW = "page_preview"
ASSET_TYPE_BLOCK_IMAGE = "block_image"
MINERU_IMAGES_DIR_NAME = "images"
MINERU_COPY_DIR_NAMES = {"images", "markdown"}
MINERU_COPY_FILE_NAMES = {"content_list.json", "middle.json", "model.json"}


class DocumentAssetService:
    """
    文档派生资产服务

    职责：
    - 管理版本级派生资产文件
    - 在解析重试前失效旧资产
    - 把页图和块图与页表、块表关联起来
    """

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.repository = DocumentAssetRepository(db)

    def prepare_version_parse_refresh(self, document_id: int, version_no: int) -> int:
        """
        解析重试前失效旧的解析资产。

        说明：
            converted_pdf 会被保留，以支持同版本重复解析时复用转换结果。
        """

        obsolete_count = self.repository.obsolete_version_assets(
            document_id,
            version_no,
            keep_asset_types={ASSET_TYPE_CONVERTED_PDF},
        )
        if obsolete_count:
            logger.info(
                "同版本旧解析资产已失效: document_id=%s version_no=%s asset_count=%s",
                document_id,
                version_no,
                obsolete_count,
            )
        return obsolete_count

    def get_or_create_converted_pdf(
        self,
        document: Document,
        pdf_path: str,
        created_by: int | None,
    ) -> DocumentAsset:
        """登记并复用同版本转换后的 PDF 资产。"""

        existing = self.repository.get_latest_ready_asset(document.id, document.version_no, ASSET_TYPE_CONVERTED_PDF)
        if existing and existing.storage_path:
            if self.settings.resolve_local_path(existing.storage_path) == self.settings.resolve_local_path(pdf_path):
                return existing
        return self._create_file_asset(
            document=document,
            asset_type=ASSET_TYPE_CONVERTED_PDF,
            local_path=Path(pdf_path),
            mime_type="application/pdf",
            created_by=created_by,
            metadata={"source_file_name": document.file_name},
        )

    def save_mineru_result(
        self,
        document: Document,
        payload: dict[str, Any],
        task_id: str | None,
        created_by: int | None,
    ) -> DocumentAsset:
        """保存 MinerU 原始响应 JSON。"""

        file_name = f"mineru_result_{task_id or 'latest'}.json"
        target_path = self._build_asset_path(document, "mineru", file_name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return self._create_file_asset(
            document=document,
            asset_type=ASSET_TYPE_MINERU_RESULT,
            local_path=target_path,
            mime_type="application/json",
            created_by=created_by,
            metadata={"task_id": task_id},
        )

    def materialize_mineru_output(
        self,
        document: Document,
        parsed_result: ParsedDocumentResult,
    ) -> dict[str, int]:
        """
        复制 MinerU 任务输出目录中的关键产物到当前文档版本派生目录。
        参数:
            document: 当前文档对象。
            parsed_result: MinerU 解析结果对象。
        返回:
            复制成功数量和图片解析失败数量摘要。
        """

        parse_source = parsed_result.parse_source
        if parsed_result.parser_name != "mineru" or not parse_source.mineru_output_host_dir:
            return {"copied_artifact_count": 0, "image_resolution_failures": 0}

        source_dir = Path(parse_source.mineru_output_host_dir)
        if not source_dir.exists():
            logger.warning(
                "MinerU任务输出目录不存在，跳过产物复制: document_id=%s task_id=%s output_dir_host=%s",
                document.id,
                parsed_result.task_id,
                source_dir,
            )
            return {"copied_artifact_count": 0, "image_resolution_failures": self._count_missing_image_candidates(parsed_result.pages)}

        target_dir = self.settings.libreoffice_work_path / str(document.id) / f"v{document.version_no}" / "mineru" / (
            f"task_{parsed_result.task_id or 'latest'}"
        )
        target_dir.mkdir(parents=True, exist_ok=True)

        copied_artifact_count = 0
        for source_path in self._iter_mineru_artifacts(source_dir):
            target_path = target_dir / source_path.relative_to(source_dir)
            if source_path.is_dir():
                shutil.copytree(source_path, target_path, dirs_exist_ok=True)
            else:
                target_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_path, target_path)
            copied_artifact_count += 1

        self._rebind_candidate_resolution_base(parsed_result.pages, source_dir, target_dir)
        parse_source.mineru_output_host_dir = str(target_dir)
        parse_source.mineru_content_list_path = self._prefer_copied_artifact_path(
            target_dir,
            parse_source.mineru_content_list_path,
        )
        parse_source.mineru_middle_json_path = self._prefer_copied_artifact_path(
            target_dir,
            parse_source.mineru_middle_json_path,
        )
        parse_source.mineru_images_dir = self._prefer_copied_artifact_directory(
            target_dir,
            parse_source.mineru_images_dir,
        )
        parse_source.mineru_markdown_dir = self._prefer_copied_markdown_artifact(
            target_dir,
            parse_source.mineru_markdown_dir,
        )

        image_resolution_failures = self._count_missing_image_candidates(parsed_result.pages)
        logger.info(
            "MinerU任务产物复制完成: document_id=%s task_id=%s output_dir_container=%s output_dir_host=%s copied_artifact_count=%s image_resolution_failures=%s content_list_path=%s middle_json_path=%s images_dir=%s",
            document.id,
            parsed_result.task_id,
            parse_source.mineru_output_container_dir,
            parse_source.mineru_output_host_dir,
            copied_artifact_count,
            image_resolution_failures,
            parse_source.mineru_content_list_path,
            parse_source.mineru_middle_json_path,
            parse_source.mineru_images_dir,
        )
        return {
            "copied_artifact_count": copied_artifact_count,
            "image_resolution_failures": image_resolution_failures,
        }

    def persist_page_and_block_images(
        self,
        document: Document,
        parsed_pages: list[dict[str, Any]],
        saved_pages: list[DocumentPage],
        saved_blocks: list[DocumentPageBlock],
        mineru_result_asset: DocumentAsset | None,
        created_by: int | None,
    ) -> dict[str, int]:
        """把页图和块图从解析结果写入资产表。"""

        page_lookup = {page.page_no: page for page in saved_pages}
        block_lookup = {(block.page_id, block.block_index): block for block in saved_blocks}
        ready_count = 0
        failed_count = 0

        for page_payload in parsed_pages:
            page_no = int(page_payload.get("page_number") or page_payload.get("page_no") or 0)
            saved_page = page_lookup.get(page_no)
            if saved_page is None:
                continue

            if mineru_result_asset is not None:
                saved_page.mineru_json_object_key = mineru_result_asset.object_key or mineru_result_asset.storage_path

            page_asset = self._persist_optional_image_asset(
                document=document,
                asset_type=ASSET_TYPE_PAGE_PREVIEW,
                page=saved_page,
                block=None,
                candidate_list=page_payload.get("page_image_candidates") or [],
                default_name=f"page_{saved_page.page_no:04d}_preview",
                created_by=created_by,
            )
            if page_asset is not None:
                if page_asset.status == "ready":
                    ready_count += 1
                    saved_page.page_image_object_key = page_asset.object_key or page_asset.storage_path
                else:
                    failed_count += 1

            for block_index, block_payload in enumerate(page_payload.get("blocks") or [], start=1):
                if not self._block_requires_image_asset(block_payload):
                    continue
                saved_block = block_lookup.get((saved_page.id, block_index))
                if saved_block is None:
                    continue
                block_asset = self._persist_optional_image_asset(
                    document=document,
                    asset_type=ASSET_TYPE_BLOCK_IMAGE,
                    page=saved_page,
                    block=saved_block,
                    candidate_list=block_payload.get("image_candidates") or [],
                    default_name=f"page_{saved_page.page_no:04d}_block_{block_index:04d}",
                    created_by=created_by,
                    extra_metadata={"block_type": saved_block.block_type},
                )
                if block_asset is None:
                    continue
                if block_asset.status == "ready":
                    ready_count += 1
                else:
                    failed_count += 1

        self.db.flush()
        return {"ready": ready_count, "failed": failed_count}

    def list_version_assets(self, document_id: int, version_no: int) -> list[DocumentAsset]:
        """查询当前版本全部资产。"""

        return self.repository.list_by_document_version(document_id, version_no)

    def get_asset(self, asset_id: int) -> DocumentAsset | None:
        """按主键查询资产。"""

        return self.repository.get(asset_id)

    def list_document_assets(self, document_id: int) -> list[DocumentAsset]:
        """查询文档全部派生资产，用于删除前收集后台清理目标。"""

        return self.repository.list_by_document(document_id)

    def delete_document_asset_records(self, document_id: int) -> int:
        """仅删除派生资产数据库记录，不等待本地文件或对象存储清理。"""

        return self.repository.delete_by_document(document_id)

    def cleanup_document_assets(self, document_id: int) -> dict[str, int]:
        """
        删除文档派生资产记录，并尽力清理本地与 MinIO 文件。

        参数:
            document_id: 文档ID。

        返回:
            清理结果摘要。
        """

        assets = self.repository.list_by_document(document_id)
        deleted_local_files = 0
        deleted_minio_objects = 0
        failed_local_files = 0
        failed_minio_objects = 0

        for asset in assets:
            if asset.storage_path:
                try:
                    path = self.settings.resolve_local_path(asset.storage_path)
                    if path.is_file():
                        path.unlink()
                        deleted_local_files += 1
                except Exception:  # noqa: BLE001
                    failed_local_files += 1
                    logger.warning("派生资产本地文件删除失败: asset_id=%s path=%s", asset.id, asset.storage_path, exc_info=True)

            if asset.object_key:
                try:
                    if self._remove_minio_object(asset.object_key):
                        deleted_minio_objects += 1
                except Exception:  # noqa: BLE001
                    failed_minio_objects += 1
                    logger.warning("派生资产MinIO对象删除失败: asset_id=%s object_key=%s", asset.id, asset.object_key, exc_info=True)

        deleted_assets = self.repository.delete_by_document(document_id)
        self._cleanup_document_asset_directory(document_id)
        return {
            "deleted_assets": deleted_assets,
            "deleted_local_files": deleted_local_files,
            "deleted_minio_objects": deleted_minio_objects,
            "failed_local_files": failed_local_files,
            "failed_minio_objects": failed_minio_objects,
        }

    def _persist_optional_image_asset(
        self,
        document: Document,
        asset_type: str,
        page: DocumentPage,
        block: DocumentPageBlock | None,
        candidate_list: list[dict[str, Any]],
        default_name: str,
        created_by: int | None,
        extra_metadata: dict[str, Any] | None = None,
    ) -> DocumentAsset | None:
        """尽力保存单个页图或块图；失败只记录 failed 资产，不中断整份解析。"""

        metadata = {
            "page_no": page.page_no,
            "document_id": document.id,
            "version_no": document.version_no,
        }
        if block is not None:
            metadata["block_id"] = block.id
            metadata["block_index"] = block.block_index
        if extra_metadata:
            metadata.update(extra_metadata)

        if not candidate_list:
            if block is not None:
                logger.warning(
                    "图片块缺少可提取图片候选: document_id=%s page_no=%s block_id=%s",
                    document.id,
                    page.page_no,
                    block.id,
                )
                return self._create_failed_asset(
                    document=document,
                    asset_type=asset_type,
                    file_name=f"{default_name}.bin",
                    page_id=page.id,
                    block_id=block.id,
                    created_by=created_by,
                    metadata={**metadata, "reason": "missing_image_candidate"},
                )
            return None

        candidate_errors: list[dict[str, Any]] = []
        for candidate in candidate_list:
            try:
                asset = self._create_image_asset_from_candidate(
                    document=document,
                    asset_type=asset_type,
                    page_id=page.id,
                    block_id=block.id if block is not None else None,
                    candidate=candidate,
                    default_name=default_name,
                    created_by=created_by,
                    metadata=metadata,
                )
                logger.info(
                    "解析图片资产保存成功: document_id=%s asset_type=%s page_no=%s block_id=%s asset_id=%s",
                    document.id,
                    asset_type,
                    page.page_no,
                    block.id if block is not None else None,
                    asset.id,
                )
                return asset
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "解析图片资产保存失败，继续尝试其他候选: document_id=%s asset_type=%s page_no=%s block_id=%s error=%s",
                    document.id,
                    asset_type,
                    page.page_no,
                    block.id if block is not None else None,
                    exc,
                )
                candidate_errors.append(
                    {
                        "error": str(exc),
                        "candidate": self._safe_candidate_metadata(candidate),
                    }
                )

        logger.warning(
            "解析图片资产全部候选均失败: document_id=%s asset_type=%s page_no=%s block_id=%s",
            document.id,
            asset_type,
            page.page_no,
            block.id if block is not None else None,
        )
        return self._create_failed_asset(
            document=document,
            asset_type=asset_type,
            file_name=f"{default_name}.bin",
            page_id=page.id,
            block_id=block.id if block is not None else None,
            created_by=created_by,
            metadata={**metadata, "reason": "all_candidates_failed", "candidate_errors": candidate_errors},
        )

    def _create_image_asset_from_candidate(
        self,
        document: Document,
        asset_type: str,
        page_id: int | None,
        block_id: int | None,
        candidate: dict[str, Any],
        default_name: str,
        created_by: int | None,
        metadata: dict[str, Any],
    ) -> DocumentAsset:
        """从单个候选中创建图片资产。"""

        file_name = self._resolve_candidate_file_name(candidate, default_name)
        mime_type = str(candidate.get("mime_type") or self._guess_mime_type(file_name))
        suffix = Path(file_name).suffix or self._suffix_from_mime_type(mime_type)
        bytes_payload = self._resolve_candidate_bytes(candidate)
        local_path = self._build_asset_path(document, asset_type, f"{default_name}{suffix}")
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(bytes_payload)
        return self._create_file_asset(
            document=document,
            asset_type=asset_type,
            local_path=local_path,
            mime_type=mime_type,
            created_by=created_by,
            metadata={**metadata, **self._safe_candidate_metadata(candidate)},
            page_id=page_id,
            block_id=block_id,
        )

    def _create_file_asset(
        self,
        document: Document,
        asset_type: str,
        local_path: Path,
        mime_type: str,
        created_by: int | None,
        metadata: dict[str, Any] | None = None,
        page_id: int | None = None,
        block_id: int | None = None,
    ) -> DocumentAsset:
        """按本地文件创建资产记录，并在可用时同步对象存储。"""

        object_key = self._upload_to_minio(local_path, document)
        asset = self.repository.add(
            DocumentAsset(
                document_id=document.id,
                version_no=document.version_no,
                page_id=page_id,
                block_id=block_id,
                asset_type=asset_type,
                file_name=local_path.name,
                mime_type=mime_type,
                storage_backend="local",
                storage_path=self.settings.to_relative_local_path(local_path),
                object_key=object_key,
                file_size=int(local_path.stat().st_size) if local_path.exists() else 0,
                status="ready",
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
                created_by=created_by,
            )
        )
        return asset

    def _create_failed_asset(
        self,
        document: Document,
        asset_type: str,
        file_name: str,
        page_id: int | None,
        block_id: int | None,
        created_by: int | None,
        metadata: dict[str, Any] | None = None,
    ) -> DocumentAsset:
        """创建失败状态的资产记录。"""

        return self.repository.add(
            DocumentAsset(
                document_id=document.id,
                version_no=document.version_no,
                page_id=page_id,
                block_id=block_id,
                asset_type=asset_type,
                file_name=file_name,
                mime_type=self._guess_mime_type(file_name),
                storage_backend="local",
                storage_path=None,
                object_key=None,
                file_size=0,
                status="failed",
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
                created_by=created_by,
            )
        )

    def _build_asset_path(self, document: Document, group: str, file_name: str) -> Path:
        """构建派生资产的本地路径。"""

        return self.settings.libreoffice_work_path / str(document.id) / f"v{document.version_no}" / group / file_name

    def _upload_to_minio(self, local_path: Path, document: Document) -> str | None:
        """在 MinIO 可用时同步派生资产副本。"""

        client = get_minio_client()
        if client is None:
            return None
        relative_path = local_path.relative_to(self.settings.libreoffice_work_path)
        object_key = "/".join(("document-assets", *relative_path.parts))
        client.fput_object(self.settings.minio_bucket, object_key, str(local_path))
        logger.info("派生资产已同步到 MinIO: document_id=%s object_key=%s", document.id, object_key)
        return object_key

    def _remove_minio_object(self, object_key: str) -> bool:
        """删除派生资产在 MinIO 中的对象副本。"""

        client = get_minio_client()
        if client is None:
            return False
        client.remove_object(self.settings.minio_bucket, object_key)
        logger.info("派生资产 MinIO 对象已删除: object_key=%s", object_key)
        return True

    def _cleanup_document_asset_directory(self, document_id: int) -> None:
        """尽力删除文档派生资产根目录，避免遗留空目录。"""

        document_dir = self.settings.libreoffice_work_path / str(document_id)
        if not document_dir.exists():
            return
        try:
            shutil.rmtree(document_dir)
            logger.info("文档派生资产目录已清理: document_id=%s path=%s", document_id, document_dir)
        except Exception:  # noqa: BLE001
            logger.warning("文档派生资产目录清理失败: document_id=%s path=%s", document_id, document_dir, exc_info=True)

    def _resolve_candidate_bytes(self, candidate: dict[str, Any]) -> bytes:
        """从 base64、本地路径或远程 URL ��提取图片字节。"""

        if candidate.get("payload_base64"):
            return self._decode_base64_payload(str(candidate["payload_base64"]))

        resolved_local_path = str(candidate.get("resolved_local_path") or "").strip()
        if resolved_local_path:
            local_path = Path(resolved_local_path)
            if not local_path.is_file():
                raise FileNotFoundError(f"image candidate local path not found: {local_path}")
            return local_path.read_bytes()

        if candidate.get("local_path"):
            local_path = Path(str(candidate["local_path"]))
            if not local_path.is_absolute():
                resolution_base_dir = str(candidate.get("resolution_base_dir") or "").strip()
                if resolution_base_dir:
                    local_path = Path(resolution_base_dir) / local_path
            if not local_path.is_file():
                raise FileNotFoundError(f"image candidate local path not found: {local_path}")
            return local_path.read_bytes()

        if candidate.get("remote_url"):
            response = requests.get(str(candidate["remote_url"]), timeout=30)
            response.raise_for_status()
            return response.content

        raise ValueError("unsupported image candidate payload")

    def _decode_base64_payload(self, raw_value: str) -> bytes:
        """解码图片 base64 内容，兼容 data URL。"""

        payload = raw_value.strip()
        if payload.startswith("data:") and "," in payload:
            payload = payload.split(",", 1)[1]
        return base64.b64decode(payload)

    def _resolve_candidate_file_name(self, candidate: dict[str, Any], default_name: str) -> str:
        """为图片候选生成稳定文件名。"""

        raw_name = str(candidate.get("file_name") or "").strip()
        if raw_name:
            return Path(raw_name).name

        remote_url = str(candidate.get("remote_url") or "").strip()
        if remote_url:
            parsed = urlparse(remote_url)
            url_name = Path(parsed.path).name
            if url_name:
                return url_name

        local_path = str(candidate.get("local_path") or "").strip()
        if local_path:
            local_name = Path(local_path).name
            if local_name:
                return local_name

        suffix = self._suffix_from_mime_type(str(candidate.get("mime_type") or ""))
        return f"{default_name}{suffix}"

    def _guess_mime_type(self, file_name: str) -> str:
        """根据文件后缀猜测 MIME 类型。"""

        suffix = Path(file_name).suffix.lower()
        return {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".svg": "image/svg+xml",
            ".json": "application/json",
            ".pdf": "application/pdf",
        }.get(suffix, "application/octet-stream")

    def _suffix_from_mime_type(self, mime_type: str) -> str:
        """根据 MIME 类型补充文件后缀。"""

        return {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/bmp": ".bmp",
            "image/svg+xml": ".svg",
            "application/json": ".json",
            "application/pdf": ".pdf",
        }.get(mime_type, ".bin")

    def _safe_candidate_metadata(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """过滤图片候选中的大体积或二进制字段。"""

        excluded_keys = {"payload_base64", "binary", "bytes"}
        result: dict[str, Any] = {}
        for key, value in candidate.items():
            if key in excluded_keys:
                continue
            result[key] = value
        return result

    def _iter_mineru_artifacts(self, source_dir: Path) -> list[Path]:
        """
        枚举需要从 MinerU 任务目录复制的关键产物。
        参数:
            source_dir: MinerU 宿主机任务输出目录。
        返回:
            需要复制的文件和目录列表。
        """

        artifacts: list[Path] = []
        for child in source_dir.iterdir():
            if child.name in MINERU_COPY_DIR_NAMES and child.exists():
                artifacts.append(child)
                continue
            if child.name in MINERU_COPY_FILE_NAMES and child.is_file():
                artifacts.append(child)
                continue
            if child.is_file() and child.suffix.lower() in {".md", ".markdown"}:
                artifacts.append(child)
        return artifacts

    def _rebind_candidate_resolution_base(
        self,
        parsed_pages: list[dict[str, Any]],
        old_base_dir: Path,
        new_base_dir: Path,
    ) -> None:
        """
        在产物复制完成后，将图片候选的解析基准目录切换到文档派生目录。
        参数:
            parsed_pages: 页级解析结果。
            old_base_dir: 原始 MinerU 宿主机输出目录。
            new_base_dir: 当前文档版本派生目录中的复制目标目录。
        """

        for page_payload in parsed_pages:
            for candidate in page_payload.get("page_image_candidates") or []:
                self._rebind_single_candidate(candidate, old_base_dir, new_base_dir)
            for block_payload in page_payload.get("blocks") or []:
                for candidate in block_payload.get("image_candidates") or []:
                    self._rebind_single_candidate(candidate, old_base_dir, new_base_dir)

    def _rebind_single_candidate(
        self,
        candidate: dict[str, Any],
        old_base_dir: Path,
        new_base_dir: Path,
    ) -> None:
        """
        更新单个图片候选的解析基准目录与已解析本地路径。
        参数:
            candidate: 图片候选对象。
            old_base_dir: 复制前基准目录。
            new_base_dir: 复制后基准目录。
        """

        candidate["resolution_base_dir"] = str(new_base_dir)
        resolved_local_path = str(candidate.get("resolved_local_path") or "").strip()
        if resolved_local_path:
            resolved_path = Path(resolved_local_path)
            try:
                relative_path = resolved_path.relative_to(old_base_dir)
            except ValueError:
                relative_path = None
            if relative_path is not None:
                candidate["resolved_local_path"] = str((new_base_dir / relative_path).resolve(strict=False))
                return

        local_path = str(candidate.get("local_path") or "").strip()
        if local_path and not Path(local_path).is_absolute():
            candidate["resolved_local_path"] = str((new_base_dir / local_path).resolve(strict=False))

    def _prefer_copied_artifact_path(self, target_dir: Path, original_path: str | None) -> str | None:
        """
        优先返回复制后的关键产物文件路径。
        参数:
            target_dir: 文档派生目录中的 MinerU 目标目录。
            original_path: 原始任务输出中的文件路径。
        返回:
            复制后优先、原路径兜底的文件路径。
        """

        if original_path:
            candidate_name = Path(original_path).name
            copied_path = target_dir / candidate_name
            if copied_path.is_file():
                return str(copied_path)
        return original_path

    def _prefer_copied_artifact_directory(self, target_dir: Path, original_path: str | None) -> str | None:
        """
        优先返回复制后的目录路径。
        参数:
            target_dir: 文档派生目录中的 MinerU 目标目录。
            original_path: 原始目录路径。
        返回:
            复制后优先、原路径兜底的目录路径。
        """

        copied_images_dir = target_dir / MINERU_IMAGES_DIR_NAME
        if copied_images_dir.is_dir():
            return str(copied_images_dir)
        return original_path

    def _prefer_copied_markdown_artifact(self, target_dir: Path, original_path: str | None) -> str | None:
        """
        优先返回复制后的 markdown 文件或目录。
        参数:
            target_dir: 文档派生目录中的 MinerU 目标目录。
            original_path: 原始 markdown 产物路径。
        返回:
            复制后的 markdown 路径。
        """

        markdown_dir = target_dir / "markdown"
        if markdown_dir.is_dir():
            return str(markdown_dir)
        for candidate in target_dir.glob("*.md"):
            if candidate.is_file():
                return str(candidate)
        return original_path

    def _count_missing_image_candidates(self, parsed_pages: list[dict[str, Any]]) -> int:
        """
        统计当前解析结果中解析后仍不存在的图片候选数量。
        参数:
            parsed_pages: 页级解析结果。
        返回:
            无法解析到本地文件的图片候选数量。
        """

        failure_count = 0
        for page_payload in parsed_pages:
            for candidate in page_payload.get("page_image_candidates") or []:
                if self._candidate_path_missing(candidate):
                    failure_count += 1
            for block_payload in page_payload.get("blocks") or []:
                for candidate in block_payload.get("image_candidates") or []:
                    if self._candidate_path_missing(candidate):
                        failure_count += 1
        return failure_count

    def _candidate_path_missing(self, candidate: dict[str, Any]) -> bool:
        """
        判断图片候选在当前上下文中是否仍缺少可读文件路径。

        参数:
            candidate: 图片候选对象。

        返回:
            True 表示候选声明了本地路径但当前仍不可读。
        """

        # 内联 base64 图片已经足够完成资产落库，不应再被视为缺图。
        if str(candidate.get("payload_base64") or "").strip():
            return False

        resolved_local_path = str(candidate.get("resolved_local_path") or "").strip()
        if resolved_local_path:
            return not Path(resolved_local_path).is_file()

        local_path = str(candidate.get("local_path") or "").strip()
        if not local_path:
            return False

        local_path_obj = Path(local_path)
        if local_path_obj.is_absolute():
            return not local_path_obj.is_file()

        resolution_base_dir = str(candidate.get("resolution_base_dir") or "").strip()
        if not resolution_base_dir:
            return True
        return not (Path(resolution_base_dir) / local_path_obj).is_file()

    def _block_requires_image_asset(self, block_payload: dict[str, Any]) -> bool:
        """判断块是否需要尝试提取图片。"""

        block_type = str(block_payload.get("block_type") or block_payload.get("type") or "").lower()
        if block_type == "image":
            return True
        return bool(block_payload.get("image_candidates"))
