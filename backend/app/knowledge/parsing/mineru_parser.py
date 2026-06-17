"""
MinerU Parser

负责：
1. 调用 MinerU 异步任务接口提交解析任务
2. 轮询任务状态并在完成后拉取原始解析结果
3. 将 MinerU 响应归一化为页、块、图片候选的统一结构
4. 在超时、失败或响应异常时抛出标准业务异常
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path, PurePosixPath
from typing import Any

import requests

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.knowledge.parsing.parsed_document import ParseSource, ParsedDocumentResult

logger = logging.getLogger(__name__)

MINERU_SUCCESS_STATUS = "completed"
MINERU_FAILURE_STATUSES = {"failed", "canceled"}
MINERU_STATUS_UNKNOWN = "unknown"

IMAGE_BASE64_KEYS = ("image_base64", "img_base64", "base64", "image_data", "img_data")
IMAGE_PATH_KEYS = ("image_path", "img_path", "path", "local_path", "saved_path")
IMAGE_URL_KEYS = ("image_url", "img_url", "url", "download_url", "remote_url")
IMAGE_MIME_KEYS = ("mime_type", "content_type")
IMAGE_NAME_KEYS = ("file_name", "image_name", "img_name", "name")
PAGE_PREVIEW_HINT_KEYS = ("page_image", "page_preview", "render_image", "thumbnail")
IMAGE_BLOCK_HINTS = {"image", "img", "picture", "figure", "photo"}
BLOCK_TEXT_KEYS = ("text", "content", "markdown", "md", "caption")
BLOCK_BBOX_KEYS = ("bbox", "position", "box")
METADATA_EXCLUDED_KEYS = set(IMAGE_BASE64_KEYS + IMAGE_PATH_KEYS + IMAGE_URL_KEYS + IMAGE_MIME_KEYS + IMAGE_NAME_KEYS)
MINERU_CONTENT_LIST_FILE = "content_list.json"
MINERU_MIDDLE_JSON_FILE = "middle.json"
MINERU_IMAGES_DIR_NAME = "images"
MINERU_RESULT_IMAGE_KEYS = ("images",)


class MinerUParser:
    """
    MinerU 解析器

    职责：
    - 通过 `/tasks` 提交异步解析任务
    - 在固定总预算内轮询任务状态
    - 统一提取页级文本、块结构和图片候选
    """

    def __init__(self) -> None:
        self.settings = get_settings()

    def parse(self, storage_path: str) -> list[dict[str, Any]]:
        """
        兼容旧调用方式，只返回页级结构。

        参数:
            storage_path: 本地待解析文件路径

        返回:
            页级结构列表
        """

        return self.parse_document(storage_path).pages

    def parse_document(self, storage_path: str, parse_source: ParseSource | None = None) -> ParsedDocumentResult:
        """
        调用 MinerU 解析文档，并返回结构化结果。

        参数:
            storage_path: 实际提交给 MinerU 的本地文件路径
            parse_source: 解析来源信息；未提供时自动按原路径构建

        返回:
            结构化解析结果对象
        """

        submit_url = self.settings.mineru_task_submit_url
        if not submit_url:
            raise AppException("未配置 MINERU_BASE_URL，无法调用 MinerU 解析服务", status_code=500, code=500)

        path = Path(storage_path)
        if not path.is_file():
            raise AppException("源文件不存在，无法调用 MinerU 解析", status_code=400, code=400)
        output_root_host_dir = self._prepare_output_root()

        parse_source = parse_source or ParseSource(
            source_path=storage_path,
            source_kind="mineru",
            original_path=storage_path,
            converted_pdf_path=None,
        )
        start_monotonic = self._current_monotonic()
        submit_payload = self._submit_task(path, submit_url)
        task_id = self._extract_task_id(submit_payload)
        task_output_container_dir = self._task_output_container_dir(task_id)
        task_output_host_dir = self._task_output_host_dir(task_id)

        logger.info(
            "MinerU解析任务已提交: task_id=%s file=%s timeout_seconds=%s poll_interval_seconds=%s output_dir_container=%s output_root_host=%s",
            task_id,
            path.name,
            self.settings.mineru_task_timeout_seconds,
            self.settings.mineru_poll_interval_seconds,
            task_output_container_dir,
            output_root_host_dir,
        )

        final_status_payload = self._wait_for_completion(task_id, path.name, start_monotonic)
        result_payload = self._fetch_task_result(task_id, path.name)
        inline_image_payloads = self._extract_inline_image_payloads(result_payload)
        pages = self._extract_pages(result_payload)
        resolved_output_host_dir = self._resolve_output_host_dir(task_id, task_output_host_dir)
        self._apply_candidate_resolution_context(
            pages,
            output_host_dir=resolved_output_host_dir,
            output_container_dir=task_output_container_dir,
            inline_image_payloads=inline_image_payloads,
        )
        parse_source.mineru_output_host_dir = str(resolved_output_host_dir)
        parse_source.mineru_output_container_dir = task_output_container_dir
        parse_source.mineru_content_list_path = self._find_optional_artifact_path(
            resolved_output_host_dir,
            MINERU_CONTENT_LIST_FILE,
        )
        parse_source.mineru_middle_json_path = self._find_optional_artifact_path(
            resolved_output_host_dir,
            MINERU_MIDDLE_JSON_FILE,
        )
        parse_source.mineru_images_dir = self._find_optional_directory_path(
            resolved_output_host_dir,
            MINERU_IMAGES_DIR_NAME,
        )
        parse_source.mineru_markdown_dir = self._find_markdown_artifact_path(resolved_output_host_dir)
        elapsed_seconds = int(self._current_monotonic() - start_monotonic)

        logger.info(
            "MinerU解析完成: task_id=%s file=%s status=%s pages=%s elapsed_seconds=%s output_dir_host=%s content_list_path=%s middle_json_path=%s images_dir=%s",
            task_id,
            path.name,
            self._extract_task_status(final_status_payload),
            len(pages),
            elapsed_seconds,
            parse_source.mineru_output_host_dir,
            parse_source.mineru_content_list_path,
            parse_source.mineru_middle_json_path,
            parse_source.mineru_images_dir,
        )
        return ParsedDocumentResult(
            pages=pages,
            parser_name="mineru",
            parse_source=parse_source,
            raw_payload=result_payload,
            task_id=task_id,
            metadata={
                "elapsed_seconds": elapsed_seconds,
                "task_output_host_dir": parse_source.mineru_output_host_dir,
                "task_output_container_dir": parse_source.mineru_output_container_dir,
            },
        )

    def _submit_task(self, path: Path, submit_url: str) -> dict[str, Any]:
        """提交 MinerU 异步解析任务。"""

        try:
            with path.open("rb") as file_obj:
                response = requests.post(
                    submit_url,
                    files=[("files", (path.name, file_obj, self._content_type(path)))],
                    data={
                        "return_md": "true",
                        "return_content_list": "true",
                        "return_middle_json": "true",
                        "return_images": "true",
                        "output_dir": self._mineru_output_container_root(),
                    },
                    timeout=self.settings.mineru_http_timeout_seconds,
                )
            if response.status_code >= 400:
                self._log_http_warning("submit", path.name, response)
            response.raise_for_status()
            payload = response.json()
            self._extract_task_id(payload)
            return payload
        except requests.RequestException as exc:
            logger.exception("MinerU任务提交失败: file=%s", path)
            raise AppException(f"MinerU任务提交失败：file={path.name} error={exc}", status_code=502, code=502) from exc
        except ValueError as exc:
            logger.exception("MinerU任务提交响应不是合法JSON: file=%s", path)
            raise AppException(f"MinerU任务提交响应格式错误：file={path.name} error={exc}", status_code=502, code=502) from exc

    def _wait_for_completion(self, task_id: str, file_name: str, start_monotonic: float) -> dict[str, Any]:
        """在固定总预算内轮询 MinerU 任务状态。"""

        last_status = MINERU_STATUS_UNKNOWN
        timeout_seconds = self.settings.mineru_task_timeout_seconds
        poll_interval = max(1, self.settings.mineru_poll_interval_seconds)

        while True:
            elapsed_seconds = int(self._current_monotonic() - start_monotonic)
            if elapsed_seconds >= timeout_seconds:
                logger.error(
                    "MinerU解析任务超时: task_id=%s file=%s status=%s elapsed_seconds=%s",
                    task_id,
                    file_name,
                    last_status,
                    elapsed_seconds,
                )
                raise AppException(
                    f"MinerU解析任务超时：task_id={task_id} status={last_status} elapsed_seconds={elapsed_seconds}",
                    status_code=504,
                    code=504,
                )

            payload = self._get_task_status(task_id, file_name)
            if payload is None:
                remaining_seconds = max(1, timeout_seconds - elapsed_seconds)
                self._sleep_seconds(min(poll_interval, remaining_seconds))
                continue

            status = self._extract_task_status(payload)
            last_status = status
            logger.info(
                "MinerU任务轮询: task_id=%s file=%s status=%s elapsed_seconds=%s queued_ahead=%s",
                task_id,
                file_name,
                status,
                elapsed_seconds,
                payload.get("queued_ahead"),
            )

            if status == MINERU_SUCCESS_STATUS:
                return payload

            if status in MINERU_FAILURE_STATUSES:
                error_message = self._extract_task_error(payload)
                logger.error(
                    "MinerU解析任务失败: task_id=%s file=%s status=%s elapsed_seconds=%s error=%s",
                    task_id,
                    file_name,
                    status,
                    elapsed_seconds,
                    error_message,
                )
                raise AppException(
                    f"MinerU解析任务失败：task_id={task_id} status={status} elapsed_seconds={elapsed_seconds} error={error_message}",
                    status_code=502,
                    code=502,
                )

            remaining_seconds = max(1, timeout_seconds - elapsed_seconds)
            self._sleep_seconds(min(poll_interval, remaining_seconds))

    def _get_task_status(self, task_id: str, file_name: str) -> dict[str, Any] | None:
        """查询 MinerU 任务状态。"""

        status_url = self.settings.mineru_task_status_url(task_id)
        if not status_url:
            raise AppException("未配置 MINERU_BASE_URL，无法查询 MinerU 任务状态", status_code=500, code=500)

        try:
            response = requests.get(status_url, timeout=self.settings.mineru_http_timeout_seconds)
            if response.status_code >= 400:
                self._log_http_warning("status", task_id, response)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.warning("MinerU任务状态查询异常: task_id=%s file=%s error=%s", task_id, file_name, exc)
            return None
        except ValueError as exc:
            logger.warning("MinerU任务状态响应JSON无效: task_id=%s file=%s error=%s", task_id, file_name, exc)
            return None

    def _fetch_task_result(self, task_id: str, file_name: str) -> dict[str, Any]:
        """拉取 MinerU 已完成任务的解析结果。"""

        result_url = self.settings.mineru_task_result_url(task_id)
        if not result_url:
            raise AppException("未配置 MINERU_BASE_URL，无法获取 MinerU 任务结果", status_code=500, code=500)

        try:
            response = requests.get(result_url, timeout=self.settings.mineru_http_timeout_seconds)
            if response.status_code >= 400:
                self._log_http_warning("result", task_id, response)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as exc:
            logger.exception("MinerU任务结果获取失败: task_id=%s file=%s", task_id, file_name)
            raise AppException(
                f"MinerU任务结果获取失败：task_id={task_id} file={file_name} error={exc}",
                status_code=502,
                code=502,
            ) from exc
        except ValueError as exc:
            logger.exception("MinerU任务结果响应不是合法JSON: task_id=%s file=%s", task_id, file_name)
            raise AppException(
                f"MinerU任务结果响应格式错误：task_id={task_id} file={file_name} error={exc}",
                status_code=502,
                code=502,
            ) from exc

    def _extract_pages(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        """从 MinerU 响应中提取统一页级结构。"""

        if payload.get("code") not in (None, 0, "0", 200):
            raise AppException(
                f"MinerU解析失败：{payload.get('message') or payload.get('msg') or payload}",
                status_code=502,
                code=502,
            )

        data = payload.get("data", payload)
        if isinstance(payload.get("results"), dict):
            return self._extract_result_pages(payload["results"])
        if isinstance(data, dict):
            if isinstance(data.get("results"), dict):
                return self._extract_result_pages(data["results"])
            page_items = data.get("pages") or data.get("page_list") or data.get("documents")
            if isinstance(page_items, list):
                return self._normalize_page_items(page_items)
            for key in ("markdown", "md", "text", "content"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return [self._normalize_page_payload(1, value, [], data)]
        if isinstance(data, list):
            return self._normalize_page_items(data)
        raise AppException("MinerU解析响应缺少可用文本内容", status_code=502, code=502)

    def _extract_result_pages(self, results: dict[str, Any]) -> list[dict[str, Any]]:
        """兼容 MinerU 结果字典结构。"""

        for file_name, result in results.items():
            if not isinstance(result, dict):
                continue

            content_list_pages = self._extract_content_list_pages(result.get("content_list"))
            if content_list_pages:
                logger.info("MinerU结果已按 content_list 提取页级结构: file=%s pages=%s", file_name, len(content_list_pages))
                return content_list_pages

            page_items = result.get("pages") or result.get("page_list")
            if isinstance(page_items, list):
                return self._normalize_page_items(page_items)

            for key in ("md_content", "markdown", "md", "text", "content"):
                value = result.get(key)
                if isinstance(value, str) and value.strip():
                    logger.info("MinerU结果已按整文 Markdown 提取: file=%s", file_name)
                    return [self._normalize_page_payload(1, value, [], result)]

        raise AppException("MinerU任务结果缺少可用文本内容", status_code=502, code=502)

    def _extract_inline_image_payloads(self, payload: dict[str, Any]) -> dict[str, str]:
        """
        提取 MinerU 任务结果中的内联图片映射。

        说明：
            部分 MinerU `/tasks/{task_id}/result` 响应不会把图片稳定写入共享卷，
            而是直接在结果 JSON 顶层 `images` 中返回 data URL。
            这里统一抽取这些图片，后续根据 `img_path` 进行回填。
        """

        normalized_payloads: dict[str, str] = {}
        result_dicts: list[dict[str, Any]] = []

        raw_results = payload.get("results")
        if isinstance(raw_results, dict):
            result_dicts.extend(result for result in raw_results.values() if isinstance(result, dict))

        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("results"), dict):
            result_dicts.extend(result for result in data["results"].values() if isinstance(result, dict))

        for result in result_dicts:
            for image_key in MINERU_RESULT_IMAGE_KEYS:
                image_map = result.get(image_key)
                if not isinstance(image_map, dict):
                    continue
                for raw_key, raw_value in image_map.items():
                    if not isinstance(raw_key, str) or not isinstance(raw_value, str):
                        continue
                    if not raw_key.strip() or not raw_value.strip():
                        continue
                    self._register_inline_image_payload(normalized_payloads, raw_key, raw_value)

        return normalized_payloads

    def _register_inline_image_payload(self, payloads: dict[str, str], raw_key: str, raw_value: str) -> None:
        """
        为一张 MinerU 内联图片注册多个查找键。

        参数:
            payloads: 已收集的图片映射
            raw_key: MinerU 返回的原始 key
            raw_value: 对应的 data URL 或 base64 内容
        """

        for lookup_key in self._build_inline_image_lookup_keys(raw_key):
            payloads[lookup_key] = raw_value

    def _build_inline_image_lookup_keys(self, raw_key: str) -> set[str]:
        """
        根据原始图片键生成归一化查找键集合。

        参数:
            raw_key: `demo.jpg`、`images/demo.jpg` 或容器绝对路径

        返回:
            可用于和 `img_path` 对齐的查找键集合
        """

        normalized_key = raw_key.strip().replace("\\", "/")
        if not normalized_key:
            return set()

        lookup_keys = {normalized_key}
        normalized_path = PurePosixPath(normalized_key)
        file_name = normalized_path.name
        if file_name:
            lookup_keys.add(file_name)
            lookup_keys.add(f"{MINERU_IMAGES_DIR_NAME}/{file_name}")
        return lookup_keys

    def _extract_content_list_pages(self, content_list: Any) -> list[dict[str, Any]]:
        """解析 MinerU 的 `content_list` 结果。"""

        if isinstance(content_list, str):
            try:
                content_list = json.loads(content_list)
            except ValueError:
                logger.warning("MinerU content_list 不是合法JSON，忽略该字段并回退其他结果字段")
                return []

        if not isinstance(content_list, list):
            return []

        if any(isinstance(item, dict) and item.get("page_idx") is not None for item in content_list):
            return self._normalize_content_blocks(content_list)
        return self._normalize_page_items(content_list)

    def _normalize_content_blocks(self, block_items: list[Any]) -> list[dict[str, Any]]:
        """将块级 `content_list` 聚合为页级结构。"""

        page_buckets: dict[int, dict[str, Any]] = {}
        for index, item in enumerate(block_items, start=1):
            if not isinstance(item, dict):
                continue

            page_number = self._extract_page_number(item, index)
            block = self._normalize_block_item(item, index)
            page_bucket = page_buckets.setdefault(
                page_number,
                {
                    "page_number": page_number,
                    "content_parts": [],
                    "blocks": [],
                    "page_title": None,
                },
            )
            if block["text"]:
                page_bucket["content_parts"].append(block["text"])
            if block["block_type"] == "title" and not page_bucket["page_title"] and block["text"]:
                page_bucket["page_title"] = block["text"][:120]
            page_bucket["blocks"].append(block)

        pages: list[dict[str, Any]] = []
        for page_number, bucket in sorted(page_buckets.items()):
            content = "\n".join(part for part in bucket["content_parts"] if part).strip()
            pages.append(
                self._normalize_page_payload(
                    page_number=page_number,
                    content=content,
                    blocks=bucket["blocks"],
                    raw_page={"page_title": bucket["page_title"]},
                )
            )

        if not pages:
            raise AppException("MinerU content_list 为空，无法生成页级文本", status_code=502, code=502)
        return pages

    def _normalize_page_items(self, page_items: list[Any]) -> list[dict[str, Any]]:
        """标准化页级数组。"""

        pages: list[dict[str, Any]] = []
        for index, item in enumerate(page_items, start=1):
            if isinstance(item, str):
                pages.append(self._normalize_page_payload(index, item, [], {"content": item}))
                continue

            if not isinstance(item, dict):
                continue

            page_number = self._extract_page_number(item, index)
            raw_blocks = item.get("blocks") or item.get("page_blocks")
            normalized_blocks = []
            if isinstance(raw_blocks, list):
                normalized_blocks = [self._normalize_block_item(block_item, block_index) for block_index, block_item in enumerate(raw_blocks, start=1)]

            content = self._extract_primary_text(item)
            if not content and normalized_blocks:
                content = "\n".join(block["text"] for block in normalized_blocks if block["text"]).strip()
            pages.append(self._normalize_page_payload(page_number, content, normalized_blocks, item))

        if not pages:
            raise AppException("MinerU解析响应页面为空", status_code=502, code=502)
        return pages

    def _normalize_page_payload(
        self,
        page_number: int,
        content: str,
        blocks: list[dict[str, Any]],
        raw_page: dict[str, Any],
    ) -> dict[str, Any]:
        """组装统一页级结构。"""

        page_title = raw_page.get("page_title") or raw_page.get("title")
        if not page_title:
            title_block = next((block for block in blocks if block["block_type"] == "title" and block["text"]), None)
            if title_block:
                page_title = title_block["text"][:120]

        page_payload = {
            "page_number": int(page_number),
            "content": str(content or ""),
            "page_title": page_title,
            "drawing_no": raw_page.get("drawing_no"),
            "layout": raw_page.get("layout") or raw_page.get("layout_json"),
            "blocks": blocks,
            "page_image_candidates": self._extract_page_image_candidates(raw_page),
        }
        return page_payload

    def _normalize_block_item(self, item: Any, fallback_index: int) -> dict[str, Any]:
        """将任意块对象标准化为统一结构。"""

        if isinstance(item, dict):
            raw_type = str(item.get("type") or item.get("block_type") or item.get("category") or "text")
            block_type = self._normalize_block_type(raw_type)
            text = self._extract_primary_text(item)
            bbox = next((item.get(key) for key in BLOCK_BBOX_KEYS if item.get(key) is not None), None)
            image_candidates = self._extract_image_candidates(item)
            if image_candidates and block_type == "text":
                block_type = "image"
            return {
                "block_index": fallback_index,
                "block_type": block_type,
                "text": text,
                "bbox": bbox,
                "metadata": self._extract_block_metadata(item),
                "image_candidates": image_candidates,
            }

        return {
            "block_index": fallback_index,
            "block_type": "text",
            "text": str(item),
            "bbox": None,
            "metadata": {},
            "image_candidates": [],
        }

    def _extract_primary_text(self, item: dict[str, Any]) -> str:
        """从页或块对象中提取主文本内容。"""

        for key in BLOCK_TEXT_KEYS:
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _extract_page_number(self, item: dict[str, Any], fallback_number: int) -> int:
        """提取页码，兼容 page_idx/page_no/page_number。"""

        page_number = item.get("page_number") or item.get("page_no") or item.get("page")
        if page_number is None and item.get("page_idx") is not None:
            page_number = int(item["page_idx"]) + 1
        return int(page_number or fallback_number)

    def _normalize_block_type(self, raw_type: str) -> str:
        """归一化块类型名称。"""

        normalized = raw_type.strip().lower()
        if normalized in IMAGE_BLOCK_HINTS:
            return "image"
        if "title" in normalized or "heading" in normalized:
            return "title"
        if "table" in normalized:
            return "table"
        if "formula" in normalized or "equation" in normalized:
            return "formula"
        return "text"

    def _extract_block_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
        """提取适合入库的轻量块元数据。"""

        metadata: dict[str, Any] = {}
        for key, value in item.items():
            if key in METADATA_EXCLUDED_KEYS or key in BLOCK_TEXT_KEYS or key in BLOCK_BBOX_KEYS:
                continue
            if key in {"type", "block_type", "category", "page_idx", "page_number", "page_no", "page"}:
                continue
            metadata[key] = value
        return metadata

    def _extract_page_image_candidates(self, raw_page: dict[str, Any]) -> list[dict[str, Any]]:
        """提取页级预览图候选。"""

        candidates: list[dict[str, Any]] = []
        for key, value in raw_page.items():
            key_lower = key.lower()
            if not any(hint in key_lower for hint in PAGE_PREVIEW_HINT_KEYS):
                continue
            candidate = self._candidate_from_value(key, value, raw_page)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _extract_image_candidates(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        """提取块级图片候选。"""

        candidates: list[dict[str, Any]] = []
        for key, value in item.items():
            candidate = self._candidate_from_value(key, value, item)
            if candidate:
                candidates.append(candidate)
        return candidates

    def _candidate_from_value(self, key: str, value: Any, container: dict[str, Any]) -> dict[str, Any] | None:
        """根据字段值构造图片候选对象。"""

        if not value:
            return None

        key_lower = key.lower()
        file_name = self._extract_candidate_name(container)
        mime_type = self._extract_candidate_mime_type(container)

        if isinstance(value, str):
            if key_lower in IMAGE_BASE64_KEYS or value.startswith("data:image/"):
                return {
                    "payload_base64": value,
                    "mime_type": mime_type or self._mime_type_from_data_url(value),
                    "file_name": file_name,
                    "candidate_type": "payload_base64",
                    "original_candidate_value": value,
                }
            if key_lower in IMAGE_PATH_KEYS and Path(value).suffix:
                return {
                    "local_path": value,
                    "mime_type": mime_type,
                    "file_name": file_name or Path(value).name,
                    "candidate_type": "local_path",
                    "original_candidate_value": value,
                }
            if key_lower in IMAGE_URL_KEYS and value.startswith(("http://", "https://")):
                return {
                    "remote_url": value,
                    "mime_type": mime_type,
                    "file_name": file_name or Path(value).name,
                    "candidate_type": "remote_url",
                    "original_candidate_value": value,
                }
        return None

    def _extract_candidate_name(self, container: dict[str, Any]) -> str | None:
        """提取图片文件名。"""

        for key in IMAGE_NAME_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return Path(value.strip()).name
        return None

    def _extract_candidate_mime_type(self, container: dict[str, Any]) -> str | None:
        """提取图片 MIME 类型。"""

        for key in IMAGE_MIME_KEYS:
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return None

    def _mime_type_from_data_url(self, value: str) -> str | None:
        """从 data URL 提取 MIME 类型。"""

        if not value.startswith("data:") or "," not in value:
            return None
        header = value.split(",", 1)[0]
        mime_type = header.removeprefix("data:").split(";", 1)[0]
        return mime_type or None

    def _prepare_output_root(self) -> Path:
        """
        校验 MinerU Docker 共享卷宿主机目录。
        返回:
            可读写的宿主机输出根目录。
        """

        try:
            return self._ensure_output_mapping_ready_compat()
        except ValueError as exc:
            logger.exception("MinerU Docker 共享卷配置无效")
            raise AppException(f"MinerU Docker 共享卷配置无效：{exc}", status_code=500, code=500) from exc

    def _ensure_output_mapping_ready_compat(self) -> Path:
        """
        兼容旧版 Settings 对象的 MinerU 输出目录校验。

        说明：
            API 或 Worker 未重启时，运行时可能拿到缺少扩展方法的
            Settings 实例。这里保留必要校验，避免解析任务因为配置对象
            版本差异失败。
        """

        container_dir = self._mineru_output_container_root()
        if not container_dir.strip():
            raise ValueError("已配置 MINERU_BASE_URL，但缺少 MINERU_OUTPUT_CONTAINER_DIR")

        host_path = self._mineru_output_host_path()
        host_path.mkdir(parents=True, exist_ok=True)
        if not host_path.is_dir():
            raise ValueError(f"MinerU 输出宿主机目录不是有效目录: {host_path}")
        return host_path

    def _mineru_output_host_path(self) -> Path:
        """
        获取 MinerU 输出宿主机路径，兼容缺少扩展属性的 Settings 对象。
        """

        configured_path = getattr(self.settings, "mineru_output_host_path", None)
        if isinstance(configured_path, Path):
            return configured_path

        host_dir = str(getattr(self.settings, "mineru_output_host_dir", "storage/mineru-output") or "storage/mineru-output")
        resolve_local_path = getattr(self.settings, "resolve_local_path", None)
        if callable(resolve_local_path):
            return resolve_local_path(host_dir)

        host_path = Path(host_dir)
        if host_path.is_absolute():
            return host_path
        return (Path.cwd() / host_path).resolve(strict=False)

    def _mineru_output_container_root(self) -> str:
        """
        获取 MinerU 容器内输出根目录，默认对齐当前 Docker 启动脚本。
        """

        return str(getattr(self.settings, "mineru_output_container_dir", "/workspace/output") or "/workspace/output")

    def _task_output_container_dir(self, task_id: str) -> str:
        """
        计算 MinerU 任务在容器内的输出目录。
        参数:
            task_id: MinerU 任务ID。
        返回:
            约定的容器内任务输出目录。
        """

        root = self._mineru_output_container_root().rstrip("/\\")
        return f"{root}/{task_id}"

    def _task_output_host_dir(self, task_id: str) -> Path:
        """
        计算 MinerU 任务在宿主机共享卷中的输出目录。
        参数:
            task_id: MinerU 任务ID。
        返回:
            约定的宿主机任务输出目录。
        """

        return self._mineru_output_host_path() / task_id

    def _resolve_output_host_dir(self, task_id: str, task_output_host_dir: Path) -> Path:
        """
        解析 MinerU 任务产物在宿主机上的实际目录。
        参数:
            task_id: MinerU 任务ID。
            task_output_host_dir: 按约定推导出的任务目录。
        返回:
            后续图片路径解析应使用的宿主机目录。
        """

        if task_output_host_dir.exists():
            return task_output_host_dir

        output_root = self._mineru_output_host_path()
        logger.warning(
            "未找到按 task_id 推导的 MinerU 输出目录，回退共享卷根目录: task_id=%s expected_dir=%s fallback_dir=%s",
            task_id,
            task_output_host_dir,
            output_root,
        )
        return output_root

    def _find_optional_artifact_path(self, output_dir: Path, file_name: str) -> str | None:
        """
        查找指定名称的 MinerU 产物文件。
        参数:
            output_dir: 任务输出目录。
            file_name: 目标文件名。
        返回:
            找到时返回绝对路径，否则返回 None。
        """

        direct_path = output_dir / file_name
        if direct_path.is_file():
            return str(direct_path)
        for candidate in output_dir.rglob(file_name):
            if candidate.is_file():
                return str(candidate)
        return None

    def _find_optional_directory_path(self, output_dir: Path, directory_name: str) -> str | None:
        """
        查找指定名称的 MinerU 产物目录。
        参数:
            output_dir: 任务输出目录。
            directory_name: 目录名。
        返回:
            找到时返回绝对路径，否则返回 None。
        """

        direct_path = output_dir / directory_name
        if direct_path.is_dir():
            return str(direct_path)
        for candidate in output_dir.rglob(directory_name):
            if candidate.is_dir():
                return str(candidate)
        return None

    def _find_markdown_artifact_path(self, output_dir: Path) -> str | None:
        """
        查找 MinerU 导出的 markdown 文件或目录。
        参数:
            output_dir: 任务输出目录。
        返回:
            markdown 文件或目录的绝对路径。
        """

        for candidate in output_dir.glob("*.md"):
            if candidate.is_file():
                return str(candidate)
        markdown_dir = output_dir / "markdown"
        if markdown_dir.is_dir():
            return str(markdown_dir)
        return None

    def _apply_candidate_resolution_context(
        self,
        pages: list[dict[str, Any]],
        output_host_dir: Path,
        output_container_dir: str,
        inline_image_payloads: dict[str, str],
    ) -> None:
        """
        为所有图片候选补充 Docker 共享卷路径解析上下文。
        参数:
            pages: 页级解析结果。
            output_host_dir: 宿主机任务输出目录。
            output_container_dir: 容器内任务输出目录。
        """

        for page_payload in pages:
            for candidate in page_payload.get("page_image_candidates") or []:
                self._annotate_candidate_resolution(
                    candidate,
                    output_host_dir,
                    output_container_dir,
                    inline_image_payloads,
                )
            for block_payload in page_payload.get("blocks") or []:
                for candidate in block_payload.get("image_candidates") or []:
                    self._annotate_candidate_resolution(
                        candidate,
                        output_host_dir,
                        output_container_dir,
                        inline_image_payloads,
                    )

    def _annotate_candidate_resolution(
        self,
        candidate: dict[str, Any],
        output_host_dir: Path,
        output_container_dir: str,
        inline_image_payloads: dict[str, str],
    ) -> None:
        """
        为单个图片候选补充相对路径解析信息。
        参数:
            candidate: 图片候选字典。
            output_host_dir: 宿主机任务输出目录。
            output_container_dir: 容器内任务输出目录。
        """

        candidate["resolution_base_dir"] = str(output_host_dir)
        self._bind_inline_image_payload(candidate, inline_image_payloads)

        local_path_value = str(candidate.get("local_path") or "").strip()
        if not local_path_value:
            return

        local_path = Path(local_path_value)
        if local_path.is_absolute() or local_path_value.replace("\\", "/").startswith("/"):
            mapped_path = self._map_container_path_to_host(local_path, output_container_dir, output_host_dir)
            candidate["resolved_local_path"] = str(mapped_path)
            candidate["resolution_status"] = (
                "container_path_mapped" if mapped_path != local_path else "absolute_path_direct"
            )
            return

        resolved_path = (output_host_dir / local_path).resolve(strict=False)
        candidate["resolved_local_path"] = str(resolved_path)
        candidate["resolution_status"] = "relative_to_output_dir"

    def _bind_inline_image_payload(
        self,
        candidate: dict[str, Any],
        inline_image_payloads: dict[str, str],
    ) -> None:
        """
        根据 `img_path` 把 MinerU 顶层 `images` 中的内联图片挂回 candidate。

        参数:
            candidate: 当前图片候选对象
            inline_image_payloads: 归一化后的内联图片映射
        """

        if candidate.get("payload_base64") or not inline_image_payloads:
            return

        local_path_value = str(candidate.get("local_path") or "").strip()
        if not local_path_value:
            return

        for lookup_key in self._build_inline_image_lookup_keys(local_path_value):
            payload = inline_image_payloads.get(lookup_key)
            if not payload:
                continue
            candidate["payload_base64"] = payload
            candidate["payload_source"] = "mineru_result_images"
            candidate["inline_payload_key"] = lookup_key
            candidate["resolution_status"] = candidate.get("resolution_status") or "inline_image_payload"
            if not candidate.get("mime_type"):
                candidate["mime_type"] = self._mime_type_from_data_url(payload)
            if not candidate.get("file_name"):
                candidate["file_name"] = PurePosixPath(local_path_value.replace("\\", "/")).name
            return

    def _map_container_path_to_host(
        self,
        candidate_path: Path,
        output_container_dir: str,
        output_host_dir: Path,
    ) -> Path:
        """
        将容器内绝对路径映射到宿主机共享卷路径。
        参数:
            candidate_path: MinerU 返回的绝对路径。
            output_container_dir: 容器内任务输出目录。
            output_host_dir: 宿主机任务输出目录。
        返回:
            宿主机可读取的绝对路径；若无法映射则原样返回。
        """

        candidate_posix = PurePosixPath(str(candidate_path).replace("\\", "/"))
        task_output_posix = PurePosixPath(str(output_container_dir).replace("\\", "/"))
        root_output_posix = PurePosixPath(self._mineru_output_container_root().replace("\\", "/"))

        try:
            relative_path = candidate_posix.relative_to(task_output_posix)
            return output_host_dir.joinpath(*relative_path.parts)
        except ValueError:
            try:
                relative_path = candidate_posix.relative_to(root_output_posix)
                return output_host_dir.parent.joinpath(*relative_path.parts)
            except ValueError:
                return candidate_path

    def _extract_task_id(self, payload: dict[str, Any]) -> str:
        """从提交响应中提取任务ID。"""

        task_id = payload.get("task_id") or payload.get("id")
        if task_id:
            return str(task_id)

        data = payload.get("data")
        if isinstance(data, dict):
            task_id = data.get("task_id") or data.get("id")
            if task_id:
                return str(task_id)

        raise AppException(f"MinerU任务提交响应缺少 task_id：{payload}", status_code=502, code=502)

    def _extract_task_status(self, payload: dict[str, Any]) -> str:
        """从状态响应中提取任务状态。"""

        status = payload.get("status")
        if status:
            return str(status)

        data = payload.get("data")
        if isinstance(data, dict) and data.get("status"):
            return str(data["status"])

        task = payload.get("task")
        if isinstance(task, dict) and task.get("status"):
            return str(task["status"])

        return MINERU_STATUS_UNKNOWN

    def _extract_task_error(self, payload: dict[str, Any]) -> str:
        """从状态响应中提取任务错误信息。"""

        for key in ("error", "message", "msg", "detail"):
            value = payload.get(key)
            if value:
                return str(value)

        data = payload.get("data")
        if isinstance(data, dict):
            for key in ("error", "message", "msg", "detail"):
                value = data.get(key)
                if value:
                    return str(value)

        return "MinerU 未返回详细错误信息"

    def _log_http_warning(self, stage: str, identifier: str, response: requests.Response) -> None:
        """记录 MinerU HTTP 异常响应摘要。"""

        logger.warning(
            "MinerU接口响应异常: stage=%s identifier=%s status_code=%s body=%s",
            stage,
            identifier,
            response.status_code,
            response.text[:1000],
        )

    def _current_monotonic(self) -> float:
        """获取当前 monotonic 时间戳。"""

        return time.monotonic()

    def _sleep_seconds(self, seconds: int) -> None:
        """休眠指定秒数。"""

        time.sleep(seconds)

    def _content_type(self, path: Path) -> str:
        """根据文件后缀补充上传 MIME。"""

        return {
            ".pdf": "application/pdf",
            ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".ppt": "application/vnd.ms-powerpoint",
            ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }.get(path.suffix.lower(), "application/octet-stream")
