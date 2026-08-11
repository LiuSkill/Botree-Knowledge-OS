# 知识问答 Debugger：端到端问答 Trace 规格

## Problem Statement

当前系统已经保存检索轨迹、Agent 执行摘要和问答审计信息，但这些信息分散在消息、检索 Trace 和前端组件中，无法稳定还原一次问答从问题进入到结果返回的完整因果链。定位问题时看不到查询改写、短期记忆融合、多意图拆解、实际生效的 TopK/阈值/融合算法、候选得分变化、最终证据、最终 Prompt 及异常分支，导致知识问答的召回、重排、证据判断和答案生成问题难以复盘。

## Solution

为每次用户提问创建一条根问答 Trace，以不可变 Trace 事件记录全部可观测执行信息，由异步 Worker 幂等聚合为可查询的阶段摘要和节点索引。Debugger 从现有“问答审计 → 问答详情”进入，仅对拥有 `system:qa-audit:debug` 的人员开放；问答完成或失败后进行事后诊断，前端以九个业务阶段导航并可下钻到真实执行节点及其完整载荷。

## User Stories

1. As a knowledge-question user, I want my question to have one root Trace, so that the entire answer can be diagnosed as a single unit.
2. As a knowledge-question user, I want Trace recording failures not to block or materially delay my answer, so that observability does not reduce availability.
3. As a QA analyst, I want to see whether a Trace is complete, incomplete, failed, cancelled, or partial, so that missing events are not mistaken for skipped processing.
4. As a QA analyst, I want to see the original question and effective question, so that memory-based context changes are explicit.
5. As a QA analyst, I want to inspect short-term memory fusion inputs, referenced context IDs, topic-shift decisions, and rewrite reasons, so that follow-up question errors can be explained.
6. As a QA analyst, I want to inspect pre-intent gating, multi-intent recognition, intent ordering, and sub-question decomposition, so that orchestration errors can be located.
7. As a QA analyst, I want to inspect query profiles and every query rewrite, so that retrieval quality can be compared across original and derived queries.
8. As a QA analyst, I want to inspect the retrieval plan and selected channels, so that planner decisions can be reproduced.
9. As a QA analyst, I want to see effective TopK, thresholds, weights, fusion algorithm and all runtime overrides, so that configuration drift cannot hide the cause of an answer.
10. As a QA analyst, I want to see model names, model routes, prompt versions and resolved configuration sources, so that the exact execution environment is known.
11. As a QA analyst, I want to inspect every recall branch, candidate count, candidate content reference and relevance score, so that recall loss is visible.
12. As a QA analyst, I want to inspect rerank inputs, scores, ordering and discarded candidates, so that reranking regressions can be identified.
13. As a QA analyst, I want to inspect evidence decisions, rule hits, confidence, access outcomes and rejection reasons, so that evidence selection is explainable.
14. As a QA analyst, I want to inspect the final evidence set and its scores, so that the answer's factual basis can be verified.
15. As a QA analyst, I want to inspect the final answer Prompt and the model's observable raw response, so that generation problems can be reproduced.
16. As a QA analyst, I want to inspect sensitive filtering before and after content, matched rules and the resulting action, so that refusals and redactions can be diagnosed.
17. As a QA analyst, I want to inspect retries, timeouts, exceptions, fallback and degradation paths, so that partial failures are distinguishable from normal execution.
18. As a QA analyst, I want to navigate a stable nine-stage business view, so that the overall flow is easy to understand.
19. As a QA analyst, I want to expand each stage into real execution nodes with parent, dependency and parallel-group relations, so that orchestration remains faithful to runtime behavior.
20. As a QA analyst, I want default summaries with on-demand full payloads, so that the page remains readable while all information remains available.
21. As a QA analyst, I want structured tabs for input, output, effective configuration, candidates/evidence, decisions, errors and raw event JSON, so that different information types are easy to compare.
22. As a QA analyst, I want long content and candidate lists to be folded, paginated or copied without truncating stored data, so that investigation is practical.
23. As an authorized Debugger user, I want complete business payload visibility without project-scope, knowledge-base, classification or sensitive-mask filtering, so that privileged diagnosis can reproduce the request exactly.
24. As a security administrator, I want authentication credentials and secrets excluded before Trace events are produced, so that diagnostic completeness never creates a credential store.
25. As a system operator, I want Trace data retained by default and deletable only through an audited explicit operation, so that historical incidents remain diagnosable.
26. As a system operator, I want large Trace payloads separated from list summaries and optionally compressed or stored as object references, so that storage growth does not degrade audit queries.
27. As a system operator, I want duplicate and out-of-order events to converge to one result, so that at-least-once asynchronous delivery is safe.
28. As a maintainer, I want versioned event envelopes and backward-compatible readers, so that schema evolution does not invalidate historical Traces.

