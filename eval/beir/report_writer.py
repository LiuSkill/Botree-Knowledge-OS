"""Structured report writer for unified BEIR evaluation runs."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


QUERY_DETAIL_COLUMNS = [
    "query_id",
    "query_text",
    "candidate_k",
    "rerank_top_k",
    "eval_top_k",
    "answer_top_k",
    "expected_doc_ids",
    "retrieved_doc_ids_top1",
    "retrieved_doc_ids_top3",
    "retrieved_doc_ids_top5",
    "retrieved_doc_ids_top10",
    "retrieved_doc_ids_top100",
    "hit_at_1",
    "hit_at_3",
    "hit_at_5",
    "hit_at_10",
    "hit_at_50",
    "hit_at_100",
    "first_hit_rank",
    "retriever_route",
    "fusion_method",
    "rerank_enabled",
    "reranker_model_name",
    "reranker_score_order",
    "rerank_before_first_hit_rank",
    "latency_total_ms",
    "latency_embedding_ms",
    "latency_retrieval_ms",
    "latency_fusion_ms",
    "latency_rerank_ms",
    "latency_planner_ms",
    "error",
]

RERANK_DEBUG_COLUMNS = [
    "query_id",
    "doc_id",
    "old_rank",
    "new_rank",
    "rank_delta",
    "old_score",
    "reranker_score",
    "is_qrels_hit",
    "source_retriever",
    "score_order",
    "reranker_model_name",
    "candidate_doc_text_len",
]


def write_eval_reports(output_dir: Path, payload: dict[str, Any]) -> dict[str, Path]:
    """Write all standard BEIR evaluation report files."""

    output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = output_dir / "metrics.json"
    details_csv_path = output_dir / "query_details.csv"
    details_jsonl_path = output_dir / "query_details.jsonl"
    rerank_debug_csv_path = output_dir / "rerank_debug.csv"
    failed_cases_path = output_dir / "failed_cases.md"
    report_path = output_dir / "report.md"
    unmapped_evidence_path = output_dir / "unmapped_evidence.jsonl"
    answer_details_path = output_dir / "answer_details.jsonl"

    metrics_payload = {
        "config": payload.get("config", {}),
        "metrics": payload.get("metrics", {}),
        "latency": payload.get("latency", {}),
        "hit_summary": payload.get("hit_summary", {}),
        "rerank_summary": payload.get("rerank_summary", {}),
        "business_summary": payload.get("business_summary", {}),
        "business_index_result": payload.get("business_index_result", {}),
        "reranker_check": payload.get("reranker_check", {}),
        "warnings": payload.get("warnings", []),
        "errors": payload.get("errors", []),
        "failed_queries": payload.get("failed_queries", []),
        "result_query_count": len(payload.get("results", {})),
    }
    metrics_path.write_text(json.dumps(metrics_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_query_details_csv(details_csv_path, payload.get("query_traces", []))
    _write_query_details_jsonl(details_jsonl_path, payload.get("query_traces", []))
    _write_rerank_debug_csv(rerank_debug_csv_path, payload.get("rerank_debug_rows", []))
    if payload.get("unmapped_evidence"):
        _write_jsonl(unmapped_evidence_path, payload.get("unmapped_evidence", []))
    if payload.get("answer_details"):
        _write_jsonl(answer_details_path, payload.get("answer_details", []))
    failed_cases_path.write_text(_failed_cases_markdown(payload), encoding="utf-8")
    report_path.write_text(_report_markdown(payload), encoding="utf-8")
    paths = {
        "metrics_json": metrics_path,
        "query_details_csv": details_csv_path,
        "query_details_jsonl": details_jsonl_path,
        "rerank_debug_csv": rerank_debug_csv_path,
        "failed_cases_md": failed_cases_path,
        "report_md": report_path,
    }
    if payload.get("unmapped_evidence"):
        paths["unmapped_evidence_jsonl"] = unmapped_evidence_path
    if payload.get("answer_details"):
        paths["answer_details_jsonl"] = answer_details_path
    return paths


def write_compare_report(output_dir: Path, compare_payload: dict[str, Any]) -> Path:
    """Write a Markdown comparison report for multiple retrieval strategies."""

    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "compare_report.md"
    path.write_text(_compare_markdown(compare_payload), encoding="utf-8")
    return path


def _write_query_details_csv(path: Path, traces: list[dict[str, Any]]) -> None:
    """Persist query-level details in a spreadsheet-friendly format."""

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=QUERY_DETAIL_COLUMNS)
        writer.writeheader()
        for trace in traces:
            writer.writerow(_trace_to_csv_row(trace))


def _write_query_details_jsonl(path: Path, traces: list[dict[str, Any]]) -> None:
    """Persist full query traces as JSONL."""

    with path.open("w", encoding="utf-8") as handle:
        for trace in traces:
            handle.write(json.dumps(trace, ensure_ascii=False) + "\n")


def _write_rerank_debug_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Persist rerank before/after rank diagnostics."""

    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=RERANK_DEBUG_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in RERANK_DEBUG_COLUMNS})


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write a JSONL file."""

    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def _trace_to_csv_row(trace: dict[str, Any]) -> dict[str, Any]:
    """Convert one query trace to the required CSV columns."""

    retrieved = trace.get("retrieved_doc_ids", [])
    hit_at = trace.get("hit_at", {})
    latency = trace.get("latency_ms", {})
    return {
        "query_id": trace.get("query_id", ""),
        "query_text": trace.get("query_text", ""),
        "candidate_k": trace.get("candidate_k", ""),
        "rerank_top_k": trace.get("rerank_top_k", ""),
        "eval_top_k": trace.get("eval_top_k", ""),
        "answer_top_k": trace.get("answer_top_k", ""),
        "expected_doc_ids": _json_list(trace.get("expected_doc_ids", [])),
        "retrieved_doc_ids_top1": _json_list(retrieved[:1]),
        "retrieved_doc_ids_top3": _json_list(retrieved[:3]),
        "retrieved_doc_ids_top5": _json_list(retrieved[:5]),
        "retrieved_doc_ids_top10": _json_list(retrieved[:10]),
        "retrieved_doc_ids_top100": _json_list(retrieved[:100]),
        "hit_at_1": bool(hit_at.get("1", False)),
        "hit_at_3": bool(hit_at.get("3", False)),
        "hit_at_5": bool(hit_at.get("5", False)),
        "hit_at_10": bool(hit_at.get("10", False)),
        "hit_at_50": bool(hit_at.get("50", False)),
        "hit_at_100": bool(hit_at.get("100", False)),
        "first_hit_rank": trace.get("first_hit_rank") or "",
        "retriever_route": trace.get("retriever_route", ""),
        "fusion_method": trace.get("fusion_method", ""),
        "rerank_enabled": bool(trace.get("rerank_enabled", False)),
        "reranker_model_name": trace.get("reranker_model_name", ""),
        "reranker_score_order": trace.get("reranker_score_order", ""),
        "rerank_before_first_hit_rank": trace.get("rerank_before_first_hit_rank") or "",
        "latency_total_ms": int(latency.get("total_ms", 0)),
        "latency_embedding_ms": int(latency.get("embedding_ms", 0)),
        "latency_retrieval_ms": int(latency.get("retrieval_ms", 0)),
        "latency_fusion_ms": int(latency.get("fusion_ms", 0)),
        "latency_rerank_ms": int(latency.get("rerank_ms", 0)),
        "latency_planner_ms": int(latency.get("planner_ms", 0)),
        "error": trace.get("error", ""),
    }


def _failed_cases_markdown(payload: dict[str, Any]) -> str:
    """Build failed-case buckets for quick retrieval diagnosis."""

    traces = payload.get("query_traces", [])
    top100_miss = [trace for trace in traces if not trace.get("first_hit_rank") or int(trace.get("first_hit_rank") or 0) > 100]
    top10_miss = [
        trace
        for trace in traces
        if trace.get("first_hit_rank") and 10 < int(trace["first_hit_rank"]) <= 100
    ]
    rerank_dropped = [
        trace
        for trace in traces
        if trace.get("rerank_enabled")
        and trace.get("raw_first_hit_rank")
        and trace.get("first_hit_rank")
        and int(trace["first_hit_rank"]) > int(trace["raw_first_hit_rank"])
    ]

    lines = ["# Failed Cases", ""]
    _append_case_section(lines, "Top100 Miss", top100_miss)
    _append_case_section(lines, "Top100 Hit But Top10 Miss", top10_miss)
    _append_case_section(lines, "Reranker Rank Dropped", rerank_dropped)
    return "\n".join(lines) + "\n"


def _report_markdown(payload: dict[str, Any]) -> str:
    """Build a human-readable Markdown report."""

    config = payload.get("config", {})
    metrics = payload.get("metrics", {}).get("flat", {})
    latency = payload.get("latency", {})
    hit_summary = payload.get("hit_summary", {})
    traces = payload.get("query_traces", [])
    rerank_summary = payload.get("rerank_summary", {})
    business_summary = payload.get("business_summary", {})
    business_index_result = payload.get("business_index_result", {})
    reranker_check = payload.get("reranker_check", {})

    lines = [
        f"# BEIR Evaluation Report - {config.get('dataset', '-')}",
        "",
        "## Configuration",
        "",
        f"- Dataset: `{config.get('dataset', '-')}`",
        f"- Split: `{config.get('split', '-')}`",
        f"- Mode: `{config.get('mode', '-')}`",
        f"- Retriever: `{config.get('retriever', '-')}`",
        f"- Retrievers: `{','.join(config.get('retrievers', []) or [])}`",
        f"- Fusion: `{config.get('fusion', '-')}`",
        f"- Rerank: `{config.get('rerank', False)}`",
        f"- Reranker score order: `{config.get('reranker_score_order', 'desc')}`",
        f"- Business project code: `{config.get('business_project_code', '-')}`",
        f"- Business user id: `{config.get('business_user_id', '-')}`",
        f"- Business index targets: `{','.join(config.get('business_index_targets', []) or [])}`",
        f"- Adapter type: `{business_summary.get('adapter_type', '-')}`",
        f"- Real permission filtering: `{business_summary.get('real_permission_filtering', False)}`",
        f"- Include answer requested: `{business_summary.get('include_answer_requested', config.get('include_answer', False))}`",
        f"- Online answer LLM enabled: `{business_summary.get('online_answer_enabled', config.get('enable_online_answer', False))}`",
        f"- Include answer LLM: `{business_summary.get('include_answer', bool(config.get('include_answer', False) and config.get('enable_online_answer', False)))}`",
        f"- TopK: `{config.get('top_k', '-')}`",
        f"- candidate_k: `{config.get('candidate_k', '-')}`",
        f"- rerank_top_k: `{config.get('rerank_top_k', '-')}`",
        f"- eval_top_k: `{config.get('eval_top_k', '-')}`",
        f"- answer_top_k: `{config.get('answer_top_k', '-')}`",
        f"- retrieval_mode: `{config.get('retrieval_mode', '-')}`",
        f"- require_real_reranker: `{config.get('require_real_reranker', '-')}`",
        f"- allow_reranker_fallback: `{config.get('allow_reranker_fallback', '-')}`",
        f"- Collection: `{config.get('collection_name', '-')}`",
        f"- Query count: `{config.get('query_count', '-')}`",
        f"- Corpus count: `{config.get('corpus_count', '-')}`",
        "",
    ]

    warnings = payload.get("warnings", [])
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning}")
        lines.append("")

    if business_summary:
        lines.extend(
            [
                "## Business RAG",
                "",
                f"- Business project code: `{business_summary.get('business_project_code', '-')}`",
                f"- Business user id: `{business_summary.get('business_user_id', '-')}`",
                f"- Business index targets: `{','.join(business_summary.get('business_index_targets', []) or [])}`",
                f"- Adapter type: `{business_summary.get('adapter_type', '-')}`",
                f"- Real permission filtering: `{business_summary.get('real_permission_filtering', False)}`",
                f"- Include answer requested: `{business_summary.get('include_answer_requested', False)}`",
                f"- Online answer LLM enabled: `{business_summary.get('online_answer_enabled', False)}`",
                f"- Include answer LLM: `{business_summary.get('include_answer', False)}`",
                f"- Evidence mapping hit rate: `{float(business_summary.get('evidence_mapping_hit_rate', 0.0)):.5f}`",
                f"- Mapped evidence: `{business_summary.get('mapped_evidence_count', 0)}`",
                f"- Unmapped evidence: `{business_summary.get('unmapped_evidence_count', 0)}`",
                "",
            ]
        )

    if business_index_result:
        lines.extend(
            [
                "## Business Index",
                "",
                f"- Status: `{business_index_result.get('status', '-')}`",
                f"- Project ID: `{business_index_result.get('project_id', '-')}`",
                f"- Imported count: `{business_index_result.get('imported_count', 0)}`",
                f"- Indexed count: `{business_index_result.get('indexed_count', 0)}`",
                f"- Mapping path: `{business_index_result.get('mapping_path', '-')}`",
                f"- Elapsed ms: `{business_index_result.get('elapsed_ms', 0)}`",
                "",
            ]
        )

    if reranker_check:
        lines.extend(
            [
                "## Reranker Check",
                "",
                f"- Status: `{reranker_check.get('status', '-')}`",
                f"- Provider: `{reranker_check.get('provider', '-')}`",
                f"- Model: `{reranker_check.get('model_name', '-')}`",
                f"- Loaded: `{reranker_check.get('model_loaded', False)}`",
                f"- Device: `{reranker_check.get('device', '-')}`",
                f"- Backend: `{reranker_check.get('backend', '-')}`",
                f"- Elapsed ms: `{reranker_check.get('elapsed_ms', 0)}`",
                "",
            ]
        )

    lines.extend(["## Metrics", "", "| Metric | Value |", "| --- | ---: |"])
    for key in sorted(metrics):
        lines.append(f"| {key} | {metrics[key]:.5f} |")

    if rerank_summary.get("enabled"):
        reranker = rerank_summary.get("reranker", {})
        before = rerank_summary.get("before", {})
        after = rerank_summary.get("after", {})
        lines.extend(
            [
                "",
                "## Rerank Summary",
                "",
                f"- Status: `{rerank_summary.get('status', 'ok')}`",
                f"- Reranker model: `{reranker.get('model_name', '-')}`",
                f"- Reranker model loaded: `{reranker.get('model_loaded', False)}`",
                f"- Reranker score order: `{reranker.get('score_order', config.get('reranker_score_order', 'desc'))}`",
                "",
                "| Metric | Before | After |",
                "| --- | ---: | ---: |",
            ]
        )
        for key in ["NDCG@10", "MRR@10", "Recall@100", "hit_at_10_count"]:
            before_value = before.get(key, 0)
            after_value = after.get(key, 0)
            if isinstance(before_value, float) or isinstance(after_value, float):
                lines.append(f"| {key} | {float(before_value):.5f} | {float(after_value):.5f} |")
            else:
                lines.append(f"| {key} | {before_value} | {after_value} |")

    lines.extend(["", "## Hit Summary", "", "| K | Hit Queries | Hit Rate |", "| ---: | ---: | ---: |"])
    for key in sorted(hit_summary, key=lambda value: int(value.replace("hit_at_", ""))):
        item = hit_summary[key]
        lines.append(f"| {key.replace('hit_at_', '')} | {item['hit_queries']} | {item['hit_rate']:.5f} |")

    lines.extend(["", "## Latency", "", "| Field | ms |", "| --- | ---: |"])
    for label, key in [
        ("avg_retrieval_ms", "retrieval_avg_ms"),
        ("avg_fusion_ms", "fusion_avg_ms"),
        ("avg_rerank_ms", "rerank_avg_ms"),
        ("avg_total_ms", "avg_total_ms"),
    ]:
        value = latency.get(key)
        if value is None and key == "avg_total_ms":
            value = _avg_trace_total_ms(traces)
        lines.append(f"| {label} | {float(value or 0):.2f} |")
    latency_summary_keys = {"retrieval_avg_ms", "fusion_avg_ms", "rerank_avg_ms", "avg_total_ms"}
    for key in sorted(latency):
        if key in latency_summary_keys:
            continue
        value = latency[key]
        if isinstance(value, (int, float)):
            lines.append(f"| {key} | {value:.2f} |")

    node_latency_keys = [
        ("intent_ms", "intent_avg_ms"),
        ("query_decompose_ms", "query_decompose_avg_ms"),
        ("planner_ms", "planner_avg_ms"),
        ("retrieval_ms", "retrieval_avg_ms"),
        ("rerank_ms", "rerank_avg_ms"),
        ("evidence_judge_ms", "evidence_judge_avg_ms"),
        ("lightweight_filter_ms", "lightweight_filter_avg_ms"),
        ("llm_evidence_judge_ms", "llm_evidence_judge_avg_ms"),
        ("answer_ms", "answer_avg_ms"),
        ("total_ms", "avg_total_ms"),
    ]
    if any(key in latency for _, key in node_latency_keys):
        lines.extend(["", "## Full RAG Node Latency", "", "| Node | Avg ms |", "| --- | ---: |"])
        for label, key in node_latency_keys:
            lines.append(f"| {label} | {float(latency.get(key, 0.0) or 0.0):.2f} |")

    failed_queries = payload.get("failed_queries") or [
        {
            "query_id": trace.get("query_id", ""),
            "error": trace.get("error") or trace.get("business_trace", {}).get("error", ""),
        }
        for trace in traces
        if trace.get("error") or trace.get("business_trace", {}).get("error")
    ]
    if failed_queries:
        lines.extend(["", "## Failed Queries", "", "| Query ID | Error |", "| --- | --- |"])
        for item in failed_queries[:50]:
            lines.append(f"| {item.get('query_id', '')} | {str(item.get('error', '')).replace('|', '/')} |")

    lines.extend(["", "## Slow Queries Top20", "", "| Query ID | Total ms | First Hit Rank | Error |", "| --- | ---: | ---: | --- |"])
    for trace in sorted(traces, key=lambda item: item.get("latency_ms", {}).get("total_ms", 0), reverse=True)[:20]:
        error = trace.get("error") or trace.get("business_trace", {}).get("error") or "-"
        lines.append(
            f"| {trace.get('query_id', '')} | {trace.get('latency_ms', {}).get('total_ms', 0)} | "
            f"{trace.get('first_hit_rank') or '-'} | {str(error).replace('|', '/')} |"
        )
    lines.append("")
    return "\n".join(lines)


def _compare_markdown(compare_payload: dict[str, Any]) -> str:
    """Build the compare-mode Markdown report."""

    runs = compare_payload.get("runs", [])
    recommendation = _recommended_strategy(runs)
    lines = [
        f"# BEIR Compare Report - {compare_payload.get('dataset', '-')}",
        "",
        f"Recommended strategy: `{recommendation}`",
        "",
        "| Strategy | Status | NDCG@10 | Recall@100 | MRR@10 | Avg Retrieval ms | Avg Fusion ms | Avg Rerank ms | Avg Total ms | Warning | Error |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for run in runs:
        metrics = run.get("metrics", {}).get("flat", {})
        latency = run.get("latency", {})
        error = run.get("error", "")
        warnings = run.get("warnings", [])
        rerank_summary = run.get("rerank_summary", {})
        status = "failed" if error else "ok"
        if rerank_summary.get("degraded"):
            status = "RERANK_DEGRADED"
        lines.append(
            f"| {run.get('name', '-')} | {status} | "
            f"{metrics.get('NDCG@10', 0.0):.5f} | {metrics.get('Recall@100', 0.0):.5f} | "
            f"{metrics.get('MRR@10', 0.0):.5f} | {latency.get('retrieval_avg_ms', 0.0):.2f} | "
            f"{latency.get('fusion_avg_ms', 0.0):.2f} | {latency.get('rerank_avg_ms', 0.0):.2f} | "
            f"{latency.get('avg_total_ms', 0.0):.2f} | {_format_warnings(warnings)} | {error or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def _append_case_section(lines: list[str], title: str, traces: list[dict[str, Any]]) -> None:
    lines.extend([f"## {title}", "", f"Count: `{len(traces)}`", ""])
    if traces:
        lines.extend(["| Query ID | First Hit Rank | Expected | Top10 |", "| --- | ---: | --- | --- |"])
        for trace in traces[:50]:
            lines.append(
                f"| {trace.get('query_id', '')} | {trace.get('first_hit_rank') or '-'} | "
                f"{_json_list(trace.get('expected_doc_ids', []))} | {_json_list(trace.get('retrieved_doc_ids', [])[:10])} |"
            )
    lines.append("")


def _json_list(values: list[Any]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _avg_trace_total_ms(traces: list[dict[str, Any]]) -> float:
    if not traces:
        return 0.0
    return sum(float(trace.get("latency_ms", {}).get("total_ms", 0)) for trace in traces) / len(traces)


def _format_warnings(warnings: list[str]) -> str:
    if not warnings:
        return "-"
    return "<br>".join(warnings[:3])


def _recommended_strategy(runs: list[dict[str, Any]]) -> str:
    """Recommend hybrid by default while reranker diagnostics are being repaired."""

    for run in runs:
        if run.get("name") == "hybrid" and not run.get("error") and not run.get("rerank_summary", {}).get("degraded"):
            return "hybrid"
    candidates: list[tuple[float, str]] = []
    for run in runs:
        if run.get("error"):
            continue
        if run.get("rerank_summary", {}).get("degraded"):
            continue
        name = str(run.get("name") or "")
        if name.endswith("reranker"):
            continue
        score = float(run.get("metrics", {}).get("flat", {}).get("NDCG@10", 0.0))
        candidates.append((score, name))
    if not candidates:
        return "hybrid"
    return max(candidates, key=lambda item: item[0])[1]
