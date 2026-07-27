# 多模态索引与视觉检索

## Problem Statement

当前知识库的索引和在线检索以文本 Chunk 为中心。解析后没有可靠正文的扫描件、图纸和图片页面无法生成 Chunk，Milvus 未启用时流水线仍可能继续发布，现有视觉能力也只是为已命中的文本证据挂载图片，不能独立发现纯视觉内容。固定字符分块、旧向量二次过滤、跨索引发布不一致以及缺少视觉评测，会造成检索召回下降、部分覆盖不可见或索引状态与实际能力不一致。

## Solution

建立页面/图片块级索引准入和多模态检索闭环。内容单元根据综合质量判断进入文本索引、视觉索引、元数据可发现或等待人工修正；文本索引使用结构感知分块，视觉索引使用整页与局部区域的图文对齐多模态 Embedding。在线检索新增独立 `visual` retriever，与文本向量、PageIndex、关键词和图谱通道并行，统一使用已验证范围快照进行权限、版本和状态校验；视觉理解模型只处理入围候选。Chunk 规则变化时对目标知识库执行原地完整重建，复用未变化的解析和独立视觉产物，并通过源快照校验检测并发变化。

## User Stories

1. As a knowledge administrator, I want each page or image block to receive an explicit index admission result, so that unsupported content is not silently treated as searchable text.
2. As a knowledge administrator, I want OCR and image descriptions to pass a composite quality gate, so that noisy text does not pollute semantic recall.
3. As a knowledge administrator, I want a critical-quality veto for tables, formulas, drawing numbers, layout order and source traceability, so that a high aggregate score cannot hide a broken business structure.
4. As a knowledge administrator, I want image-only content to enter a visual index without requiring a text Chunk, so that scans and drawings remain discoverable.
5. As a knowledge administrator, I want unsupported content to remain metadata-discoverable without being treated as answer evidence, so that users can locate the source without receiving false textual claims.
6. As a knowledge administrator, I want partial coverage to be explicitly labeled and measured, so that missing pages are visible to operators and answer policies.
7. As a knowledge administrator, I want key pages and content areas to meet publication gates, so that a document cannot appear complete while its core drawing or table is missing.
8. As a knowledge administrator, I want exact duplicate content merged with all source mappings preserved, so that duplicate evidence does not consume candidate slots.
9. As a knowledge administrator, I want near-duplicate content retained and diversified at retrieval time, so that small parameter differences are not removed accidentally.
10. As a knowledge administrator, I want Chunk rules to prefer headings, clauses, tables, formulas, captions and natural boundaries, so that evidence keeps its business context.
11. As a knowledge administrator, I want Chunk rules to fall back to bounded length splitting, so that oversized content remains indexable.
12. As a knowledge administrator, I want each Chunk rule version recorded with downstream index metadata, so that incompatible index generations are not mixed.
13. As a knowledge administrator, I want a complete knowledge-base rebuild to reuse parsed pages and independent visual assets, so that changing Chunk rules does not force unnecessary parsing or image regeneration.
14. As a knowledge administrator, I want rebuilds to validate source snapshots before and after execution, so that concurrent changes cannot produce an untrustworthy index.
15. As a knowledge administrator, I want a rebuild to fail rather than publish mixed-source results, so that every published result corresponds to a known source snapshot.
16. As a user, I want a text question to retrieve visual pages even when no text Chunk matches, so that answers that exist only in drawings are not missed.
17. As a user, I want visual retrieval to include both whole-page and local-region candidates, so that both layout-level and fine-grained symbols can be found.
18. As a user, I want visual regions linked to their parent page and neighboring regions, so that a local match can be interpreted with enough context.
19. As a user, I want visual retrieval to run in parallel with text retrieval, so that adding a modality does not serialize the entire search flow.
20. As a user, I want visual candidate retrieval to participate by default when the accessible scope contains visual content, so that routing does not depend on explicit image keywords.
21. As a user, I want expensive visual understanding to run only on final visual candidates or when text evidence is insufficient, so that ordinary text questions do not pay the full multimodal cost.
22. As a user, I want text, visual, PageIndex, keyword and graph evidence fused with source-aware deduplication, so that one page does not crowd out diverse relevant evidence.
23. As a user, I want visual and textual scores normalized or rank-fused before reranking, so that raw scores from different modalities are not compared incorrectly.
24. As a user, I want every retrieval route to use the same verified access snapshot, so that a result cannot be visible in one route and blocked in another.
25. As a user, I want permission, security, version and publish-state validation to fail closed, so that stale metadata cannot expose evidence or suppress safe results unpredictably.
26. As a user, I want a short-lived verified access snapshot to be actively invalidated after permission tightening, rollback or archive, so that mutable governance changes take effect promptly.
27. As a user, I want non-security route failures to return remaining evidence with an explicit incomplete status, so that partial recall is not mistaken for proof that no answer exists.
28. As a user, I want the answer to be refused when the primary route for the question fails, so that a visual question is not answered from unrelated weak text evidence.
29. As an operator, I want visual Embedding inference isolated from API and worker processes, so that model memory pressure does not destabilize request handling.
30. As an operator, I want visual understanding to run through a separate or remote model service, so that GPU capacity and concurrency can be scaled independently.
31. As an operator, I want configurable visual retrieval and visual-understanding timeouts, so that external model stalls cannot hold requests indefinitely.
32. As an operator, I want per-stage timing and route completion recorded, so that capacity and latency can be assessed after the first functional release.
33. As an operator, I want runtime changes to permission, version and status prefilters to run the agreed offline recall gate before activation, so that governance changes do not silently reduce recall.
34. As an operator, I want the offline gate segmented by text, visual, mixed-modality, OCR rejection, local-region, version, duplicate and timeout scenarios, so that aggregate Recall@K cannot hide critical failures.
35. As an auditor, I want every visual citation to resolve to a page or region asset and its source version, so that visual answers remain traceable.
36. As an auditor, I want metadata-only evidence excluded from answer citations, so that locating a document is not confused with proving its contents.

