"""
LLM Service

负责：
1. 读取默认 LLM 配置
2. 调用真实 OpenAI-compatible Chat Completions 接口
3. 支持同步回答与流式回答
4. 记录模型调用耗时与异常信息
"""

from __future__ import annotations

import base64
import json
import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.core.minio import get_minio_client
from app.models.document_asset import DocumentAsset
from app.models.model_config import ModelConfig
from app.repositories.model_repository import ModelConfigRepository
from app.retrieval.schemas import Evidence
from app.services.document_asset_service import DocumentAssetService

logger = logging.getLogger(__name__)

DISABLED_MODEL_PROVIDERS = {"fallback", "mock", "mork", "dummy", "fake", "demo"}
NO_EVIDENCE_ANSWER = "当前知识库未找到足够依据，无法确认该问题。"
STREAM_DONE_TOKEN = "[DONE]"


@dataclass(frozen=True)
class RuntimeModelConfig:
    """运行时模型配置。"""

    provider: str
    model_name: str
    api_base: str
    api_key: str | None


class LLMService:
    """大语言模型服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.model_repository = ModelConfigRepository(db)
        self.asset_service = DocumentAssetService(db)

    def answer_with_evidence(self, question: str, evidences: list[Evidence]) -> str:
        """基于检索证据生成文本回答。"""

        if not evidences:
            return NO_EVIDENCE_ANSWER
        return self.chat(self._build_text_messages(question, evidences))

    def stream_answer_with_evidence(self, question: str, evidences: list[Evidence]) -> Iterator[str]:
        """基于检索证据生成流式文本回答。"""

        if not evidences:
            yield NO_EVIDENCE_ANSWER
            return
        yield from self.stream_chat(self._build_text_messages(question, evidences))

    def answer_with_multimodal_evidence(self, question: str, evidences: list[Evidence]) -> str:
        """基于文本证据和命中页图片生成回答。"""

        if not evidences:
            return NO_EVIDENCE_ANSWER

        image_parts = self._build_image_parts(evidences)
        if not image_parts:
            return self.answer_with_evidence(question, evidences)

        return self.chat(
            self._build_multimodal_messages(question, evidences, image_parts),
            model_type="vision_llm",
            timeout_seconds=self.settings.vision_llm_timeout_seconds,
        )

    def stream_answer_with_multimodal_evidence(self, question: str, evidences: list[Evidence]) -> Iterator[str]:
        """基于文本证据和命中页图片生成流式回答。"""

        if not evidences:
            yield NO_EVIDENCE_ANSWER
            return

        image_parts = self._build_image_parts(evidences)
        if not image_parts:
            yield from self.stream_answer_with_evidence(question, evidences)
            return

        yield from self.stream_chat(
            self._build_multimodal_messages(question, evidences, image_parts),
            model_type="vision_llm",
            timeout_seconds=self.settings.vision_llm_timeout_seconds,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        model_type: str = "llm",
        timeout_seconds: int | None = None,
    ) -> str:
        """调用同步 Chat Completions 接口。"""

        runtime_config = self._runtime_config(model_type)
        url = f"{runtime_config.api_base.rstrip('/')}/chat/completions"
        payload = self._build_chat_payload(runtime_config.model_name, messages)
        headers = self._build_headers(runtime_config)

        started_at = time.perf_counter()
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds or self.settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = self._flatten_message_content(data["choices"][0]["message"]["content"])
            logger.info(
                "LLM调用成功: provider=%s model=%s model_type=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                model_type,
                int((time.perf_counter() - started_at) * 1000),
            )
            return content.strip()
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.exception(
                "LLM调用失败: provider=%s model=%s model_type=%s",
                runtime_config.provider,
                runtime_config.model_name,
                model_type,
            )
            raise AppException(f"LLM真实接口调用失败: {exc}", status_code=502, code=502) from exc

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model_type: str = "llm",
        timeout_seconds: int | None = None,
    ) -> Iterator[str]:
        """调用流式 Chat Completions 接口。"""

        runtime_config = self._runtime_config(model_type)
        url = f"{runtime_config.api_base.rstrip('/')}/chat/completions"
        payload = self._build_chat_payload(runtime_config.model_name, messages, stream=True)
        headers = self._build_headers(runtime_config)

        started_at = time.perf_counter()
        response = None
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout_seconds or self.settings.llm_timeout_seconds,
                stream=True,
            )
            response.raise_for_status()
            for line in response.iter_lines(decode_unicode=True):
                if not line:
                    continue
                raw_line = line.strip()
                if not raw_line or raw_line.startswith(":") or not raw_line.startswith("data:"):
                    continue
                chunk = raw_line[5:].strip()
                if chunk == STREAM_DONE_TOKEN:
                    break
                try:
                    payload_json = json.loads(chunk)
                except json.JSONDecodeError:
                    logger.warning("LLM流式响应包含无法解析的分片，已忽略: provider=%s chunk=%s", runtime_config.provider, chunk[:200])
                    continue
                if payload_json.get("error"):
                    raise AppException(
                        f"LLM真实接口调用失败: {payload_json['error']}",
                        status_code=502,
                        code=502,
                    )
                delta = self._extract_stream_delta(payload_json)
                if delta:
                    yield delta
            logger.info(
                "LLM流式调用成功: provider=%s model=%s model_type=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                model_type,
                int((time.perf_counter() - started_at) * 1000),
            )
        except requests.RequestException as exc:
            logger.exception(
                "LLM流式调用失败: provider=%s model=%s model_type=%s",
                runtime_config.provider,
                runtime_config.model_name,
                model_type,
            )
            raise AppException(f"LLM真实接口调用失败: {exc}", status_code=502, code=502) from exc
        finally:
            if response is not None:
                response.close()

    def test_chat_completion(self, config: ModelConfig) -> dict:
        """测试指定 LLM 配置。"""

        runtime_config = self._runtime_config(config.model_type or "llm", config)
        answer = self._call_test_prompt(runtime_config)
        return {
            "status": "success",
            "provider": runtime_config.provider,
            "model": runtime_config.model_name,
            "answer": answer,
        }

    def _call_test_prompt(self, runtime_config: RuntimeModelConfig) -> str:
        """执行最小化连通性测试。"""

        url = f"{runtime_config.api_base.rstrip('/')}/chat/completions"
        headers = self._build_headers(runtime_config)
        payload = self._build_chat_payload(
            runtime_config.model_name,
            [{"role": "user", "content": "请回复：连接正常"}],
            temperature=0,
        )
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=self.settings.llm_timeout_seconds)
            response.raise_for_status()
            data = response.json()
            return self._flatten_message_content(data["choices"][0]["message"]["content"]).strip()
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.exception("LLM配置测试失败: provider=%s model=%s", runtime_config.provider, runtime_config.model_name)
            raise AppException(f"LLM配置测试失败: {exc}", status_code=502, code=502) from exc

    def _runtime_config(self, model_type: str, config: ModelConfig | None = None) -> RuntimeModelConfig:
        """解析运行时模型配置。"""

        model_config = config or self.model_repository.get_default(model_type)
        if model_type == "vision_llm":
            provider = (model_config.provider if model_config else self.settings.vision_llm_provider).strip()
            model_name = (model_config.model_name if model_config else self.settings.vision_llm_model).strip()
            api_base = (model_config.api_base if model_config else None) or self.settings.vision_llm_base_url
            api_key = (model_config.api_key if model_config else None) or self.settings.vision_llm_api_key
            missing_model_message = "未配置 VISION_LLM_MODEL 或默认视觉模型名称"
            missing_base_message = "未配置 VISION_LLM_BASE_URL 或默认 vision_llm API Base"
        else:
            provider = (model_config.provider if model_config else self.settings.llm_provider).strip()
            model_name = (model_config.model_name if model_config else self.settings.llm_model).strip()
            api_base = (
                (model_config.api_base if model_config else None)
                or self.settings.llm_base_url
                or self.settings.openai_compatible_base_url
            )
            api_key = (model_config.api_key if model_config else None) or self.settings.llm_api_key or self.settings.openai_api_key
            missing_model_message = "未配置 LLM_MODEL 或默认 LLM 模型名称"
            missing_base_message = "未配置 LLM_BASE_URL 或默认 LLM API Base"

        if provider.lower() in DISABLED_MODEL_PROVIDERS:
            raise AppException("已禁用 mock/fallback 模型配置，请配置真实 LLM 服务", status_code=500, code=500)
        if not model_name:
            raise AppException(missing_model_message, status_code=500, code=500)
        if not api_base:
            raise AppException(missing_base_message, status_code=500, code=500)
        return RuntimeModelConfig(provider=provider, model_name=model_name, api_base=api_base, api_key=api_key)

    def _build_headers(self, runtime_config: RuntimeModelConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if runtime_config.api_key:
            headers["Authorization"] = f"Bearer {runtime_config.api_key}"
        return headers

    def _build_chat_payload(
        self,
        model_name: str,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if stream:
            payload["stream"] = True
        return payload

    def _build_text_messages(self, question: str, evidences: list[Evidence]) -> list[dict[str, Any]]:
        prompt = self._build_rag_prompt(question, evidences)
        return [
            {
                "role": "system",
                "content": (
                    "你是企业知识库问答助手。必须只基于给定资料回答。"
                    "如果资料不足，请明确说明无法确认。回答中保留简洁结论和来源编号。"
                ),
            },
            {"role": "user", "content": prompt},
        ]

    def _build_multimodal_messages(
        self,
        question: str,
        evidences: list[Evidence],
        image_parts: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        prompt = "\n\n".join(
            [
                self._build_rag_prompt(question, evidences),
                (
                    "图片证据已随本次消息提供。请结合图片中的设备、管线、箭头和仪表标识回答流程问题。"
                    "如果图片或文字证据都无法确认某个细节，请明确说明无法确认。"
                ),
            ]
        )
        return [
            {
                "role": "system",
                "content": (
                    "你是企业知识库多模态问答助手。必须只基于给定文字资料和图片证据回答；"
                    "涉及 PID/P&ID 图时，请按物料流向、关键设备和控制/过滤/输送环节组织答案，并保留来源编号。"
                ),
            },
            {
                "role": "user",
                "content": [{"type": "text", "text": prompt}, *image_parts],
            },
        ]

    def _extract_stream_delta(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        delta = choices[0].get("delta")
        if isinstance(delta, dict):
            return self._flatten_message_content(delta.get("content"))
        message = choices[0].get("message")
        if isinstance(message, dict):
            return self._flatten_message_content(message.get("content"))
        return ""

    def _flatten_message_content(self, content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    elif isinstance(item.get("content"), str):
                        parts.append(item["content"])
            return "".join(parts)
        return str(content)

    def _build_image_parts(self, evidences: list[Evidence]) -> list[dict[str, Any]]:
        """构建 OpenAI-compatible 视觉消息片段。"""

        image_parts: list[dict[str, Any]] = []
        seen_asset_ids: set[int] = set()
        max_images = max(0, int(self.settings.vision_llm_max_images))
        max_bytes = max(0, int(self.settings.vision_llm_max_image_bytes))

        for evidence in evidences:
            for evidence_asset in evidence.assets:
                if len(image_parts) >= max_images:
                    return image_parts
                if evidence_asset.asset_id in seen_asset_ids:
                    continue
                seen_asset_ids.add(evidence_asset.asset_id)

                asset = self.asset_service.get_asset(evidence_asset.asset_id)
                if asset is None or asset.status != "ready":
                    continue
                mime_type = str(asset.mime_type or evidence_asset.mime_type or "").lower()
                if not mime_type.startswith("image/"):
                    continue
                if max_bytes > 0 and int(asset.file_size or 0) > max_bytes:
                    logger.warning(
                        "视觉证据图片超过大小限制，跳过模型输入: asset_id=%s file_size=%s max_bytes=%s",
                        asset.id,
                        asset.file_size,
                        max_bytes,
                    )
                    continue

                bytes_payload = self._read_asset_bytes(asset)
                if max_bytes > 0 and len(bytes_payload) > max_bytes:
                    logger.warning(
                        "视觉证据图片读取后超过大小限制，跳过模型输入: asset_id=%s bytes=%s max_bytes=%s",
                        asset.id,
                        len(bytes_payload),
                        max_bytes,
                    )
                    continue
                encoded = base64.b64encode(bytes_payload).decode("ascii")
                image_parts.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                    }
                )

        logger.info("视觉模型图片输入构建完成: image_count=%s", len(image_parts))
        return image_parts

    def _read_asset_bytes(self, asset: DocumentAsset) -> bytes:
        """读取视觉证据图片字节，优先使用本地文件，必要时回退到 MinIO。"""

        if asset.storage_path:
            asset_path = self.settings.resolve_local_path(asset.storage_path)
            if asset_path.is_file():
                return asset_path.read_bytes()

        if asset.object_key:
            client = get_minio_client()
            if client is None:
                raise AppException("对象存储未启用，无法读取视觉证据图片", status_code=404, code=404)
            response = client.get_object(self.settings.minio_bucket, asset.object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        raise AppException("视觉证据图片文件不存在", status_code=404, code=404)

    def _build_rag_prompt(self, question: str, evidences: list[Evidence]) -> str:
        """构建带来源追踪信息的 RAG 提示词。"""

        evidence_lines: list[str] = []
        for index, evidence in enumerate(evidences, start=1):
            content = evidence.content.replace("\r", " ").strip()
            asset_summary = ", ".join(
                f"asset_id={asset.asset_id}, type={asset.asset_type}, page_no={asset.page_number or '-'}"
                for asset in evidence.assets
            )
            evidence_lines.append(
                "\n".join(
                    [
                        f"[{index}] file={evidence.file_name}",
                        (
                            f"project_id={evidence.project_id or '-'}, document_id={evidence.document_id}, "
                            f"drawing_no={evidence.drawing_no or '-'}, page_no={evidence.page_number or '-'}, "
                            f"chunk_id={evidence.chunk_id}"
                        ),
                        f"visual_assets={asset_summary}" if asset_summary else "visual_assets=-",
                        content,
                    ]
                )
            )
        return "\n\n".join(
            [
                f"问题：{question}",
                "资料：",
                "\n\n".join(evidence_lines),
                "请基于资料直接回答，并在关键结论后标注来源编号，例如 [1]。",
            ]
        )
