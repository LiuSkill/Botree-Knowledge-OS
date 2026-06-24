"""Command line entrypoint for BEIR retrieval evaluation."""

from __future__ import annotations

import argparse
import logging
from datetime import datetime
from pathlib import Path

from eval.beir.bootstrap import WORKSPACE_ROOT
from eval.beir.logging_utils import setup_logging
from eval.beir.runner import BeirEvalConfig, BeirEvaluationRunner

logger = logging.getLogger(__name__)

RETRIEVER_CHOICES = [
    "bm25",
    "milvus",
    "keyword",
    "ripgrep",
    "pageindex",
    "graphrag",
    "hybrid",
    "rrf",
    "hybrid_reranker",
    "agentic_router",
    "full_rag",
]


def main() -> None:
    """Parse CLI arguments and run BEIR evaluation."""

    args = parse_args()
    output_dir = resolve_output_dir(args)
    log_path = setup_logging(output_dir, verbose=args.verbose)
    logger.info("BEIR evaluation logging initialized: log_path=%s", log_path)
    embedding_batch_size = args.embedding_batch_size or args.batch_size or 32
    max_queries = args.max_queries if args.max_queries is not None else args.limit_queries
    business_project_code = args.business_project_code or f"EVAL_BEIR_{args.dataset.upper()}"
    answer_top_k = args.final_top_k or args.answer_top_k
    config = BeirEvalConfig(
        dataset=args.dataset,
        retriever=args.retriever,
        retrievers=tuple(args.retrievers),
        mode=args.mode,
        fusion=args.fusion,
        weights=args.weights,
        top_k=args.top_k,
        candidate_k=args.candidate_k,
        rerank_top_k=args.rerank_top_k,
        eval_top_k=args.eval_top_k,
        answer_top_k=answer_top_k,
        final_top_k=args.final_top_k,
        retrieval_mode=args.retrieval_mode,
        require_real_reranker=args.require_real_reranker,
        allow_reranker_fallback=args.allow_reranker_fallback,
        rerank=args.rerank,
        collection_name=args.collection_name or f"beir_{args.dataset}_eval",
        data_dir=args.data_dir,
        reports_dir=output_dir,
        output_dir=output_dir,
        split=args.split,
        k_values=tuple(parse_k_values(args.k_values)),
        keyword_adapter=args.keyword_adapter,
        batch_size=embedding_batch_size,
        embedding_batch_size=embedding_batch_size,
        query_batch_size=args.query_batch_size,
        force_reindex=args.force_reindex,
        skip_index=args.skip_index,
        max_queries=max_queries,
        include_answer=args.include_answer,
        enable_online_answer=args.enable_online_answer,
        business_project_code=business_project_code,
        business_user_id=args.business_user_id,
        business_index_targets=tuple(args.business_index_targets),
        eval_mode=args.eval_mode,
        force_business_reindex=args.force_business_reindex,
        reranker_score_order=args.reranker_score_order,
        verbose=args.verbose,
    )
    try:
        BeirEvaluationRunner(config).run()
    except Exception:
        logger.exception("BEIR evaluation failed")
        raise