## Implementation Decisions

- Extend the knowledge indexing pipeline with page/image-block admission states and a publication manifest that records required indexes per content unit.
- Add a visual indexing adapter that produces whole-page and local-region records with parent-page, neighboring-region, source-version, security and index-generation metadata.
- Use a graph-aligned multimodal Embedding model for visual candidate vectors. Use the existing independent model-service boundary for visual understanding; do not load vision models in API request workers.
- Add `visual` to the retrieval router and planner. It runs in parallel with existing retrievers when the scope can contain visual content; query features may tune weights but cannot disable the route solely because image keywords are absent.
- Preserve the existing visual evidence enrichment service as post-retrieval asset attachment, not as the visual retriever.
- Fuse cross-modal candidates by normalized score or rank fusion, then deduplicate exact content while retaining all provenance and diversify near-duplicates by document/page/region.
- Generate one verified access snapshot from the business database per retrieval request. All retrievers and post-filters consume it; index metadata cannot independently define access.
- Treat security, permission, version and publish-state validation as fail-closed. Allow bounded verified snapshots with explicit invalidation on governance tightening, rollback and archive.
- Represent route failures as incomplete retrieval unless the failed route is the primary route for the query; in that case refuse answer generation.
- Version Chunk rules, preprocessing, OCR/description, Embedding models, dimensions, distance metric, region segmentation and build strategy as one compatible index generation.
- For a Chunk-rule change, rebuild the target knowledge base in place from a source snapshot, reusing unchanged parsed pages and independent visual assets. Do not retain or mix the old index; reject the rebuild if the source snapshot changes.
- Allow controlled partial-coverage publication only when effective-content coverage and key-page gates pass; expose the state and missing coverage to retrieval and answer policy.
- Keep configurable per-route and total retrieval timeouts plus timing traces. No performance SLO or version-release recall gate is part of the first implementation; only runtime permission/version/status prefilter changes use the offline recall gate.

## Testing Decisions

- Test the highest seam possible: the indexing pipeline and retrieval graph/router, asserting externally visible admission states, publication status, evidence sets, citations and incomplete/拒答 decisions rather than private helper calls.
- Add indexing tests for text-only, visual-only, mixed pages, OCR rejection, critical-structure veto, partial coverage, exact duplicates, near-duplicates, source-snapshot drift and incompatible index generations.
- Add visual retriever tests for whole-page and local-region recall, parent-page context, access filtering, version filtering, score fusion, route timeout and primary-route failure behavior.
- Add retrieval graph tests for parallel route execution, conditional visual understanding, non-security partial degradation, security fail-closed behavior and metadata-only exclusion from citations.
- Add model-service contract tests for visual query/document Embedding compatibility, dimension/metric validation, batching, timeout and model-generation metadata.
- Reuse existing retrieval planner, scope policy, Milvus retriever, page-index retriever, visual evidence, graph trace and document index service test patterns.
- Add evaluation fixtures segmented by text, visual, mixed-modality, OCR rejection, table/formula, local-region, duplicate, version and timeout scenarios. Report per-bucket Recall@K and key-page/region miss rates; do not rely on aggregate metrics.

## Out of Scope

- Production drift monitoring and online recall SLO enforcement.
- Version-release recall gates for model, Chunk, OCR, fusion or index strategy changes.
- Keeping an old index for rollback or mixing old and new Chunk generations during an in-place rebuild.
- Automatic freezing of knowledge-base writes during rebuild; source snapshot validation is the agreed protection.
- Full-image visual understanding for every query or every indexed image.
- Replacing the existing answer-generation policy, permissions model or document governance workflow beyond the retrieval contracts described above.

## Further Notes

The current implementation has no independent visual retriever, cannot index image-only pages without text Chunks, may mark Milvus-skipped builds as successful, uses fixed-size character Chunking, and filters stale vector hits only after bounded Milvus retrieval. These are known gaps to be addressed by this spec. The first release should preserve route-level traces and configurable timeouts even though capacity and latency thresholds are deferred.
