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
from app.services.rag_prompt_templates import (
    ANSWER_SYSTEM_PROMPT,
    VISION_ANSWER_SYSTEM_PROMPT,
    answer_instruction_for_profile,
    answer_scope_instruction,
)

logger = logging.getLogger(__name__)

DISABLED_MODEL_PROVIDERS = {"fallback", "mock", "mork", "dummy", "fake", "demo"}
NO_EVIDENCE_ANSWER = "当前知识库未找到足够依据，无法确认该问题。"
INDUSTRY_GENERAL_KNOWLEDGE_NOTICE = "说明：当前未检索到可引用的行业基础知识库资料，以上内容基于模型通用知识进行回答。"
STREAM_DONE_TOKEN = "[DONE]"
TEXT_MODEL_DEFAULT_FIELDS = {
    "llm": "llm_model",
    "intent": "intent_llm_model",
    "planner": "planner_llm_model",
    "evidence_judge_fast": "evidence_judge_fast_model",
    "evidence_judge": "evidence_judge_model",
    "answer_llm": "answer_llm_model",
    "analysis_llm": "analysis_llm_model",
}
VISION_MODEL_TYPES = {"vision_llm"}
STRUCTURED_JSON_MODEL_TYPES = {"intent", "planner", "evidence_judge_fast", "evidence_judge"}
NON_THINKING_MODEL_TYPES = {"intent", "planner", "evidence_judge_fast", "evidence_judge"}
TASK_TIMEOUT_FIELDS = {
    "evidence_judge_fast": "evidence_judge_timeout_seconds",
    "evidence_judge": "evidence_judge_timeout_seconds",
    "vision_llm": "vision_llm_timeout_seconds",
}
SHORT_CHAIN_MODEL_TYPES = {"evidence_judge_fast", "evidence_judge"}
SHORT_CHAIN_TIMEOUT_MAX_SECONDS = 15
MIN_TIMEOUT_SECONDS = 1


@dataclass(frozen=True)
class RuntimeModelConfig:
    """运行时模型配置。"""

    provider: str
    model_name: str
    api_base: str
    api_key: str | None
    model_type: str = "llm"
    source: str = "database"


