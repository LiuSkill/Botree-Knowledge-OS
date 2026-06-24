"""BEIR metric evaluation wrappers."""

from __future__ import annotations

from typing import Any

from eval.beir.types import BeirQrels, BeirResults


def evaluate_beir_results(qrels: BeirQrels, results: BeirResults, k_values: list[int]) -> dict[str, Any]:
    """Evaluate results with BEIR EvaluateRetrieval."""

    try:
        from beir.retrieval.evaluation import EvaluateRetrieval
    except ImportError as exc:
        raise RuntimeError("缺少 beir 依赖，无法使用 EvaluateRetrieval 计算指标") from exc

    evaluator = EvaluateRetrieval()
    ndcg, mean_average_precision, recall, precision = evaluator.evaluate(qrels, results, k_values)
    mrr = evaluator.evaluate_custom(qrels, results, k_values, metric="mrr")
    return {
        "NDCG": ndcg,
        "MAP": mean_average_precision,
        "Recall": recall,
        "Precision": precision,
        "MRR": mrr,
        "flat": _flatten_metric_groups(
            {
                "NDCG": ndcg,
                "MAP": mean_average_precision,
                "Recall": recall,
                "Precision": precision,
                "MRR": mrr,
            }
        ),
    }


def _flatten_metric_groups(metric_groups: dict[str, dict[str, float]]) -> dict[str, float]:
    """Flatten BEIR metric groups into a single JSON-friendly mapping."""

    flat: dict[str, float] = {}
    for _, metrics in metric_groups.items():
        for key, value in metrics.items():
            flat[key] = float(value)
    return flat
