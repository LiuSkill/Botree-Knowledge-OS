"""
Reranker Service

负责对多路检索证据做统一重排。优先使用模型配置中的真实本地 CrossEncoder
reranker；在允许降级的场景下，保留确定性规则排序作为 fallback。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

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
                return self._rerank_with_real_model(query, evidences, limit, normalized_score_order)
            except Exception as exc:
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

        return self._rerank_with_fallback(query, evidences, limit, normalized_score_order, fallback_used=True)

    def ensure_real_model(self) -> RuntimeRerankerConfig:
        """校验并加载默认真实 Reranker 模型。"""

        runtime_config = self._runtime_config()
        if not self._is_local_reranker(runtime_config):
            raise AppException(
                f"当前Reranker provider={runtime_config.provider} 暂未接入本地预热",
                status_code=500,
                code=500,
            )
        self._get_local_model(runtime_config)
        return runtime_config

    def warmup_local_reranker(self) -> None:
        """启动时预热本地 Reranker 模型。"""

        runtime_config = self._runtime_config()
        if not self._is_local_reranker(runtime_config):
            logger.info(
                "跳过本地Reranker预热: provider=%s model=%s is_local=%s",
                runtime_config.provider,
                runtime_config.model_name,
                False,
            )
            return

        from app.services.reranker_local import is_local_reranker_loaded

        loaded_before = is_local_reranker_loaded(
            runtime_config.model_name,
            self.settings.reranker_device,
            self.settings.reranker_batch_size,
        )
        logger.info(
            "本地Reranker预热开始: loaded=%s provider=%s model=%s device=%s batch_size=%s",
            loaded_before,
            runtime_config.provider,
            runtime_config.model_name,
            self.settings.reranker_device,
            self.settings.reranker_batch_size,
        )
        started_at = time.perf_counter()
        model = self._get_local_model(runtime_config)
        scores = model.predict("reranker warmup", ["reranker warmup document"])
        self.last_runtime = {
            "provider": runtime_config.provider,
            "model_name": runtime_config.model_name,
            "model_loaded": model.is_loaded,
            "backend": model.backend_name,
            "device": model.device,
            "batch_size": model.batch_size,
            "fallback_used": False,
            "warmup_score": scores[0] if scores else None,
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
        logger.info(
            "本地Reranker预热完成: loaded=%s provider=%s model=%s backend=%s device=%s elapsed_ms=%s",
            model.is_loaded,
            runtime_config.provider,
            runtime_config.model_name,
            model.backend_name,
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
            "device": model.device,
            "batch_size": model.batch_size,
            "fallback_used": False,
            "score_order": score_order,
            "candidate_count": len(evidences),
            "elapsed_ms": int((time.perf_counter() - started_at) * 1000),
        }
        return [item[1] for item in scored[:limit]]

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

    def _runtime_config(self, config: ModelConfig | None = None) -> RuntimeRerankerConfig:
        if config is None:
            if self.model_repository is None:
                raise AppException("Reranker模型配置不可用：数据库会话为空", status_code=500, code=500)
            config = self.model_repository.get_default("reranker")
        if config is None:
            raise AppException("未配置默认启用的Reranker模型", status_code=500, code=500)
        return RuntimeRerankerConfig(
            provider=config.provider,
            model_name=config.model_name,
            api_base=config.api_base,
            api_key=config.api_key,
        )

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

    def _is_local_reranker(self, runtime_config: RuntimeRerankerConfig) -> bool:
        return runtime_config.provider.lower() in LOCAL_RERANKER_PROVIDERS

    def _normalize_score_order(self, score_order: str) -> str:
        normalized = (score_order or "desc").lower().strip()
        return normalized if normalized in {"asc", "desc"} else "desc"