## Implementation Decisions

- Extend the existing Chat completion boundary and Retrieval Trace service rather than creating a parallel answer pipeline.
- Create a root Trace at question ingress; persist events asynchronously after each observable node and finalize after success or failure.
- Use an immutable event store as the source of truth, an asynchronously rebuilt Trace aggregate for list/detail summaries, and on-demand node payload storage for large data.
- Use a versioned event envelope containing schema version, event ID, trace ID, node ID, parent node ID, business stage, event type, sequence, occurrence time, producer, payload/payload reference and checksum.
- Guarantee at-least-once delivery with idempotency keys; allow event reordering and retries; expose explicit completeness state when events are missing.
- Provide nine stable business stages: question entry, question understanding, retrieval planning, multi-route recall, reranking, evidence judgment, answer generation, sensitive filtering and result return.
- Preserve actual execution nodes under stages, including pre-intent gate, intent recognition, answer policy routing, session-memory contextualization, query decomposition, query profile, question understanding, policy resolution, planner, retrieval, evidence judgment, answer-policy gate and answer generation.
- Capture observable inputs, outputs, effective configuration snapshots and sources, candidates, scores, rules, decisions, evidence, prompts, model routes, raw observable model responses, errors, retries, fallbacks and timings.
- Do not capture hidden model chain-of-thought. Structured decision fields are required where explanation is needed.
- Add a `system:qa-audit:debug` action permission under the existing Q&A audit menu. The backend detail endpoint and frontend Debugger action both enforce it; ordinary `system:qa-audit:view` remains unchanged.
- Add a Debugger action to the Q&A audit detail row. The page uses a Trace overview, a nine-stage expandable execution tree, and a node inspector with fixed sections for summary, input, output, effective configuration, candidates/evidence, decisions, errors and raw JSON.
- Load summaries first and large payloads on demand. Keep chat messages, knowledge documents and citations independent from Debugger retention/deletion.
- Retain Trace data indefinitely by default. Explicit cleanup requires the existing authorized operational path and an audit record.

## Testing Decisions

- Test externally observable API behavior, persisted Trace states and rendered data contracts rather than private helper implementation details.
- Add service tests for root Trace creation, stage/node event emission, effective configuration capture, failure finalization, incomplete-state detection, retry/duplicate handling and secret exclusion.
- Add repository/aggregate tests for out-of-order events, idempotent replay, reconstruction and large-payload references.
- Add API tests for `system:qa-audit:view` versus `system:qa-audit:debug`, complete detail retrieval, pagination, filters and explicit cleanup authorization.
- Add frontend tests for the audit-row Debugger action, stage tree rendering, node tabs, skipped/failed/incomplete states and lazy payload loading.
- Reuse existing prior art in chat trace schema, retrieval trace service, chat visible progress, answer policy/evidence, sensitive filter and Q&A audit tests.

## Out of Scope

- Real-time Debugger streaming or live intervention in an executing answer.
- Recording model hidden chain-of-thought.
- Changing retrieval, reranking, evidence, answer or sensitive-filter business rules as part of the observability feature.
- Applying Debugger Trace data to ordinary user-facing citations or answer content.
- Deleting or rewriting chat messages, knowledge documents, document versions or citation records.
- Building a separate permissions system or account allowlist.
- Automatic retention expiry without an explicit audited operator action.

## Further Notes

- Existing `agent_trace_json`, `progress_json` and `retrieval_traces` should be treated as compatibility inputs during migration; the new Trace aggregate becomes the Debugger read model.
- The feature should preserve trace IDs across LangGraph, multi-intent orchestration, asynchronous workers and API responses for support correlation.
- Payloads must be protected from accidental secret capture at event construction time, before queueing or persistence.
