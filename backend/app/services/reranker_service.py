"""
Reranker Service

负责对多路检索证据做统一重排。优先使用模型配置中的真实本地 CrossEncoder
reranker；在允许降级的场景下，保留确定性规则排序作为 fallback。
"""

from __future__ import annotations

import copy
import logging
import threading
import time
from dataclasses import dataclass

import requests
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import AppException
from app.models.model_config import ModelConfig
from app.repositories.model_repository import ModelConfigRepository
from app.retrieval.query_utils import (
    boilerplate_multiplier,
    contains_search_token,
    extract_query_terms,
    normalize_query_text,
    score_text_relevance,
)
from app.retrieval.schemas import Evidence

logger = logging.getLogger(__name__)

LOCAL_RERANKER_PROVIDERS = {"local", "local_reranker", "bge_local", "qwen_local"}
MODEL_SERVICE_RERANKER_PROVIDERS = {"model_service"}


@dataclass(frozen=True)
class RuntimeRerankerConfig:
    """运行时 Reranker 配置。"""

    provider: str
    model_name: str
    api_base: str | None
    api_key: str | None


class RerankerService:
    """
    证据重排服务。

    业务规则：
        - 在线问答传入 require_real_model=True 时必须使用真实 reranker；
        - allow_fallback=False 时真实模型失败会抛出业务异常；
        - 老链路或测试未显式要求真实模型时，可以使用确定性 fallback。
    """

    def __init__(self, db: Session | None) -> None:
        self.db = db
        self.settings = get_settings()
        self.model_repository = ModelConfigRepository(db) if db is not None else None
        self.last_details: list[dict] = []
        self.last_runtime: dict = {}

    def rerank(
        self,
        query: str,
        evidences: list[Evidence],
        limit: int = 5,
        *,
        require_real_model: bool = False,
        allow_fallback: bool = True,
        score_order: str = "desc",
    ) -> list[Evidence]:
        """对证据进行重排并返回 TopN。"""

        if not evidences:
            self.last_details = []
            self.last_runtime = {"model_loaded": False, "fallback_used": False, "candidate_count": 0}
            return []

        normalized_score_order = self._normalize_score_order(score_order)
        if require_real_model or self._has_default_real_model():
            try:
                return self._rerank_with_real_model_with_timeout(query, evidences, limit, normalized_score_order)
            except Exception as exc:
                failure_runtime = dict(self.last_runtime)
                if require_real_model and not allow_fallback:
                    logger.exception("真实Reranker调用失败且禁止fallback: candidate_count=%s", len(evidences))
                    if isinstance(exc, AppException):
                        raise
                    raise AppException(f"真实Reranker调用失败：{exc}", status_code=502, code=502) from exc
                logger.warning(
                    "真实Reranker不可用，使用确定性fallback: require_real_model=%s allow_fallback=%s error=%s",
                    require_real_model,
                    allow_fallback,
                    exc,
                    exc_info=True,
                )
                reranked = self._rerank_with_fallback(
                    query,
                    evidences,
                    limit,
                    normalized_score_order,
                    fallback_used=True,
                )
                if failure_runtime:
                    self.last_runtime["real_model_runtime"] = failure_runtime
                self.last_runtime["real_model_error"] = str(exc)
                return reranked

        return self._rerank_with_fallback(query, evidences, limit, normalized_score_order, fallback_used=True)

    def _rerank_with_real_model_with_timeout(
        self,
        query: str,
        evidences: list[Evidence],
        limit: int,
        score_order: str,
    ) -> list[Evidence]:
        timeout_seconds = float(getattr(self.settings, "reranker_timeout_seconds", 15) or 15)
        if timeout_seconds <= 0:
            return self._rerank_with_real_model(query, evidences, limit, score_order)

        total_started_at = time.perf_counter()
        gate_context = self._try_acquire_local_inference_slot(timeout_seconds, len(evidences), score_order)
        queue_wait_ms = int(gate_context["queue_wait_ms"]) if gate_context else 0
        prepare_elapsed_ms = int(gate_context["prepare_elapsed_ms"]) if gate_context else 0
        wait_budget_seconds = max(0.0, timeout_seconds - prepare_elapsed_ms / 1000.0)
        if gate_context is not None and wait_budget_seconds <= 0:
            gate_context["model"].release_inference_slot()
            self._record_real_model_timeout_runtime(
                gate_context=gate_context,
                candidate_count=len(evidences),
                score_order=score_order,
                queue_wait_ms=queue_wait_ms,
                prepare_elapsed_ms=prepare_elapsed_ms,
                timeout_seconds=timeout_seconds,
                timeout_stage="prepare",
                total_elapsed_ms=prepare_elapsed_ms,
            )
            raise TimeoutError(f"real_reranker_timeout>{timeout_seconds}s")
        worker_evidences = copy.deepcopy(evidences)
        result_holder: dict[str, list[Evidence]] = {}
        error_holder: dict[str, BaseException] = {}
        completed = threading.Event()

        def run_real_rerank() -> None:
            try:
                result_holder["value"] = self._rerank_with_real_model(query, worker_evidences, limit, score_order)
            except BaseException as exc:  # noqa: BLE001
                error_holder["error"] = exc
            finally:
                if gate_context is not None:
                    gate_context["model"].release_inference_slot()
                completed.set()

        worker = threading.Thread(target=run_real_rerank, name="reranker-real-model", daemon=True)
        try:
            worker.start()
        except Exception:
            if gate_context is not None:
                gate_context["model"].release_inference_slot()
            raise
        if not completed.wait(wait_budget_seconds if gate_context is not None else timeout_seconds):
            self._record_real_model_timeout_runtime(
                gate_context=gate_context,
                candidate_count=len(evidences),
                score_order=score_order,
                queue_wait_ms=queue_wait_ms,
                prepare_elapsed_ms=prepare_elapsed_ms,
                timeout_seconds=timeout_seconds,
                timeout_stage="inference",
                total_elapsed_ms=int((time.perf_counter() - total_started_at) * 1000),
            )
            raise TimeoutError(f"real_reranker_timeout>{timeout_seconds}s")
        if "error" in error_holder:
            raise error_holder["error"]
        self._attach_timeout_metrics(
            queue_wait_ms,
            prepare_elapsed_ms,
            int((time.perf_counter() - total_started_at) * 1000),
        )
        return result_holder["value"]

    def ensure_real_model(self) -> RuntimeRerankerConfig:
        """校验并加载默认真实 Reranker 模型。"""

        runtime_config = self._runtime_config()
        if self._is_model_service_reranker(runtime_config):
            self._ensure_model_service_available(runtime_config)
            return runtime_config
        if not self._is_local_reranker(runtime_config):
            raise AppException(
                f"当前Reranker provider={runtime_config.provider} 暂未接入本地预热",
                status_code=500,
                code=500,
            )
        self._get_local_model(runtime_config)
        return runtime_config

    def test_reranker(self, config: ModelConfig) -> dict:
        """测试指定 Reranker 配置。"""

        runtime_config = self._runtime_config(config)
        try:
            if self._is_model_service_reranker(runtime_config):
                response_data = self._request_model_service_rerank("连接测试", ["连接测试文档"], runtime_config)
                results = response_data.get("results") or []
                score = float(results[0]["score"]) if results else None
                return {
                    "status": "success",
                    "provider": runtime_config.provider,
                    "model": runtime_config.model_name,
                    "backend": response_data.get("backend") or "model_service",
                    "score": score,
                }
            if self._is_local_reranker(runtime_config):
                model = self._get_local_model(runtime_config)
                scores = model.predict("连接测试", ["连接测试文档"])
                return {
                    "status": "success",
                    "provider": runtime_config.provider,
                    "model": runtime_config.model_name,
                    "backend": model.backend_name,
                    "device": model.device,
                    "score": scores[0] if scores else None,
                }
            raise AppException(f"当前Reranker provider={runtime_config.provider} 暂未实现连接测试", status_code=500, code=500)
        except AppException:
            raise
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            logger.exception("Reranker配置测试失败: provider=%s model=%s", runtime_config.provider, runtime_config.model_name)
            raise AppException(f"Reranker配置测试失败：{exc}", status_code=502, code=502) from exc

    def warmup_local_reranker(self) -> None:
        """启动时预热本地 Reranker 模型。"""

        runtime_config = self._runtime_config()
        if not self._is_local_reranker(runtime_config):
            return

        from app.services.reranker_local import is_local_reranker_loaded

        loaded_before = is_local_reranker_loaded(
            runtime_config.model_name,
            self.settings.reranker_device,
            self.settings.reranker_batch_size,
        )
        requested_device = self._requested_reranker_device()
        device_explicitly_configured = self._reranker_device_explicitly_configured()
        if not device_explicitly_configured:
            logger.warning(
                "RERANKER_DEVICE 未显式配置，当前按默认值预热本地Reranker: requested_device=%s provider=%s model=%s。"
                "如需GPU，请在 backend/.env 或进程环境中设置 RERANKER_DEVICE=cuda 并重启服务。",
                requested_device,
                runtime_config.provider,
                runtime_config.model_name,
            )
        logger.info(
            "本地Reranker预热开始: loaded=%s provider=%s model=%s requested_device=%s batch_size=%s explicit_device=%s",
            loaded_before,
            runtime_config.provider,
            runtime_config.model_name,
            requested_device,
            self.settings.reranker_batch_size,
            device_explicitly_configured,
        )
        started_at = time.perf_counter()
        model = self._get_local_model(runtime_config)
        scores = model.predict("reranker warmup", ["reranker warmup document"])
        self.last_runtime = {
            "provider": runtime_config.provider,
            "model_name": runtime_config.model_name,
            "model_loaded": model.is_loaded,
            "backend": model.backend_name,
            "requested_device": requested_device,
            "resolved_device": model.device,
            "device": model.device,
            "device_explicitly_configured": device_explicitly_configured,
            "batch_size": model.batch_size,
            "fallback_used": False,
            "warmup_score": scores[0] if scores else None,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
        logger.info(
            "本地Reranker预热完成: loaded=%s provider=%s model=%s backend=%s requested_device=%s resolved_device=%s elapsed_ms=%s",
            model.is_loaded,
            runtime_config.provider,
            runtime_config.model_name,
            model.backend_name,
            requested_device,
            model.device,
            self.last_runtime["elapsed_ms"],
        )

    def _rerank_with_real_model(
        self,
        query: str,
        evidences: list[Evidence],
        limit: int,
        score_order: str,
    ) -> list[Evidence]:
        runtime_config = self._runtime_config()
        requested_device = self._requested_reranker_device()
        device_explicitly_configured = self._reranker_device_explicitly_configured()
        if self._is_model_service_reranker(runtime_config):
            return self._rerank_with_model_service(query, evidences, limit, score_order, runtime_config)
        if not self._is_local_reranker(runtime_config):
            raise AppException(
                f"当前Reranker provider={runtime_config.provider} 暂未实现真实重排调用",
                status_code=500,
                code=500,
            )
        model = self._get_local_model(runtime_config)
        started_at = time.perf_counter()
        scores = model.predict(query, [evidence.content or "" for evidence in evidences])
        if len(scores) != len(evidences):
            raise ValueError(f"Reranker返回数量不匹配: expected={len(evidences)} actual={len(scores)}")

        scored: list[tuple[float, Evidence, dict]] = []
        for evidence, score in zip(evidences, scores, strict=True):
            raw_score = evidence.score
            evidence.metadata = {
                **evidence.metadata,
                "rerank_score": score,
                "rerank_raw_score": raw_score,
                "rerank_backend": model.backend_name,
                "rerank_model": runtime_config.model_name,
                "rerank_requested_device": requested_device,
                "rerank_resolved_device": model.device,
            }
            evidence.score = score
            scored.append(
                (
                    score,
                    evidence,
                    {
                        "retriever": evidence.retriever,
                        "document_id": evidence.document_id,
                        "chunk_id": evidence.chunk_id,
                        "page_number": evidence.page_number,
                        "raw_score": raw_score,
                        "score": score,
                        "backend": model.backend_name,
                        "model_name": runtime_config.model_name,
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=score_order == "desc")
        self.last_details = [item[2] for item in scored[:limit]]
        self.last_runtime = {
            "provider": runtime_config.provider,
            "model_name": runtime_config.model_name,
            "model_loaded": model.is_loaded,
            "backend": model.backend_name,
            "requested_device": requested_device,
            "resolved_device": model.device,
            "device": model.device,
            "device_explicitly_configured": device_explicitly_configured,
            "batch_size": model.batch_size,
            "fallback_used": False,
            "score_order": score_order,
            "candidate_count": len(evidences),
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
        return [item[1] for item in scored[:limit]]

    def _rerank_with_model_service(
        self,
        query: str,
        evidences: list[Evidence],
        limit: int,
        score_order: str,
        runtime_config: RuntimeRerankerConfig,
    ) -> list[Evidence]:
        """调用独立模型服务执行真实重排。"""

        if not runtime_config.api_base:
            raise AppException("Reranker API Base为空，无法调用模型服务", status_code=500, code=500)

        started_at = time.perf_counter()
        documents = [evidence.content or "" for evidence in evidences]
        response_data = self._request_model_service_rerank(query, documents, runtime_config)
        results = response_data.get("results")
        if not isinstance(results, list):
            raise ValueError("Reranker模型服务响应缺少results")

        scores_by_index: dict[int, float] = {}
        for item in results:
            if not isinstance(item, dict):
                raise ValueError("Reranker模型服务results格式错误")
            index = int(item["index"])
            scores_by_index[index] = float(item["score"])
        if len(scores_by_index) != len(evidences):
            raise ValueError(f"Reranker返回数量不匹配: expected={len(evidences)} actual={len(scores_by_index)}")

        backend = str(response_data.get("backend") or "model_service")
        resolved_device = str(response_data.get("device") or "remote")
        scored: list[tuple[float, Evidence, dict]] = []
        for index, evidence in enumerate(evidences):
            if index not in scores_by_index:
                raise ValueError(f"Reranker模型服务缺少候选分数: index={index}")
            score = scores_by_index[index]
            raw_score = evidence.score
            evidence.metadata = {
                **evidence.metadata,
                "rerank_score": score,
                "rerank_raw_score": raw_score,
                "rerank_backend": backend,
                "rerank_model": runtime_config.model_name,
                "rerank_requested_device": "remote",
                "rerank_resolved_device": resolved_device,
            }
            evidence.score = score
            scored.append(
                (
                    score,
                    evidence,
                    {
                        "retriever": evidence.retriever,
                        "document_id": evidence.document_id,
                        "chunk_id": evidence.chunk_id,
                        "page_number": evidence.page_number,
                        "raw_score": raw_score,
                        "score": score,
                        "backend": backend,
                        "model_name": runtime_config.model_name,
                    },
                )
            )

        scored.sort(key=lambda item: item[0], reverse=score_order == "desc")
        self.last_details = [item[2] for item in scored[:limit]]
        self.last_runtime = {
            "provider": runtime_config.provider,
            "model_name": runtime_config.model_name,
            "model_loaded": True,
            "backend": backend,
            "requested_device": "remote",
            "resolved_device": resolved_device,
            "device": resolved_device,
            "device_explicitly_configured": True,
            "fallback_used": False,
            "score_order": score_order,
            "candidate_count": len(evidences),
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
        return [item[1] for item in scored[:limit]]

    def _request_model_service_rerank(
        self,
        query: str,
        documents: list[str],
        runtime_config: RuntimeRerankerConfig,
    ) -> dict:
        """发送 Reranker 模型服务请求并返回 JSON 响应。"""

        url = f"{runtime_config.api_base.rstrip('/')}/rerank"
        headers = {"Content-Type": "application/json"}
        if runtime_config.api_key:
            headers["Authorization"] = f"Bearer {runtime_config.api_key}"
        payload = {"model": runtime_config.model_name, "query": query, "documents": documents}
        timeout_seconds = float(getattr(self.settings, "reranker_timeout_seconds", 15) or 15)
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds if timeout_seconds > 0 else None)
        response.raise_for_status()
        return response.json()

    def _rerank_with_fallback(
        self,
        query: str,
        evidences: list[Evidence],
        limit: int,
        score_order: str,
        *,
        fallback_used: bool,
    ) -> list[Evidence]:
        terms = self._terms(query)
        scored: list[tuple[float, Evidence, dict]] = []
        for evidence in evidences:
            exact_bonus = self._exact_bonus(evidence.content, query, terms)
            source_bonus = self._source_bonus(evidence.retriever)
            relevance_bonus = score_text_relevance(evidence.content, query, terms) * 0.3
            quality_multiplier = boilerplate_multiplier(evidence.content)
            raw_score = evidence.score
            final_score = (raw_score + exact_bonus + source_bonus + relevance_bonus) * quality_multiplier
            evidence.metadata = {
                **evidence.metadata,
                "rerank_score": final_score,
                "rerank_raw_score": raw_score,
                "rerank_exact_bonus": exact_bonus,
                "rerank_source_bonus": source_bonus,
                "rerank_relevance_bonus": relevance_bonus,
                "rerank_quality_multiplier": quality_multiplier,
                "rerank_backend": "deterministic",
            }
            evidence.score = final_score
            scored.append(
                (
                    final_score,
                    evidence,
                    {
                        "retriever": evidence.retriever,
                        "document_id": evidence.document_id,
                        "chunk_id": evidence.chunk_id,
                        "page_number": evidence.page_number,
                        "raw_score": raw_score,
                        "score": final_score,
                        "quality_multiplier": quality_multiplier,
                        "backend": "deterministic",
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=score_order == "desc")
        self.last_details = [item[2] for item in scored[:limit]]
        self.last_runtime = {
            "provider": "deterministic",
            "model_name": "deterministic_fallback",
            "model_loaded": False,
            "backend": "deterministic",
            "fallback_used": fallback_used,
            "score_order": score_order,
            "candidate_count": len(evidences),
        }
        return [item[1] for item in scored[:limit]]

    def _terms(self, query: str) -> list[str]:
        """抽取重排关键词。"""

        return extract_query_terms(query)

    def _exact_bonus(self, content: str, query: str, terms: list[str]) -> float:
        """计算精确命中奖励分。"""

        text = normalize_query_text(content).lower()
        bonus = 0.0
        if query and normalize_query_text(query).lower() in text:
            bonus += 5.0
        for term in terms:
            if term and contains_search_token(text, term):
                bonus += 0.8
        return bonus

    def _source_bonus(self, retriever: str) -> float:
        """根据召回来源给出稳定优先级。"""

        return {
            "ripgrep": 1.5,
            "page_index": 1.3,
            "graphrag": 0.9,
            "milvus": 0.6,
            "keyword": 0.2,
        }.get(retriever, 0.0)

    def _try_acquire_local_inference_slot(
        self,
        timeout_seconds: float,
        candidate_count: int,
        score_order: str,
    ) -> dict | None:
        started_at = time.perf_counter()
        try:
            runtime_config = self._runtime_config()
        except Exception:
            return None
        if not self._is_local_reranker(runtime_config):
            return None

        model = self._get_local_model(runtime_config)
        acquire_slot = getattr(model, "acquire_inference_slot", None)
        if not callable(acquire_slot):
            return None

        queue_wait_ms = acquire_slot(timeout_seconds)
        requested_device = self._requested_reranker_device()
        device_explicitly_configured = self._reranker_device_explicitly_configured()
        if queue_wait_ms is None:
            prepare_elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            self._record_real_model_timeout_runtime(
                gate_context={
                    "runtime_config": runtime_config,
                    "model": model,
                    "requested_device": requested_device,
                    "device_explicitly_configured": device_explicitly_configured,
                },
                candidate_count=candidate_count,
                score_order=score_order,
                queue_wait_ms=int(timeout_seconds * 1000),
                prepare_elapsed_ms=prepare_elapsed_ms,
                timeout_seconds=timeout_seconds,
                timeout_stage="queue",
                total_elapsed_ms=prepare_elapsed_ms,
            )
            raise TimeoutError(f"real_reranker_queue_timeout>{timeout_seconds}s")

        return {
            "runtime_config": runtime_config,
            "model": model,
            "requested_device": requested_device,
            "device_explicitly_configured": device_explicitly_configured,
            "queue_wait_ms": queue_wait_ms,
            "prepare_elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }

    def _record_real_model_timeout_runtime(
        self,
        *,
        gate_context: dict | None,
        candidate_count: int,
        score_order: str,
        queue_wait_ms: int,
        prepare_elapsed_ms: int,
        timeout_seconds: float,
        timeout_stage: str,
        total_elapsed_ms: int,
    ) -> None:
        runtime = {
            "provider": "local" if gate_context is not None else "unknown",
            "model_name": None,
            "model_loaded": False,
            "backend": "timeout",
            "fallback_used": False,
            "score_order": score_order,
            "candidate_count": candidate_count,
            "timed_out": True,
            "timeout_stage": timeout_stage,
            "timeout_seconds": timeout_seconds,
            "queue_wait_ms": queue_wait_ms,
            "prepare_elapsed_ms": prepare_elapsed_ms,
            "total_elapsed_ms": total_elapsed_ms,
        }
        if gate_context is not None:
            runtime_config = gate_context["runtime_config"]
            model = gate_context["model"]
            runtime.update(
                {
                    "provider": runtime_config.provider,
                    "model_name": runtime_config.model_name,
                    "model_loaded": model.is_loaded,
                    "backend": model.backend_name,
                    "requested_device": gate_context["requested_device"],
                    "resolved_device": model.device,
                    "device": model.device,
                    "device_explicitly_configured": gate_context["device_explicitly_configured"],
                    "batch_size": model.batch_size,
                }
            )
        self.last_runtime = runtime

    def _attach_timeout_metrics(self, queue_wait_ms: int, prepare_elapsed_ms: int, total_elapsed_ms: int) -> None:
        if not self.last_runtime:
            return
        self.last_runtime["queue_wait_ms"] = queue_wait_ms
        self.last_runtime["prepare_elapsed_ms"] = prepare_elapsed_ms
        self.last_runtime["total_elapsed_ms"] = total_elapsed_ms

    def _runtime_config(self, config: ModelConfig | None = None) -> RuntimeRerankerConfig:
        if config is None:
            if self.model_repository is not None:
                config = self.model_repository.get_default("reranker")
            if config is None:
                return self._runtime_config_from_env()
        if config is None:
            raise AppException("未配置默认启用的Reranker模型", status_code=500, code=500)
        return RuntimeRerankerConfig(
            provider=config.provider,
            model_name=config.model_name,
            api_base=config.api_base,
            api_key=config.api_key,
        )

    def _runtime_config_from_env(self) -> RuntimeRerankerConfig:
        provider = str(getattr(self.settings, "reranker_provider", "") or "").strip()
        model_name = str(
            getattr(self.settings, "reranker_model", "")
            or getattr(self.settings, "model_service_reranker_model", "")
            or ""
        ).strip()
        if not provider or not model_name:
            raise AppException("未配置默认启用的Reranker模型", status_code=500, code=500)
        provider_key = provider.lower()
        api_base = str(getattr(self.settings, "reranker_api_base", "") or "").strip() or None
        api_key = str(getattr(self.settings, "reranker_api_key", "") or "").strip() or None
        if provider_key in MODEL_SERVICE_RERANKER_PROVIDERS:
            api_base = api_base or getattr(self.settings, "model_service_api_base", None)
            api_key = api_key or getattr(self.settings, "model_service_api_key", None)
        if provider_key not in LOCAL_RERANKER_PROVIDERS and not api_base:
            raise AppException("未配置 Reranker API Base", status_code=500, code=500)
        return RuntimeRerankerConfig(provider=provider, model_name=model_name, api_base=api_base, api_key=api_key)

    def _has_default_real_model(self) -> bool:
        if self.model_repository is None:
            return False
        try:
            return self.model_repository.get_default("reranker") is not None
        except Exception:
            logger.exception("查询默认Reranker配置失败")
            return False

    def _get_local_model(self, runtime_config: RuntimeRerankerConfig):
        try:
            from app.services.reranker_local import get_local_reranker

            return get_local_reranker(
                runtime_config.model_name,
                self.settings.reranker_device,
                self.settings.reranker_batch_size,
            )
        except ImportError as exc:
            logger.exception("本地Reranker依赖缺失: model=%s", runtime_config.model_name)
            raise AppException(
                "本地Reranker依赖缺失，请安装 sentence-transformers、transformers、torch 后重试",
                status_code=500,
                code=500,
            ) from exc
        except Exception as exc:
            logger.exception("本地Reranker加载或调用失败: model=%s", runtime_config.model_name)
            raise AppException(f"本地Reranker加载或调用失败：{exc}", status_code=502, code=502) from exc

    def _requested_reranker_device(self) -> str:
        return str(self.settings.reranker_device or "cpu").strip().lower() or "cpu"

    def _reranker_device_explicitly_configured(self) -> bool:
        return "reranker_device" in getattr(self.settings, "model_fields_set", set())

    def _is_local_reranker(self, runtime_config: RuntimeRerankerConfig) -> bool:
        return runtime_config.provider.lower() in LOCAL_RERANKER_PROVIDERS

    def _is_model_service_reranker(self, runtime_config: RuntimeRerankerConfig) -> bool:
        return runtime_config.provider.lower() in MODEL_SERVICE_RERANKER_PROVIDERS

    def _ensure_model_service_available(self, runtime_config: RuntimeRerankerConfig) -> None:
        if not runtime_config.api_base:
            raise AppException("Reranker API Base为空，无法检查模型服务", status_code=500, code=500)
        headers = {}
        if runtime_config.api_key:
            headers["Authorization"] = f"Bearer {runtime_config.api_key}"
        response = requests.get(
            f"{runtime_config.api_base.rstrip('/')}/health",
            headers=headers,
            timeout=float(getattr(self.settings, "reranker_timeout_seconds", 15) or 15),
        )
        response.raise_for_status()

    def _normalize_score_order(self, score_order: str) -> str:
        normalized = (score_order or "desc").lower().strip()
        return normalized if normalized in {"asc", "desc"} else "desc"