class LLMService:
    """大语言模型服务。"""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.settings = get_settings()
        self.model_repository = ModelConfigRepository(db)
        self.asset_service = DocumentAssetService(db)
        self.last_runtime_config: RuntimeModelConfig | None = None
        self.last_timeout_seconds: int | None = None

    def answer_with_evidence(
        self,
        question: str,
        evidences: list[Evidence],
        model_type: str = "llm",
        query_profile: dict[str, Any] | None = None,
    ) -> str:
        """基于检索证据生成文本回答。"""

        if not evidences:
            return self._answer_without_evidence(question, model_type, query_profile)
        return self.chat(self._build_text_messages(question, evidences, query_profile), model_type=model_type)

    def stream_answer_with_evidence(
        self,
        question: str,
        evidences: list[Evidence],
        model_type: str = "llm",
        query_profile: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """基于检索证据生成流式文本回答。"""

        if not evidences:
            yield from self._stream_answer_without_evidence(question, model_type, query_profile)
            return
        yield from self.stream_chat(self._build_text_messages(question, evidences, query_profile), model_type=model_type)

    def answer_with_multimodal_evidence(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
    ) -> str:
        """基于文本证据和命中页图片生成回答。"""

        if not evidences:
            return self._answer_without_evidence(question, "answer_llm", query_profile)

        image_parts = self._build_image_parts(evidences)
        if not image_parts:
            return self.answer_with_evidence(question, evidences, query_profile=query_profile)

        return self.chat(
            self._build_multimodal_messages(question, evidences, image_parts, query_profile),
            model_type="vision_llm",
            timeout_seconds=self.settings.vision_llm_timeout_seconds,
        )

    def stream_answer_with_multimodal_evidence(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
    ) -> Iterator[str]:
        """基于文本证据和命中页图片生成流式回答。"""

        if not evidences:
            yield from self._stream_answer_without_evidence(question, "answer_llm", query_profile)
            return

        image_parts = self._build_image_parts(evidences)
        if not image_parts:
            yield from self.stream_answer_with_evidence(question, evidences, query_profile=query_profile)
            return

        yield from self.stream_chat(
            self._build_multimodal_messages(question, evidences, image_parts, query_profile),
            model_type="vision_llm",
            timeout_seconds=self.settings.vision_llm_timeout_seconds,
        )

    def chat(
        self,
        messages: list[dict[str, Any]],
        model_type: str = "llm",
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
        disable_thinking: bool = False,
    ) -> str:
        """调用同步 Chat Completions 接口。"""

        runtime_config = self._runtime_config(model_type)
        self.last_runtime_config = runtime_config
        url = f"{runtime_config.api_base.rstrip('/')}/chat/completions"
        payload = self._build_chat_payload(runtime_config, messages, max_tokens=max_tokens, disable_thinking=disable_thinking)
        headers = self._build_headers(runtime_config)
        effective_timeout_seconds = self._resolve_timeout_seconds(model_type, timeout_seconds)
        self.last_timeout_seconds = effective_timeout_seconds

        started_at = time.perf_counter()
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=effective_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = self._flatten_message_content(data["choices"][0]["message"]["content"])
            logger.info(
                "LLM调用成功: provider=%s model=%s model_type=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                runtime_config.model_type,
                int((time.perf_counter() - started_at) * 1000),
            )
            return content.strip()
        except requests.Timeout as exc:
            logger.warning(
                "LLM调用超时: provider=%s model=%s model_type=%s timeout_seconds=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                runtime_config.model_type,
                effective_timeout_seconds,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise AppException("LLM接口响应超时，请稍后重试", status_code=504, code=504) from exc
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.exception(
                "LLM调用失败: provider=%s model=%s model_type=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                runtime_config.model_type,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise AppException("LLM真实接口调用失败，请检查模型服务配置或稍后重试", status_code=502, code=502) from exc

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        model_type: str = "llm",
        timeout_seconds: int | None = None,
        max_tokens: int | None = None,
        disable_thinking: bool = False,
    ) -> Iterator[str]:
        """调用流式 Chat Completions 接口。"""

        runtime_config = self._runtime_config(model_type)
        self.last_runtime_config = runtime_config
        url = f"{runtime_config.api_base.rstrip('/')}/chat/completions"
        payload = self._build_chat_payload(
            runtime_config,
            messages,
            stream=True,
            max_tokens=max_tokens,
            disable_thinking=disable_thinking,
        )
        headers = self._build_headers(runtime_config)
        effective_timeout_seconds = self._resolve_timeout_seconds(model_type, timeout_seconds)
        self.last_timeout_seconds = effective_timeout_seconds

        started_at = time.perf_counter()
        response = None
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=effective_timeout_seconds,
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
                runtime_config.model_type,
                int((time.perf_counter() - started_at) * 1000),
            )
        except requests.Timeout as exc:
            logger.warning(
                "LLM流式调用超时: provider=%s model=%s model_type=%s timeout_seconds=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                runtime_config.model_type,
                effective_timeout_seconds,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise AppException("LLM接口响应超时，请稍后重试", status_code=504, code=504) from exc
        except requests.RequestException as exc:
            logger.exception(
                "LLM流式调用失败: provider=%s model=%s model_type=%s elapsed_ms=%s",
                runtime_config.provider,
                runtime_config.model_name,
                runtime_config.model_type,
                int((time.perf_counter() - started_at) * 1000),
            )
            raise AppException("LLM真实接口调用失败，请检查模型服务配置或稍后重试", status_code=502, code=502) from exc
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
            runtime_config,
            [{"role": "user", "content": "请回复：连接正常"}],
            temperature=0,
            apply_task_options=False,
        )
        try:
            response = requests.post(
                url,
                headers=headers,
                json=payload,
                timeout=self._resolve_timeout_seconds(runtime_config.model_type),
            )
            response.raise_for_status()
            data = response.json()
            return self._flatten_message_content(data["choices"][0]["message"]["content"]).strip()
        except (requests.RequestException, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.exception("LLM配置测试失败: provider=%s model=%s", runtime_config.provider, runtime_config.model_name)
            raise AppException(f"LLM配置测试失败: {exc}", status_code=502, code=502) from exc

    def _runtime_config(self, model_type: str, config: ModelConfig | None = None) -> RuntimeModelConfig:
        """解析运行时模型配置。"""

        model_config = config or self.model_repository.get_default(model_type)
        source = "explicit" if config is not None else ("database" if model_config is not None else "env_fallback")
        if model_type in VISION_MODEL_TYPES:
            provider = (model_config.provider if model_config else self.settings.vision_llm_provider).strip()
            model_name = (model_config.model_name if model_config else self.settings.vision_llm_model).strip()
            api_base = (model_config.api_base if model_config else None) or self.settings.vision_llm_base_url
            api_key = (model_config.api_key if model_config else None) or self.settings.vision_llm_api_key
            missing_model_message = "未配置 VISION_LLM_MODEL 或默认视觉模型名称"
            missing_base_message = "未配置 VISION_LLM_BASE_URL 或默认 vision_llm API Base"
        else:
            provider = (model_config.provider if model_config else self.settings.llm_provider).strip()
            model_name = (model_config.model_name if model_config else self._default_text_model_name(model_type)).strip()
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
        return RuntimeModelConfig(
            provider=provider,
            model_name=model_name,
            api_base=api_base,
            api_key=api_key,
            model_type=model_type,
            source=source,
        )

    def _default_text_model_name(self, model_type: str) -> str:
        """按任务模型类型获取环境变量兜底模型名。"""

        field_name = TEXT_MODEL_DEFAULT_FIELDS.get(model_type, "llm_model")
        return str(getattr(self.settings, field_name, self.settings.llm_model) or "")

    def model_route(self, task: str, reason: str) -> dict[str, Any]:
        """返回最近一次 LLM 调用的模型路由信息，用于写入 LangGraph trace。"""

        runtime_config = self.last_runtime_config
        if runtime_config is None:
            return {
                "task": task,
                "source": "not_called",
                "reason": reason,
            }
        return {
            "task": task,
            "model_type": runtime_config.model_type,
            "model_name": runtime_config.model_name,
            "provider": runtime_config.provider,
            "source": runtime_config.source,
            "timeout_seconds": self.last_timeout_seconds,
            "reason": reason,
        }

    def _resolve_timeout_seconds(self, model_type: str, timeout_seconds: int | None = None) -> int:
        """解析任务级超时；证据判断属于主链路前置短任务，必须受硬上限保护。"""

        if timeout_seconds is None:
            field_name = TASK_TIMEOUT_FIELDS.get(model_type, "llm_timeout_seconds")
            default_timeout = getattr(self.settings, "llm_timeout_seconds", 60)
            configured_timeout = getattr(self.settings, field_name, default_timeout)
        else:
            configured_timeout = timeout_seconds

        try:
            resolved_timeout = int(configured_timeout)
        except (TypeError, ValueError):
            resolved_timeout = int(getattr(self.settings, "llm_timeout_seconds", 60))

        resolved_timeout = max(MIN_TIMEOUT_SECONDS, resolved_timeout)
        if model_type in SHORT_CHAIN_MODEL_TYPES and resolved_timeout > SHORT_CHAIN_TIMEOUT_MAX_SECONDS:
            logger.warning(
                "短链路LLM超时配置超过上限，已截断: model_type=%s configured_seconds=%s effective_seconds=%s",
                model_type,
                resolved_timeout,
                SHORT_CHAIN_TIMEOUT_MAX_SECONDS,
            )
            return SHORT_CHAIN_TIMEOUT_MAX_SECONDS
        return resolved_timeout

    def _build_headers(self, runtime_config: RuntimeModelConfig) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if runtime_config.api_key:
            headers["Authorization"] = f"Bearer {runtime_config.api_key}"
        return headers

    def _build_chat_payload(
        self,
        runtime_config: RuntimeModelConfig,
        messages: list[dict[str, Any]],
        *,
        temperature: float = 0.2,
        stream: bool = False,
        max_tokens: int | None = None,
        apply_task_options: bool = True,
        disable_thinking: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": runtime_config.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if stream:
            payload["stream"] = True
        if max_tokens is not None and max_tokens > 0:
            payload["max_completion_tokens" if self._is_dashscope_qwen_runtime(runtime_config) else "max_tokens"] = max_tokens
        if apply_task_options:
            self._apply_task_payload_options(runtime_config, payload)
        if disable_thinking and self._is_dashscope_qwen_runtime(runtime_config):
            payload["enable_thinking"] = False
        return payload

    def _apply_task_payload_options(self, runtime_config: RuntimeModelConfig, payload: dict[str, Any]) -> None:
        """为短链路任务开启真实可调用的结构化、非思考模式。"""

        if not self._is_dashscope_qwen_runtime(runtime_config):
            return

        model_type = runtime_config.model_type
        if model_type in NON_THINKING_MODEL_TYPES:
            payload["enable_thinking"] = False
        if model_type in STRUCTURED_JSON_MODEL_TYPES:
            payload["response_format"] = {"type": "json_object"}

    def _is_dashscope_qwen_runtime(self, runtime_config: RuntimeModelConfig) -> bool:
        """判断当前运行时是否为 DashScope/OpenAI-compatible Qwen 调用。"""

        provider = runtime_config.provider.lower()
        api_base = runtime_config.api_base.lower()
        model_name = runtime_config.model_name.lower()
        return model_name.startswith("qwen") and (
            "qwen" in provider or "dashscope" in provider or "dashscope" in api_base
        )

    def _build_text_messages(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        prompt = self._build_rag_prompt(question, evidences, query_profile)
        return [
            {
                "role": "system",
                "content": ANSWER_SYSTEM_PROMPT,
            },
            {"role": "user", "content": prompt},
        ]

    def _build_multimodal_messages(
        self,
        question: str,
        evidences: list[Evidence],
        image_parts: list[dict[str, Any]],
        query_profile: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        prompt = "\n\n".join(
            [
                self._build_rag_prompt(question, evidences, query_profile),
                (
                    "图片证据已随本次消息提供。请结合图片中的设备、管线、箭头和仪表标识回答流程问题。"
                    "如果图片或文字证据都无法确认某个细节，请明确说明无法确认。"
                ),
            ]
        )
        return [
            {
                "role": "system",
                "content": VISION_ANSWER_SYSTEM_PROMPT,
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

    def _build_rag_prompt(
        self,
        question: str,
        evidences: list[Evidence],
        query_profile: dict[str, Any] | None = None,
    ) -> str:
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
                            f"source_type={evidence.source_type}, project_id={evidence.project_id or '-'}, "
                            f"knowledge_base_id={evidence.knowledge_base_id}, document_id={evidence.document_id}, "
                            f"drawing_no={evidence.drawing_no or '-'}, page_no={evidence.page_number or '-'}, "
                            f"chunk_id={evidence.chunk_id}"
                        ),
                        f"visual_assets={asset_summary}" if asset_summary else "visual_assets=-",
                        content,
                    ]
                )
            )
        safe_profile = self._safe_query_profile(query_profile)
        return "\n\n".join(
            [
                f"问题：{question}",
                f"查询画像：{json.dumps(safe_profile, ensure_ascii=False)}",
                f"证据使用边界：\n{answer_scope_instruction(safe_profile)}",
                f"回答结构要求：\n{answer_instruction_for_profile(safe_profile)}",
                "资料：",
                "\n\n".join(evidence_lines),
                "请严格基于资料直接回答，并在关键结论后标注来源编号，例如 [1]；资料无法确认的内容不要补写。",
            ]
        )

    def _safe_query_profile(self, query_profile: dict[str, Any] | None) -> dict[str, Any]:
        """裁剪传入模型的查询画像，避免无关长字段污染 prompt。"""

        profile = query_profile or {}
        return {
            "query_type": profile.get("query_type") or "unknown",
            "answer_shape": profile.get("answer_shape") or "general",
            "need_page_location": bool(profile.get("need_page_location")),
            "need_exact_term": bool(profile.get("need_exact_term")),
            "need_visual_asset": bool(profile.get("need_visual_asset")),
            "need_graph_reasoning": bool(profile.get("need_graph_reasoning")),
            "knowledge_scope": str(profile.get("knowledge_scope") or "none"),
            "is_industry_domain": bool(profile.get("is_industry_domain")),
            "industry_domains": list(profile.get("industry_domains") or [])[:8],
            "entities": list(profile.get("entities") or [])[:12],
            "keywords": list(profile.get("keywords") or [])[:16],
            "reason": str(profile.get("reason") or "")[:240],
        }

    def _answer_without_evidence(
        self,
        question: str,
        model_type: str,
        query_profile: dict[str, Any] | None,
    ) -> str:
        """无检索证据时按知识范围选择回答策略。"""

        if self._should_use_industry_general_knowledge(query_profile):
            return self._answer_industry_from_general_knowledge(question, model_type)
        return NO_EVIDENCE_ANSWER

    def _stream_answer_without_evidence(
        self,
        question: str,
        model_type: str,
        query_profile: dict[str, Any] | None,
    ) -> Iterator[str]:
        """无检索证据时按知识范围流式回答。"""

        if not self._should_use_industry_general_knowledge(query_profile):
            yield NO_EVIDENCE_ANSWER
            return
        yield from self._stream_industry_from_general_knowledge(question, model_type)

    def _should_use_industry_general_knowledge(self, query_profile: dict[str, Any] | None) -> bool:
        """判断行业基础知识问答在无证据时是否允许使用模型通用知识兜底。"""

        profile = query_profile or {}
        return str(profile.get("knowledge_scope") or "") == "industry"

    def _answer_industry_from_general_knowledge(self, question: str, model_type: str) -> str:
        """行业知识库无命中时，使用模型通用知识回答并追加声明。"""

        try:
            answer = self.chat(
                self._build_industry_general_knowledge_messages(question),
                model_type=model_type,
                max_tokens=1000,
                disable_thinking=True,
            )
            if not str(answer or "").strip():
                logger.warning("行业知识库无证据时同步通用知识回答为空，使用更直接的 prompt 重试")
                answer = self.chat(
                    self._build_industry_general_knowledge_retry_messages(question),
                    model_type=model_type,
                    max_tokens=800,
                    disable_thinking=True,
                )
            return self._append_industry_general_knowledge_notice(answer)
        except Exception as exc:  # noqa: BLE001
            logger.warning("行业知识库无证据时通用知识回答失败: error=%s", exc)
            return f"当前行业知识库资料不足，且通用回答模型暂不可用，无法生成模型通用知识回答。\n\n{INDUSTRY_GENERAL_KNOWLEDGE_NOTICE}"

    def _stream_industry_from_general_knowledge(self, question: str, model_type: str) -> Iterator[str]:
        """行业知识库无命中时，流式使用模型通用知识回答并追加声明。"""

        try:
            emitted_content = False
            for chunk in self.stream_chat(
                self._build_industry_general_knowledge_messages(question),
                model_type=model_type,
                max_tokens=1000,
                disable_thinking=True,
            ):
                if not chunk or not chunk.strip():
                    continue
                emitted_content = True
                yield chunk
            if emitted_content:
                yield f"\n\n{INDUSTRY_GENERAL_KNOWLEDGE_NOTICE}"
                return

            logger.warning("行业知识库无证据时流式回答未返回正文，改用同步回答模型兜底")
            yield self._answer_industry_from_general_knowledge(question, model_type)
        except Exception as exc:  # noqa: BLE001
            logger.warning("行业知识库无证据时流式通用知识回答失败: error=%s", exc)
            yield f"当前行业知识库资料不足，且通用回答模型暂不可用，无法生成模型通用知识回答。\n\n{INDUSTRY_GENERAL_KNOWLEDGE_NOTICE}"

    def _build_industry_general_knowledge_messages(self, question: str) -> list[dict[str, str]]:
        """构建行业知识库无证据时的通用知识回答 prompt。"""

        return [
            {
                "role": "system",
                "content": (
                    "你是电池回收、湿法冶金、工艺设计、图纸识读、设备、公辅与安全环保方向的行业知识助手。"
                    "当前没有检索到可引用的行业基础知识库资料，请仅基于模型通用知识直接回答用户问题。"
                    "重要：必须给出实质性回答，不要只声明无法基于资料回答。"
                    "回答应先给出简明结论，再说明关键区别、原理或适用场景。"
                    "不得编造来源编号、文件名、页码、项目参数或项目结论；不要使用“根据资料”“根据知识库”等表述。"
                    "如果问题涉及具体项目参数、图纸或设备配置，必须说明需要项目资料确认。"
                ),
            },
            {"role": "user", "content": question},
        ]

    def _build_industry_general_knowledge_retry_messages(self, question: str) -> list[dict[str, str]]:
        """构建行业通用知识兜底的二次直接回答 prompt。"""

        return [
            {
                "role": "system",
                "content": (
                    "直接回答用户的行业基础知识问题。不要提知识库无资料，不要拒答，不要输出来源编号。"
                    "用模型通用知识给出可读、简明、可执行的解释。"
                ),
            },
            {"role": "user", "content": f"请直接回答：{question}"},
        ]

    def _append_industry_general_knowledge_notice(self, answer: str) -> str:
        """确保模型通用知识兜底答案末尾带有固定声明。"""

        text = str(answer or "").strip()
        if INDUSTRY_GENERAL_KNOWLEDGE_NOTICE in text:
            return text
        if not text:
            text = "模型未返回有效正文，无法生成模型通用知识回答。"
        return f"{text}\n\n{INDUSTRY_GENERAL_KNOWLEDGE_NOTICE}"