def parse_args() -> argparse.Namespace:
    """Build and parse CLI arguments."""

    parser = argparse.ArgumentParser(description="Evaluate Botree RAG retrieval on BEIR datasets.")
    parser.add_argument("--dataset", default="scifact", help="BEIR dataset name, default: scifact")
    parser.add_argument("--split", default="test", help="BEIR qrels split, default: test")
    parser.add_argument(
        "--mode",
        default="eval",
        choices=["info", "index", "business_index", "check_reranker", "eval", "full", "compare"],
        help="Evaluation workflow: info/index/business_index/check_reranker/eval/full/compare.",
    )
    parser.add_argument(
        "--retriever",
        default="milvus",
        choices=RETRIEVER_CHOICES,
        help="Single retrieval strategy. hybrid means Milvus + BM25 with fusion.",
    )
    parser.add_argument(
        "--retrievers",
        type=parse_retrievers,
        default=[],
        help="Comma-separated retriever combination, e.g. milvus,bm25,ripgrep. Overrides --retriever when set.",
    )
    parser.add_argument("--fusion", default="rrf", choices=["rrf", "weighted", "concat_dedupe"], help="Fusion method for multi-retriever runs.")
    parser.add_argument("--weights", type=parse_weights, default={}, help="Weights for weighted fusion, e.g. milvus=0.5,bm25=0.3")
    parser.add_argument("--top_k", type=positive_int, default=100, help="Final TopK written to BEIR results.")
    parser.add_argument("--candidate_k", type=positive_int, default=100, help="Per-retriever candidate TopK before fusion/rerank.")
    parser.add_argument("--rerank_top_k", type=positive_int, default=100, help="Fused candidate TopK sent to reranker.")
    parser.add_argument("--eval_top_k", type=positive_int, default=100, help="Maximum retrieved TopK retained for BEIR metrics.")
    parser.add_argument("--answer_top_k", type=positive_int, default=10, help="Final evidence count for answer LLM. Current real chain expects 10.")
    parser.add_argument("--final_top_k", type=positive_int, default=None, help="Deprecated alias for answer_top_k in older commands.")
    parser.add_argument(
        "--retrieval_mode",
        default="smart",
        choices=["fast", "smart", "full"],
        help="Real RAG retrieval mode. BEIR default: smart.",
    )
    parser.add_argument("--rerank", nargs="?", const=True, default=True, type=parse_bool, help="Rerank candidates, default: true.")
    parser.add_argument(
        "--require_real_reranker",
        nargs="?",
        const=True,
        default=True,
        type=parse_bool,
        help="Fail formal eval when no real reranker is configured, default: true.",
    )
    parser.add_argument(
        "--allow_reranker_fallback",
        nargs="?",
        const=True,
        default=False,
        type=parse_bool,
        help="Allow deterministic reranker fallback for debugging only, default: false.",
    )
    parser.add_argument(
        "--reranker_score_order",
        default="desc",
        choices=["desc", "asc"],
        help="Sort reranker scores by relevance order, default: desc.",
    )
    parser.add_argument("--collection_name", default=None, help="Milvus test collection name. Default: beir_{dataset}_eval")
    parser.add_argument("--k_values", default="1,3,5,10,50,100", help="Comma-separated metric K values.")
    parser.add_argument("--keyword_adapter", default="bm25", choices=["bm25", "ripgrep"], help="Keyword adapter for keyword/hybrid aliases.")
    parser.add_argument("--embedding_batch_size", type=positive_int, default=None, help="Corpus embedding/index batch size, default: 32.")
    parser.add_argument("--query_batch_size", type=positive_int, default=32, help="Query embedding batch size, default: 32.")
    parser.add_argument("--max_queries", type=positive_int, default=None, help="Optional smoke-test query limit.")
    parser.add_argument("--include_answer", nargs="?", const=True, default=False, type=parse_bool, help="Record answer-related artifacts for full RAG runs.")
    parser.add_argument(
        "--enable_online_answer",
        nargs="?",
        const=True,
        default=False,
        type=parse_bool,
        help="Explicitly enable the online answer LLM call for full RAG. Default: false.",
    )
    parser.add_argument("--business_project_code", default=None, help="Business eval project code. Default: EVAL_BEIR_{dataset}.")
    parser.add_argument("--business_user_id", default="beir_eval_user", help="Business eval username or numeric user id.")
    parser.add_argument(
        "--business_index_targets",
        type=parse_business_index_targets,
        default=parse_business_index_targets("milvus,bm25,ripgrep"),
        help="Comma-separated business index targets, default: milvus,bm25,ripgrep.",
    )
    parser.add_argument("--eval_mode", nargs="?", const=True, default=True, type=parse_bool, help="Pass eval_mode=true into real RAG graph.")
    parser.add_argument("--force_business_reindex", action="store_true", help="Rebuild BEIR data inside the eval-only business project.")
    parser.add_argument("--verbose", action="store_true", help="Enable DEBUG logs.")
    index_group = parser.add_mutually_exclusive_group()
    index_group.add_argument("--force_reindex", action="store_true", help="Drop and rebuild the Milvus collection before evaluation.")
    index_group.add_argument("--skip_index", action="store_true", help="Skip corpus indexing and directly evaluate an existing collection.")
    parser.add_argument("--data_dir", type=Path, default=WORKSPACE_ROOT / "eval" / "beir" / "datasets", help="BEIR dataset directory.")
    parser.add_argument("--output_dir", type=Path, default=None, help="Report output directory. Default: eval/beir/results/{dataset}/{timestamp}.")
    parser.add_argument("--batch_size", type=positive_int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--limit_queries", type=positive_int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--reports_dir", type=Path, default=None, help=argparse.SUPPRESS)
    return parser.parse_args()


def resolve_output_dir(args: argparse.Namespace) -> Path:
    """Resolve the run output directory."""

    if args.output_dir is not None:
        return args.output_dir
    if args.reports_dir is not None:
        return args.reports_dir
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return WORKSPACE_ROOT / "eval" / "beir" / "results" / args.dataset / timestamp


def positive_int(value: str) -> int:
    """argparse type for positive integers."""

    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be > 0")
    return parsed


def parse_bool(value: str | bool) -> bool:
    """Parse flexible boolean CLI values."""

    if isinstance(value, bool):
        return value
    normalized = value.lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError("expected boolean value")


def parse_k_values(value: str) -> list[int]:
    """Parse comma-separated K values."""

    k_values = sorted({positive_int(item.strip()) for item in value.split(",") if item.strip()})
    if not k_values:
        raise argparse.ArgumentTypeError("k_values cannot be empty")
    return k_values


def parse_retrievers(value: str | list[str]) -> list[str]:
    """Parse comma-separated retriever names."""

    if isinstance(value, list):
        return value
    if not value:
        return []
    retrievers = [item.strip().lower().replace("-", "_") for item in value.split(",") if item.strip()]
    unsupported = [item for item in retrievers if item not in RETRIEVER_CHOICES]
    if unsupported:
        raise argparse.ArgumentTypeError(f"unsupported retrievers: {','.join(unsupported)}")
    return retrievers


def parse_business_index_targets(value: str | list[str]) -> list[str]:
    """Parse comma-separated business index targets."""

    if isinstance(value, list):
        return value
    allowed = {"milvus", "bm25", "keyword", "ripgrep", "pageindex", "graphrag"}
    targets = [item.strip().lower().replace("-", "_") for item in value.split(",") if item.strip()]
    unsupported = [item for item in targets if item not in allowed]
    if unsupported:
        raise argparse.ArgumentTypeError(f"unsupported business_index_targets: {','.join(unsupported)}")
    return targets or ["milvus", "bm25", "ripgrep"]


def parse_weights(value: str | dict[str, float]) -> dict[str, float]:
    """Parse weighted-fusion weights."""

    if isinstance(value, dict):
        return value
    if not value:
        return {}
    weights: dict[str, float] = {}
    for item in value.split(","):
        if not item.strip():
            continue
        if "=" not in item:
            raise argparse.ArgumentTypeError(f"invalid weight item: {item}")
        key, raw_value = item.split("=", 1)
        weights[key.strip().lower().replace("-", "_")] = float(raw_value)
    return weights


if __name__ == "__main__":
    main()
