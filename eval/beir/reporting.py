"""JSON and Markdown report writers for BEIR evaluation."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from eval.beir.types import QueryTrace


def write_reports(
    report_dir: Path,
    dataset: str,
    retriever: str,
    top_k: int,
    rerank: bool,
    payload: dict[str, Any],
    traces: list[QueryTrace],
) -> dict[str, Path]:
    """Write JSON and Markdown reports to eval/beir/reports."""

    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base_name = f"{dataset}_{retriever}_top{top_k}_rerank{int(rerank)}_{timestamp}"
    json_path = report_dir / f"{base_name}.json"
    md_path = report_dir / f"{base_name}.md"

    serializable_payload = {
        **payload,
        "query_traces": [_trace_to_dict(trace) for trace in traces],
    }
    json_path.write_text(json.dumps(serializable_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_markdown_report(serializable_payload), encoding="utf-8")
    return {"json": json_path, "markdown": md_path}


def _trace_to_dict(trace: QueryTrace) -> dict[str, Any]:
    """Convert QueryTrace to a report dict."""

    return {
        "query_id": trace.query_id,
        "query": trace.query,
        "elapsed_ms": trace.elapsed_ms,
        "top_docs": trace.top_docs,
        "rankings": trace.rankings,
        "qrels_doc_ids": trace.qrels_doc_ids,
        "hit_qrels": trace.hit_qrels,
        "qrels_hit": trace.qrels_hit,
        "retriever": trace.retriever,
        "rerank": trace.rerank,
    }


def _markdown_report(payload: dict[str, Any]) -> str:
    """Build a compact Markdown report."""

    config = payload["config"]
    metrics = payload["metrics"]["flat"]
    traces = payload["query_traces"]
    hit_count = sum(1 for trace in traces if trace["qrels_hit"])
    hit_rate = hit_count / len(traces) if traces else 0.0

    lines = [
        f"# BEIR Evaluation Report - {config['dataset']}",
        "",
        "## Configuration",
        "",
        f"- Dataset: `{config['dataset']}`",
        f"- Split: `{config['split']}`",
        f"- Retriever: `{config['retriever']}`",
        f"- Keyword adapter: `{config['keyword_adapter']}`",
        f"- TopK: `{config['top_k']}`",
        f"- Rerank: `{config['rerank']}`",
        f"- Collection: `{config['collection_name']}`",
        f"- Query count: `{config['query_count']}`",
        f"- Corpus count: `{config['corpus_count']}`",
        "",
        "## Metrics",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
    ]
    for key in sorted(metrics):
        lines.append(f"| {key} | {metrics[key]:.5f} |")

    lines.extend(
        [
            "",
            "## Query Trace Summary",
            "",
            f"- Queries with qrels hit in TopK: `{hit_count}/{len(traces)}`",
            f"- TopK qrels hit rate: `{hit_rate:.5f}`",
            "",
            "| Query ID | Elapsed ms | Qrels Hit | Hit Docs | Top Docs |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for trace in traces:
        top_docs = ", ".join(trace["top_docs"][:10])
        hit_docs = ", ".join(trace["hit_qrels"])
        lines.append(
            f"| {trace['query_id']} | {trace['elapsed_ms']} | {trace['qrels_hit']} | "
            f"{hit_docs or '-'} | {top_docs or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)
