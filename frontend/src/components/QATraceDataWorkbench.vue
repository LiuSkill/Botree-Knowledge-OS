<script setup lang="ts">
import { computed, ref } from "vue";

import type { QADebuggerEvent, QADebuggerResult } from "@/api/system";
import ChatRichContent from "@/components/ChatRichContent.vue";

interface CandidateRow {
  key: string;
  rank: number;
  source: string;
  location: string;
  content: string;
  channel: string;
  score?: number;
  previousRank?: number;
  imageUrl?: string;
}
interface FieldRow {
  label: string;
  value: string;
}
interface LifecycleRow extends CandidateRow {
  recallRank?: number;
  recallScore?: number;
  rerankRank?: number;
  rerankScore?: number;
  inEvidence: boolean;
  cited: boolean;
}
interface StepSection {
  title: string;
  description: string;
  rows: FieldRow[];
  emptyText: string;
}
interface RecallRun {
  key: string;
  query: string;
  hits: number;
  elapsed: number;
  timedOut: boolean;
  candidates: CandidateRow[];
}
interface RecallGroup {
  key: string;
  name: string;
  queries: string[];
  hits: number;
  elapsed: number;
  timedOut: boolean;
  candidates: CandidateRow[];
  runs: RecallRun[];
}

const props = defineProps<{
  result: QADebuggerResult;
  question?: string;
  answer?: string;
  feedbackStatus?: "like" | "dislike" | null;
}>();
const emit = defineEmits<{ loadMore: [] }>();

const stageOrder = [
  "question_entry",
  "question_understanding",
  "retrieval_planning",
  "multi_route_recall",
  "reranking",
  "evidence_judgment",
  "answer_generation",
  "sensitive_filtering",
  "result_return",
];
const stageNames: Record<string, string> = {
  question_entry: "问题进入",
  question_understanding: "意图识别",
  retrieval_planning: "检索规划",
  multi_route_recall: "检索召回",
  reranking: "候选重排",
  evidence_judgment: "证据判断",
  answer_generation: "答案生成",
  sensitive_filtering: "敏感过滤",
  result_return: "结果返回",
};
const fieldNames: Record<string, string> = {
  question: "原始问题",
  original_question: "原始问题",
  query: "检索问题",
  effective_question: "补全后的问题",
  intent: "识别意图",
  intent_name: "识别意图",
  intent_type: "意图类型",
  status: "执行状态",
  reason: "判断依据",
  decision: "判断结果",
  elapsed_ms: "执行耗时",
  implementation: "执行方式",
  top_k: "候选数量",
  top_n: "保留数量",
  score_threshold: "最低相关度",
  fusion_algorithm: "结果融合方式",
  algorithm: "处理算法",
  strategy: "处理策略",
  selected_retrievers: "选用的检索方式",
  planned_retrievers: "计划使用的检索方式",
  executed_retrievers: "实际使用的检索方式",
  skipped_retrievers: "未执行的检索方式",
  model: "使用模型",
  model_name: "使用模型",
  model_id: "模型标识",
  model_route: "模型选择",
  provider: "模型服务商",
  deployment: "模型部署",
  prompt_version: "提示词版本",
  version: "版本",
  temperature: "生成随机度",
  action: "处理动作",
  before_content: "处理前内容",
  after_content: "处理后内容",
  answer: "生成答案",
  final_answer: "最终答案",
  answer_preview: "答案预览",
  confidence: "置信度",
  citation_count: "引用数量",
  depends_on: "依赖环节",
  parallel_group_id: "并行任务组",
  route: "问答路线",
  skip_retrieval: "是否跳过检索",
  direct_answer_type: "直接回答类型",
  sub_queries: "拆分后的问题",
  query_profile: "问题画像",
  question_understanding: "问题理解",
  policy_resolution: "策略选择",
  resolved_task_type: "最终任务类型",
  resolved_answer_shape: "回答形式",
  resolved_answer_policy: "回答策略",
  resolved_knowledge_scope: "知识范围",
  memory_trigger_mode: "上下文使用方式",
  memory_original_question: "用户原始问题",
  memory_effective_question: "结合上下文后的问题",
  memory_decision_reason: "上下文处理依据",
  memory_topic_shift: "话题切换判断",
  memory_referenced_context_ids: "引用的上下文",
  query_features: "问题特征",
  retrieval_plan: "检索方案",
  skip_reasons: "未执行原因",
  fallback_ladder: "备用方案顺序",
  fallback_used: "已使用的备用方案",
  fallback_trigger_reason: "启用备用方案的原因",
  retriever_hits: "各检索方式命中数",
  retriever_elapsed_ms: "各检索方式耗时",
  retriever_top_scores: "各检索方式最高分",
  retriever_timeouts: "检索超时情况",
  retrieval_sub_queries: "实际检索问题",
  evidence_judgement: "证据充分性判断",
  evidence_evaluation: "证据质量评估",
  answer_policy_gate: "回答条件判断",
  answer_policy_decision: "回答策略结果",
  retry_count: "重试次数",
  retry_reason: "重试原因",
  retry_retrievers: "重试的检索方式",
  retry_query_count: "补充检索次数",
  retry_query_details: "补充检索详情",
  retry_budget_stop_reason: "停止重试原因",
  timing_summary: "耗时汇总",
  evidence_judge_elapsed_ms: "证据判断耗时",
  retry_evidence_judge_elapsed_ms: "重试判断耗时",
  evidence: "证据摘要",
  visual_asset_count: "视觉资料数量",
  task_type: "任务类型",
  answer_shape: "回答形式",
  knowledge_scope: "知识范围",
  answer_policy: "回答策略",
  retrieval_needs: "检索需求",
  query_rewrites: "改写后的问题",
  enough: "证据是否充分",
  relevance: "相关程度",
  support_level: "支撑程度",
  conflict: "证据是否冲突",
  risk: "风险等级",
  evidence_count: "证据数量",
  strong_evidence_count: "强证据数量",
  weak_evidence_count: "弱证据数量",
  missing_aspects: "缺失信息",
  should_retry: "是否需要补充检索",
  allow_limited_answer: "是否允许有限回答",
  source: "配置来源",
  weights: "权重",
  weight: "权重",
  timeout_ms: "超时时间",
  max_tokens: "最大生成长度",
  query_type: "问题类型",
  need_page_location: "是否需要页码定位",
  need_exact_term: "是否要求术语精确匹配",
  need_visual_asset: "是否需要视觉资料",
  need_graph_reasoning: "是否需要图谱推理",
  conflict_detected: "是否存在策略冲突",
  resolution_rule: "策略选择规则",
  original_intent: "初步识别意图",
};
const valueNames: Record<string, string> = {
  success: "成功",
  failed: "失败",
  running: "执行中",
  skipped: "未执行",
  complete: "记录完整",
  incomplete: "记录不完整",
  partial: "部分记录",
  project_fact: "项目知识查询",
  general_knowledge: "通用知识问答",
  process_parameter: "工艺参数查询",
  process_flow: "工艺流程查询",
  project_overview: "项目概览查询",
  source_location: "资料定位查询",
  comparison: "对比分析",
  graph_reasoning: "关联推理",
  casual: "日常交流",
  unknown: "未确定",
  rag: "查询知识库后回答",
  direct: "直接回答",
  direct_answer: "直接回答",
  direct_value: "直接给出参数值",
  process_steps: "分步骤说明",
  comparison_table: "对比表格",
  project_summary: "项目摘要",
  general: "常规回答",
  clarify: "需要用户补充信息",
  refusal: "拒绝回答",
  sufficient: "证据充分",
  insufficient: "证据不足",
  empty: "无有效证据",
  high: "高",
  medium: "中",
  low: "低",
  none: "无",
  vector: "语义检索",
  keyword: "关键词检索",
  visual: "视觉检索",
  pageindex: "页面索引检索",
  milvus: "语义检索",
  bm25: "关键词检索",
  rules: "规则判断",
  lightweight: "轻量规则判断",
  project: "项目知识库",
  base: "基础知识库",
  industry: "行业知识库",
  project_with_industry: "项目知识优先，行业知识补充",
  true: "是",
  false: "否",
};
const producerNames: Record<string, string> = {
  chat_service: "问答服务",
  retrieval_graph: "知识检索与回答引擎",
  question_answer_trace_service: "过程记录服务",
  multi_intent_orchestration: "多意图编排服务",
};
const activeStage = ref("overview");
const activeEventId = ref<string | null>(null);
const selectedCandidate = ref<CandidateRow | null>(null);
const candidateKeyword = ref("");
const candidateFilter = ref<"all" | "evidence" | "dropped" | "cited">("all");
const selectedRetriever = ref("");
const collapsedStages = ref<Set<string>>(new Set());
const candidateFilterOptions: Array<{
  key: "all" | "evidence" | "dropped" | "cited";
  label: string;
}> = [
  { key: "all", label: "全部" },
  { key: "evidence", label: "最终证据" },
  { key: "dropped", label: "已淘汰" },
  { key: "cited", label: "答案引用" },
];
const allPayloads = computed(() =>
  props.result.events
    .map((event) => event.payload)
    .filter((payload): payload is Record<string, unknown> => Boolean(payload)),
);
const terminalResult = computed(() => {
  for (const payload of [...allPayloads.value].reverse()) {
    const result = asRecord(payload.result);
    if (Object.keys(result).length) return result;
  }
  return {};
});
const runtimeRaw = computed(() => asRecord(terminalResult.value.raw));

const stageItems = computed(() =>
  stageOrder.map((stage) => {
    const events = props.result.events.filter(
      (event) => event.business_stage === stage,
    );
    const summary = props.result.stages.find((item) => item.stage === stage);
    const executedInsidePipeline =
      (stage === "reranking" && runtimeRaw.value.reranker_used === true) ||
      (stage === "sensitive_filtering" &&
        Object.keys(asRecord(runtimeRaw.value.sensitive_filter)).length > 0);
    const warning =
      events.some((event) => /failed|warning/.test(event.event_type)) ||
      (!executedInsidePipeline &&
        events.some((event) => /skipped/.test(event.event_type)));
    const eventElapsed = events.reduce(
      (sum, event) => sum + numberValue(event.payload?.elapsed_ms),
      0,
    );
    const elapsed =
      eventElapsed ||
      (stage === "reranking"
        ? numberValue(runtimeRaw.value.rerank_elapsed_ms)
        : 0);
    return {
      stage,
      name: stageNames[stage],
      events,
      summary: summary || executedInsidePipeline,
      warning,
      elapsed,
    };
  }),
);
const activeEvents = computed(() =>
  props.result.events.filter(
    (event) => event.business_stage === activeStage.value,
  ),
);
const activeEvent = computed(
  () =>
    props.result.events.find(
      (event) => event.event_id === activeEventId.value,
    ) || null,
);
const payloads = computed(() =>
  activeEvents.value
    .map((event) => event.payload)
    .filter((payload): payload is Record<string, unknown> => Boolean(payload)),
);
const primaryPayload = computed(() => payloads.value.at(-1) || {});
const hasMore = computed(
  () => props.result.events.length < props.result.events_total,
);

function numberValue(value: unknown): number {
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}
function firstValue(
  objects: Record<string, unknown>[],
  keys: string[],
): unknown {
  for (const object of objects)
    for (const key of keys)
      if (
        object[key] !== undefined &&
        object[key] !== null &&
        object[key] !== ""
      )
        return object[key];
  return undefined;
}
function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}
function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "未记录";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value))
    return value.every((item) => typeof item !== "object")
      ? value.map((item) => translateValue(String(item))).join("、")
      : `共 ${value.length} 项`;
  if (typeof value === "object")
    return (
      Object.entries(value as Record<string, unknown>)
        .filter(([, item]) => typeof item !== "object")
        .map(
          ([key, item]) =>
            `${fieldNames[key] || translateValue(key)}：${displayValue(item)}`,
        )
        .join("；") || "包含结构化内容"
    );
  return translateValue(String(value));
}
function humanizeKey(key: string): string {
  if (fieldNames[key]) return fieldNames[key];
  const words: Record<string, string> = {
    query: "问题",
    profile: "画像",
    type: "类型",
    count: "数量",
    score: "得分",
    threshold: "阈值",
    elapsed: "耗时",
    retriever: "检索方式",
    retrieval: "检索",
    evidence: "证据",
    answer: "回答",
    policy: "策略",
    route: "路线",
    model: "模型",
    source: "来源",
    reason: "原因",
    result: "结果",
    output: "输出",
    input: "输入",
    config: "配置",
    memory: "上下文",
    retry: "重试",
    fallback: "备用方案",
    visual: "视觉资料",
    task: "任务",
    status: "状态",
    scope: "范围",
    need: "是否需要",
    used: "已使用",
    planned: "计划",
    executed: "已执行",
    skipped: "未执行",
    total: "总计",
    top: "最高",
    ms: "毫秒",
  };
  return key
    .split("_")
    .map((word) => words[word] || word)
    .join(" · ");
}
function translateValue(value: string): string {
  const normalized = value.trim();
  const operationalValues: Record<string, string> = {
    allow: "允许通过",
    redact: "脱敏后通过",
    block: "阻止返回",
    normal_answer: "正常回答",
    enough: "证据充足",
    full: "完整支持",
    partial: "部分支持",
    kb_first: "优先使用知识库",
    base_chat: "基础知识问答",
    auto: "自动选择",
    knowledge_qa: "知识库问答",
    kb_question: "知识库问题",
    parameter_lookup: "参数查询",
    parameter_table: "参数表格",
    scope_only: "仅沿用问答范围",
    stable_scope_only_incomplete_question: "问题较短，仅沿用稳定的问答范围",
    execution_path_did_not_enter_stage: "当前执行路线没有进入独立步骤",
    page_index: "页面索引检索",
    ripgrep: "原文精确检索",
    project_metadata: "项目资料元数据检索",
    graphrag: "知识关系检索",
    deterministic: "确定性降级重排",
    deterministic_fallback: "确定性降级模型",
    system_config: "系统配置",
    qwen: "通义模型",
    answer_generator: "答案生成服务",
  };
  return (
    valueNames[normalized.toLowerCase()] ||
    operationalValues[normalized.toLowerCase()] ||
    normalized
  );
}
function readableRetrieverReason(value: unknown): string {
  const text = String(value || "").trim();
  if (!text) return "未记录选择原因";
  return text.split(";")[0].replace(/^policy_matrix:\s*/i, "");
}
function eventStatus(eventType: string): string {
  const status = eventType.split(".").at(-1) || eventType;
  return valueNames[status] || "已记录";
}
function readableTime(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const clock = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
  return `${clock}.${String(date.getMilliseconds()).padStart(3, "0")}`;
}
function fields(value: unknown, excluded: string[] = []): FieldRow[] {
  const rows: FieldRow[] = [];
  const walk = (item: unknown, prefix = "") => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return;
    for (const [key, child] of Object.entries(
      item as Record<string, unknown>,
    )) {
      if (
        excluded.includes(key) ||
        child === null ||
        child === undefined ||
        child === ""
      )
        continue;
      const label = prefix
        ? `${prefix} / ${humanizeKey(key)}`
        : humanizeKey(key);
      if (typeof child === "object" && !Array.isArray(child))
        walk(child, label);
      else rows.push({ label, value: displayValue(child) });
    }
  };
  walk(value);
  return rows;
}
function arraysFrom(value: unknown, keys: string[]): unknown[] {
  if (Array.isArray(value)) return value;
  const record = asRecord(value);
  for (const key of keys)
    if (Array.isArray(record[key])) return record[key] as unknown[];
  return [];
}
function collectCandidates(sections: string[], keys: string[]): unknown[] {
  const result: unknown[] = [];
  for (const payload of payloads.value) {
    for (const section of sections)
      result.push(...arraysFrom(payload[section], keys));
    result.push(...arraysFrom(payload, keys));
  }
  result.push(...arraysFrom(runtimeRaw.value, keys));
  for (const payload of allPayloads.value) {
    const terminalResult = asRecord(payload.result);
    result.push(
      ...arraysFrom(terminalResult, ["evidences", "evidence", "citations"]),
    );
  }
  return result;
}
function normalizeCandidates(
  items: unknown[],
  reranked = false,
): CandidateRow[] {
  const merged = new Map<string, Record<string, unknown>>();
  items.forEach((item, index) => {
    const record = asRecord(item);
    const metadata = asRecord(record.metadata);
    const identity = String(
      record.chunk_id ??
        metadata.chunk_id ??
        record.id ??
        `${record.document_id ?? "document"}-${record.page_number ?? record.page_no ?? index}`,
    );
    const previous = merged.get(identity) || {};
    merged.set(
      identity,
      Object.fromEntries(
        Object.entries({ ...previous, ...record }).filter(
          ([, value]) => value !== null && value !== undefined && value !== "",
        ),
      ),
    );
  });
  return [...merged.values()]
    .map((record, index) => {
      const metadata = asRecord(record.metadata);
      const stringFrom = (keys: string[]) => {
        for (const key of keys) {
          const value = record[key] ?? metadata[key];
          if (typeof value === "string" && value) return value;
        }
        return "";
      };
      const scoreValue =
        record.rerank_score ??
        record.relevance_score ??
        record.score_after ??
        record.score ??
        record.vector_score ??
        metadata.score;
      const assets = Array.isArray(record.assets)
        ? record.assets.map(asRecord)
        : [];
      const assetUrl = assets
        .map((asset) => asset.url)
        .find((value) => typeof value === "string") as string | undefined;
      const pageNumber =
        record.page_number ??
        record.page_no ??
        metadata.page_number ??
        metadata.page_no;
      const location =
        stringFrom(["page_label", "page", "location", "section_title"]) ||
        (pageNumber === undefined ? "-" : `第 ${displayValue(pageNumber)} 页`);
      const parsedScore = Number(scoreValue);
      return {
        key: String(
          record.chunk_id ?? record.id ?? record.document_id ?? index,
        ),
        rank: numberValue(record.rank_after ?? record.rank ?? index + 1),
        previousRank: numberValue(record.rank_before) || undefined,
        source:
          stringFrom([
            "document_name",
            "source_name",
            "title",
            "filename",
            "file_name",
            "document_title",
            "source",
          ]) || "未命名资料",
        location,
        content:
          stringFrom([
            "text",
            "content",
            "chunk_text",
            "original_text",
            "snippet",
            "ocr_text",
          ]) || displayValue(record),
        channel:
          stringFrom([
            "retriever",
            "channel",
            "retrieval_type",
            "source_type",
            "type",
          ]) || (reranked ? "重排模型" : "-"),
        score: Number.isFinite(parsedScore) ? parsedScore : undefined,
        imageUrl:
          stringFrom([
            "image_url",
            "page_image_url",
            "preview_url",
            "screenshot_url",
            "asset_url",
          ]) || assetUrl,
      };
    })
    .sort((a, b) => a.rank - b.rank);
}

const originalQuery = computed(() => {
  const value = firstValue(
    [asRecord(primaryPayload.value.input), ...payloads.value],
    ["original_question", "question", "query"],
  );
  return value === undefined ? props.question || "未记录" : displayValue(value);
});
const rules = computed(() => {
  const rows: FieldRow[] = [];
  for (const payload of payloads.value) {
    rows.push(...fields(payload.effective_config));
    rows.push(...fields(payload.rules));
    rows.push(
      ...fields(payload.details, [
        "candidates",
        "results",
        "hits",
        "documents",
        "chunks",
        "retrieval_before_rerank_candidates",
        "rerank_after_candidates",
        "rerank_details",
        "final_evidence_set",
        "evidences",
      ]),
    );
  }
  return rows.filter(
    (row, index, self) =>
      self.findIndex(
        (item) => item.label === row.label && item.value === row.value,
      ) === index,
  );
});
const recallRows = computed(() =>
  normalizeCandidates(
    collectCandidates(
      ["output", "details"],
      [
        "retrieval_before_rerank_candidates",
        "candidates",
        "results",
        "hits",
        "documents",
        "chunks",
      ],
    ),
  ),
);
const rerankInputRows = computed(() =>
  normalizeCandidates(
    collectCandidates(
      ["input"],
      [
        "retrieval_before_rerank_candidates",
        "candidates",
        "results",
        "hits",
        "documents",
        "chunks",
      ],
    ),
  ),
);
const rerankOutputRows = computed(() =>
  normalizeCandidates(
    collectCandidates(
      ["output"],
      [
        "rerank_after_candidates",
        "candidates",
        "results",
        "hits",
        "documents",
        "chunks",
      ],
    ),
    true,
  ),
);
const evidenceRows = computed(() =>
  normalizeCandidates(
    collectCandidates(
      ["input", "output", "details"],
      [
        "final_evidence_set",
        "evidences",
        "evidence",
        "selected_candidates",
        "candidates",
        "results",
      ],
    ),
    true,
  ),
);
const visualRows = computed(() =>
  recallRows.value.filter(
    (row) =>
      row.imageUrl || /vision|visual|image|ocr|视觉|图片/i.test(row.channel),
  ),
);
function chooseStage(stage: string): void {
  activeStage.value = stage;
  activeEventId.value = null;
}
function chooseEvent(event: QADebuggerEvent): void {
  activeStage.value = event.business_stage;
  activeEventId.value = event.event_id;
}
function toggleStage(stage: string): void {
  const next = new Set(collapsedStages.value);
  if (next.has(stage)) next.delete(stage);
  else next.add(stage);
  collapsedStages.value = next;
}
function chooseAndToggleStage(stage: string, hasChildren: boolean): void {
  chooseStage(stage);
  if (hasChildren) toggleStage(stage);
}
function toggleDataSection(event: MouseEvent): void {
  const header = (event.target as HTMLElement).closest("header");
  const section = header?.parentElement;
  if (!header || !section || header.parentElement !== section) return;
  if (
    !section.matches(
      "section, .step-data-grid>article, .planning-grid>article, .two-columns>article, .intent-details>article",
    )
  )
    return;
  section.classList.toggle("data-collapsed");
}
function setCandidateFilter(
  value: "all" | "evidence" | "dropped" | "cited",
): void {
  candidateFilter.value = value;
}
const eventName = (event: QADebuggerEvent): string =>
  displayValue(
    asRecord(event.payload?.details).step ||
      event.payload?.step ||
      stageNames[event.business_stage] ||
      event.business_stage,
  );
const stepContext = computed(() => {
  const payload = activeEvent.value?.payload || {};
  const input = asRecord(payload.input);
  const output = asRecord(payload.output);
  const details = asRecord(payload.details);
  const stage = activeEvent.value?.business_stage;
  const name = activeEvent.value ? eventName(activeEvent.value) : "";
  const memory = [asRecord(details.memory_topic_shift)];
  const understanding = [
    asRecord(details.question_understanding),
    asRecord(details.query_profile),
    asRecord(details.policy_resolution),
  ];
  const retrieval = [asRecord(details.retrieval_plan)];
  const evidence = [
    asRecord(details.evidence_judgement),
    asRecord(details.evidence_evaluation),
    asRecord(details.answer_policy_decision),
  ];
  const preferred =
    name.includes("记忆") || name.includes("上下文")
      ? memory
      : stage === "evidence_judgment"
        ? evidence
        : stage === "retrieval_planning"
          ? retrieval
          : understanding;
  return {
    payload,
    input,
    output,
    details,
    objects: [
      ...preferred,
      details,
      asRecord(details.model_route),
      output,
      payload,
      input,
      ...understanding,
      ...retrieval,
      ...evidence,
      ...memory,
      asRecord(runtimeRaw.value.reranker_runtime),
      asRecord(runtimeRaw.value.sensitive_filter),
      runtimeRaw.value,
      terminalResult.value,
    ],
  };
});
function selectedRows(definitions: Array<[string, string[]]>): FieldRow[] {
  return definitions
    .map(([label, keys]) => ({
      label,
      value: displayValue(firstValue(stepContext.value.objects, keys)),
    }))
    .filter((row) => row.value !== "未记录" && row.value !== "");
}
const stepSummary = computed(() => {
  if (!activeEvent.value) return "";
  const name = eventName(activeEvent.value);
  const { details, payload } = stepContext.value;
  if (
    activeEvent.value.business_stage === "reranking" &&
    runtimeRaw.value.reranker_used === true
  )
    return "流程没有进入独立重排节点，但重排已在检索阶段内部完成。下方展示内部重排的真实数据。";
  if (
    activeEvent.value.business_stage === "sensitive_filtering" &&
    Object.keys(asRecord(runtimeRaw.value.sensitive_filter)).length
  )
    return "流程没有进入独立过滤节点，但答案返回前已经完成敏感内容检查。下方展示真实检查结果。";
  if (activeEvent.value.event_type.includes("skipped"))
    return `该步骤没有单独执行：${translateValue(String(payload.reason || "当前执行路线不需要进入此步骤"))}`;
  if (name.includes("意图"))
    return `系统将问题识别为“${displayValue(details.intent || payload.intent || "知识问答")}”，并决定${details.skip_retrieval === true ? "直接回答" : "先查询知识库再回答"}。`;
  if (name.includes("记忆") || name.includes("上下文"))
    return details.memory_effective_question ===
      details.memory_original_question
      ? "没有使用历史对话改写本次问题。"
      : "系统结合历史对话补全了本次问题。";
  if (name.includes("拆解"))
    return `系统将问题整理为 ${Array.isArray(details.sub_queries) ? details.sub_queries.length : 0} 个可独立检索的问题。`;
  if (activeEvent.value.business_stage === "retrieval_planning")
    return `系统选择 ${Array.isArray(details.planned_retrievers) ? details.planned_retrievers.length : 0} 种检索方式查找相关知识。`;
  if (activeEvent.value.business_stage === "multi_route_recall")
    return `检索完成，共形成 ${arraysFrom(runtimeRaw.value, ["retrieval_before_rerank_candidates"]).length} 条候选知识。`;
  if (activeEvent.value.business_stage === "evidence_judgment")
    return displayValue(
      asRecord(details.evidence_judgement).reason ||
        asRecord(details.evidence_evaluation).reason ||
        asRecord(details.answer_policy_decision).reason ||
        "证据判断完成",
    );
  if (activeEvent.value.business_stage === "answer_generation")
    return details.answer_preview
      ? "答案已经根据最终证据生成。"
      : "本步骤完成回答前的状态准备。";
  if (activeEvent.value.business_stage === "result_return")
    return "答案和引用资料已经返回给用户。";
  return `${eventName(activeEvent.value)}已完成。`;
});
const stepDisplayStatus = computed(() => {
  if (!activeEvent.value) return "";
  if (
    activeEvent.value.business_stage === "reranking" &&
    runtimeRaw.value.reranker_used === true
  )
    return "内部完成";
  if (
    activeEvent.value.business_stage === "sensitive_filtering" &&
    Object.keys(asRecord(runtimeRaw.value.sensitive_filter)).length
  )
    return "内部完成";
  return eventStatus(activeEvent.value.event_type);
});
const stepSections = computed<StepSection[]>(() => {
  if (!activeEvent.value) return [];
  const name = eventName(activeEvent.value);
  const stage = activeEvent.value.business_stage;
  const sections: StepSection[] = [];
  const add = (
    title: string,
    description: string,
    definitions: Array<[string, string[]]>,
    emptyText: string,
  ) =>
    sections.push({
      title,
      description,
      rows: selectedRows(definitions),
      emptyText,
    });
  if (stage === "question_entry") {
    add(
      "用户提交了什么",
      "本次问答的原始请求。",
      [
        ["原始问题", ["question"]],
        ["问答场景", ["chat_type"]],
        ["运行方式", ["mode"]],
        ["会话编号", ["session_id"]],
        ["消息编号", ["user_message_id"]],
      ],
      "没有记录请求信息",
    );
    add(
      "系统做了什么",
      "建立本次问答记录，供后续所有步骤关联。",
      [
        ["处理状态", ["status"]],
        ["Trace编号", ["trace_id"]],
      ],
      "请求已接收，未记录其他处理信息",
    );
  } else if (name.includes("记忆") || name.includes("上下文")) {
    add(
      "问题处理前后",
      "确认历史对话有没有改变本次问题。",
      [
        ["用户原始问题", ["memory_original_question", "original_question"]],
        [
          "结合上下文后的问题",
          ["memory_effective_question", "effective_question"],
        ],
        ["引用的历史信息", ["memory_referenced_context_ids"]],
      ],
      "没有记录问题改写",
    );
    add(
      "为什么这样处理",
      "说明是否使用历史对话以及判断依据。",
      [
        ["上下文使用方式", ["memory_trigger_mode"]],
        ["判断依据", ["memory_decision_reason"]],
        ["是否切换话题", ["strong"]],
        ["话题判断原因", ["reason"]],
      ],
      "没有记录上下文判断依据",
    );
  } else if (name.includes("拆解")) {
    add(
      "需要处理的问题",
      "查看原问题被拆成了哪些可检索问题。",
      [
        ["用户问题", ["memory_effective_question", "question"]],
        ["拆分后的问题", ["sub_queries"]],
        ["问题数量", ["sub_query_total", "sub_query_count"]],
      ],
      "本次问题没有拆分",
    );
    add(
      "拆解方式",
      "查看负责拆解的模型和执行情况。",
      [
        ["执行方式", ["implementation"]],
        ["使用模型", ["model_name", "model"]],
        ["处理耗时", ["elapsed_ms"]],
      ],
      "没有记录拆解配置",
    );
  } else if (stage === "question_understanding") {
    add(
      "系统在理解什么",
      "本步骤使用的问题和问答范围。",
      [
        [
          "用户问题",
          ["memory_original_question", "original_question", "question"],
        ],
        [
          "结合上下文后的问题",
          ["memory_effective_question", "effective_question"],
        ],
        ["问答场景", ["chat_type"]],
      ],
      "没有记录问题正文",
    );
    add(
      "如何进行判断",
      "参与识别的规则、模型和冲突解决方式。",
      [
        ["执行方式", ["implementation"]],
        ["使用模型", ["model_name", "model"]],
        ["识别规则", ["resolution_rule"]],
        ["判断依据", ["reason"]],
        ["处理耗时", ["elapsed_ms"]],
      ],
      "没有记录独立判断规则",
    );
    add(
      "最终理解结果",
      "这些结论将决定后续如何检索和回答。",
      [
        ["问题类型", ["resolved_task_type", "task_type", "query_type"]],
        ["回答形式", ["resolved_answer_shape", "answer_shape"]],
        ["知识范围", ["resolved_knowledge_scope", "knowledge_scope"]],
        ["回答策略", ["resolved_answer_policy", "answer_policy"]],
        ["问答路线", ["route"]],
        ["是否跳过检索", ["skip_retrieval"]],
        ["识别置信度", ["confidence"]],
      ],
      "本步骤没有形成新的识别结论",
    );
  } else if (stage === "retrieval_planning") {
    add(
      "准备检索什么",
      "系统实际用于查找知识的问题。",
      [
        [
          "检索问题",
          ["memory_effective_question", "effective_question", "query"],
        ],
        ["问题类型", ["resolved_task_type", "query_type"]],
        ["知识范围", ["resolved_knowledge_scope", "knowledge_scope"]],
      ],
      "没有记录检索问题",
    );
    add(
      "准备怎样检索",
      "本次选择的检索渠道和备用方案。",
      [
        ["计划使用的方式", ["planned_retrievers", "selected_retrievers"]],
        ["主检索方式", ["primary_retriever"]],
        ["未使用的方式", ["skipped_retrievers"]],
        ["备用方案", ["fallback_ladder"]],
        ["规划依据", ["reason"]],
      ],
      "没有记录检索策略",
    );
    add(
      "计划取多少数据",
      "检索和筛选阶段的数量上限。",
      [
        ["初始候选上限", ["candidate_k"]],
        ["重排保留上限", ["rerank_top_k"]],
        ["证据判断上限", ["eval_top_k"]],
        ["回答证据上限", ["answer_top_k"]],
      ],
      "没有记录数量配置",
    );
  } else if (stage === "multi_route_recall") {
    add(
      "实际检索了什么",
      "真实执行的检索问题和知识范围。",
      [
        [
          "检索问题",
          ["memory_effective_question", "effective_question", "query"],
        ],
        ["检索范围", ["query_scope"]],
        ["实际执行方式", ["executed_retrievers"]],
      ],
      "没有记录实际检索问题",
    );
    add(
      "各检索方式表现",
      "直接查看命中数量、最高分、耗时和超时情况。",
      [
        ["命中数量", ["retriever_hits"]],
        ["最高相关度", ["retriever_top_scores"]],
        ["执行耗时", ["retriever_elapsed_ms"]],
        ["超时情况", ["retriever_timeouts"]],
        ["是否使用备用方案", ["fallback_used"]],
      ],
      "没有记录各检索方式的执行情况",
    );
    add(
      "召回结果",
      "候选原文请在阶段汇总页查看。",
      [
        ["召回候选数量", ["candidate_k"]],
        ["最终形成证据摘要", ["evidence"]],
        ["视觉资料数量", ["visual_asset_count"]],
      ],
      "没有记录召回结果",
    );
  } else if (stage === "reranking") {
    add(
      "为什么需要重排",
      "对召回候选重新计算相关性并筛选。",
      [
        ["输入候选数量", ["candidate_count"]],
        ["计划保留数量", ["rerank_top_k"]],
      ],
      "没有记录重排规模",
    );
    add(
      "实际如何执行",
      "显示真实模型、超时和降级情况。",
      [
        ["服务来源", ["provider"]],
        ["使用模型", ["model_name"]],
        ["实际后端", ["backend"]],
        ["是否降级", ["fallback_used"]],
        ["执行耗时", ["rerank_elapsed_ms"]],
      ],
      "没有记录重排执行信息",
    );
    add(
      "重排结果",
      "排名变化和淘汰情况请在候选知识流转中查看。",
      [
        ["重排后数量", ["answer_context_count"]],
        ["是否使用重排器", ["reranker_used"]],
      ],
      "没有记录重排结果",
    );
  } else if (stage === "evidence_judgment") {
    add(
      "判断哪些资料",
      "本步骤基于候选证据判断能否回答。",
      [
        ["参与判断的证据", ["evidence"]],
        ["强证据数量", ["strong_evidence_count"]],
        ["弱证据数量", ["weak_evidence_count"]],
      ],
      "没有记录参与判断的证据",
    );
    add(
      "使用什么标准",
      "检查相关性、支持程度、冲突和缺失信息。",
      [
        ["相关程度", ["relevance"]],
        ["支持程度", ["support_level"]],
        ["是否冲突", ["conflict"]],
        ["缺失信息", ["missing_aspects"]],
        ["风险等级", ["risk"]],
      ],
      "没有记录判断标准",
    );
    add(
      "最后能不能回答",
      "展示证据充分性和回答策略。",
      [
        ["证据是否充分", ["enough"]],
        ["证据状态", ["evidence_status"]],
        ["判断置信度", ["confidence"]],
        ["是否需要补充检索", ["should_retry"]],
        ["允许怎样回答", ["action"]],
        ["结论依据", ["reason"]],
      ],
      "没有记录证据判断结论",
    );
  } else if (stage === "answer_generation") {
    add(
      "答案依据",
      "回答生成时可使用的问题和证据。",
      [
        ["用户问题", ["memory_effective_question", "question"]],
        ["最终证据", ["evidence"]],
        ["证据状态", ["evidence_status"]],
      ],
      "没有记录答案依据",
    );
    add(
      "如何生成答案",
      "本次真实使用的模型和回答策略。",
      [
        ["使用模型", ["model_name", "model"]],
        ["模型服务来源", ["provider", "source"]],
        ["回答策略", ["resolved_answer_policy", "answer_policy"]],
        ["最大生成长度", ["max_tokens"]],
        ["生成耗时", ["elapsed_ms"]],
      ],
      "没有记录答案生成配置",
    );
    add(
      "生成了什么",
      "展示本步骤产生的答案正文。",
      [
        ["生成答案", ["answer_preview", "answer"]],
        ["回答类型", ["answer_type"]],
      ],
      "本步骤没有生成答案正文",
    );
  } else if (stage === "sensitive_filtering") {
    add(
      "检查什么内容",
      "返回用户前需要检查的答案。",
      [["检查前内容", ["before_content"]]],
      "没有记录检查前内容",
    );
    add(
      "检查规则和结果",
      "查看是否命中规则以及采取的处理动作。",
      [
        ["处理动作", ["action"]],
        ["命中规则", ["matched_rule_codes"]],
        ["脱敏类型", ["redaction_types"]],
        ["处理数量", ["redaction_count"]],
      ],
      "没有命中安全规则",
    );
    add(
      "最终允许返回的内容",
      "确认安全处理有没有改变答案。",
      [["检查后内容", ["after_content"]]],
      "没有记录检查后内容",
    );
  } else if (stage === "result_return") {
    add(
      "返回给用户的内容",
      "用户最终实际看到的答案。",
      [
        ["最终答案", ["answer"]],
        ["回答类型", ["answer_type"]],
        ["回答消息编号", ["assistant_message_id"]],
      ],
      "没有记录返回答案",
    );
    add(
      "答案附带的信息",
      "用于核验答案范围、证据和脱敏情况。",
      [
        ["证据状态", ["evidence_status"]],
        ["检索范围", ["query_scope"]],
        ["实际检索方式", ["used_retrievers"]],
        ["是否基于知识库", ["kb_grounded"]],
        ["是否拒绝回答", ["refused"]],
        ["是否发生脱敏", ["redacted"]],
      ],
      "没有记录返回附加信息",
    );
  }
  return sections;
});
const lifecycleRows = computed<LifecycleRow[]>(() => {
  const recalled = normalizeCandidates(
    arraysFrom(runtimeRaw.value, ["retrieval_before_rerank_candidates"]),
  );
  const reranked = normalizeCandidates(
    arraysFrom(runtimeRaw.value, ["rerank_after_candidates"]),
    true,
  );
  const final = normalizeCandidates(
    arraysFrom(terminalResult.value, ["evidences", "evidence"]),
    true,
  );
  const citations = Array.isArray(terminalResult.value.citations)
    ? terminalResult.value.citations.map(asRecord)
    : [];
  const citedRanks = new Set(
    [
      ...String(terminalResult.value.answer || props.answer || "").matchAll(
        /\[(\d+)\]/g,
      ),
    ].map((match) => Number(match[1])),
  );
  const ids = new Set(
    [...recalled, ...reranked, ...final].map((row) => row.key),
  );
  return [...ids]
    .map((key) => {
      const recall = recalled.find((row) => row.key === key);
      const rerank = reranked.find((row) => row.key === key);
      const evidence = final.find((row) => row.key === key);
      const base = evidence || rerank || recall!;
      return {
        ...base,
        recallRank: recall?.rank,
        recallScore: recall?.score,
        rerankRank: rerank?.rank,
        rerankScore: rerank?.score,
        inEvidence: Boolean(evidence),
        cited:
          citations.some((item) => String(item.chunk_id ?? item.id) === key) ||
          Boolean(evidence && citedRanks.has(evidence.rank)),
      };
    })
    .sort((a, b) => (a.recallRank ?? 999) - (b.recallRank ?? 999));
});
const diagnosisItems = computed(() => {
  const items: Array<{
    level: "success" | "warning" | "danger";
    title: string;
    detail: string;
    stage: string;
  }> = [];
  const recallCount = lifecycleRows.value.filter(
    (row) => row.recallRank,
  ).length;
  const rerankCount = lifecycleRows.value.filter(
    (row) => row.rerankRank,
  ).length;
  const evidenceCount = lifecycleRows.value.filter(
    (row) => row.inEvidence,
  ).length;
  if (!recallCount)
    items.push({
      level: "danger",
      title: "没有召回知识",
      detail: "检索没有返回候选内容，答案存在无依据生成风险。",
      stage: "multi_route_recall",
    });
  else
    items.push({
      level: "success",
      title: `召回 ${recallCount} 条候选知识`,
      detail: "可以继续检查相关资料是否进入重排和最终证据。",
      stage: "multi_route_recall",
    });
  const runtime = asRecord(runtimeRaw.value.reranker_runtime);
  if (runtime.fallback_used === true)
    items.push({
      level: "warning",
      title: "重排发生降级",
      detail: `真实重排服务未成功，改用${displayValue(runtime.backend || "备用算法")}；${rerankCount} 条内容进入下一阶段。`,
      stage: "reranking",
    });
  const judgement = asRecord(runtimeRaw.value.evidence_judgement);
  items.push({
    level: judgement.enough === true ? "success" : "danger",
    title: judgement.enough === true ? "系统判断证据充分" : "系统判断证据不足",
    detail: displayValue(
      judgement.reason || `最终保留 ${evidenceCount} 条证据。`,
    ),
    stage: "evidence_judgment",
  });
  items.push({
    level: "warning",
    title: "答案事实尚未自动逐句核验",
    detail:
      "当前只能人工对照答案和证据，不能自动确认每个数值与结论是否有原文支持。",
    stage: "answer_generation",
  });
  return items;
});
const visibleLifecycleRows = computed(() =>
  lifecycleRows.value.filter((row) => {
    if (candidateFilter.value === "evidence" && !row.inEvidence) return false;
    if (candidateFilter.value === "dropped" && row.rerankRank) return false;
    if (candidateFilter.value === "cited" && !row.cited) return false;
    const keyword = candidateKeyword.value.trim().toLowerCase();
    return (
      !keyword ||
      `${row.source} ${row.location} ${row.content}`
        .toLowerCase()
        .includes(keyword)
    );
  }),
);
const overallDiagnosis = computed(() => {
  if (
    !lifecycleRows.value.some((row) => row.recallRank) ||
    !lifecycleRows.value.some((row) => row.inEvidence)
  )
    return {
      level: "danger",
      label: "高风险",
      title: "答案缺少可验证的知识依据",
    };
  if (
    props.feedbackStatus === "dislike" ||
    asRecord(runtimeRaw.value.reranker_runtime).fallback_used === true
  )
    return {
      level: "warning",
      label: "需要复核",
      title:
        props.feedbackStatus === "dislike"
          ? "用户对答案给出负面反馈"
          : "执行过程发生降级",
    };
  return {
    level: "success",
    label: "基本正常",
    title: "当前 Trace 未发现明显执行缺口",
  };
});
const intentDetails = computed(() =>
  payloads.value.map((payload) => asRecord(payload.details)),
);
const intentObjects = computed(() => [
  ...payloads.value.map((payload) => asRecord(payload.output)),
  ...intentDetails.value.map((details) =>
    asRecord(details.question_understanding),
  ),
  ...intentDetails.value.map((details) => asRecord(details.query_profile)),
  ...intentDetails.value.map((details) => asRecord(details.policy_resolution)),
  ...intentDetails.value,
]);
const intentConclusions = computed<FieldRow[]>(() => {
  const definitions: Array<[string, string[]]> = [
    [
      "问题类型",
      [
        "resolved_task_type",
        "task_type",
        "query_type",
        "intent_type",
        "intent",
      ],
    ],
    ["回答方式", ["resolved_answer_shape", "answer_shape"]],
    ["回答策略", ["resolved_answer_policy", "answer_policy"]],
    ["知识范围", ["resolved_knowledge_scope", "knowledge_scope"]],
    ["问答路线", ["route"]],
    ["识别置信度", ["confidence"]],
  ];
  return definitions
    .map(([label, keys]) => ({
      label,
      value: displayValue(firstValue(intentObjects.value, keys)),
    }))
    .filter((row) => row.value !== "未记录");
});
const intentReasons = computed(() => {
  const reasons: string[] = [];
  const objects = intentObjects.value;
  const explicitReason = firstValue(objects, [
    "reason",
    "decision_reason",
    "conflict_reason",
  ]);
  if (explicitReason) reasons.push(displayValue(explicitReason));
  const exact = firstValue(objects, ["need_exact_term", "has_exact_token"]);
  if (exact === true) reasons.push("问题包含需要精确匹配的术语或参数。");
  const visual = firstValue(objects, ["need_visual_asset"]);
  if (visual === true) reasons.push("回答可能依赖图纸、表格或页面截图。");
  const page = firstValue(objects, ["need_page_location"]);
  if (page === true) reasons.push("答案需要能够定位到具体文档页。");
  const graph = firstValue(objects, ["need_graph_reasoning"]);
  if (graph === true) reasons.push("问题需要结合知识关系进行推理。");
  const conflict = firstValue(objects, ["conflict_detected"]);
  if (conflict === true)
    reasons.push("不同识别结果存在冲突，系统已通过策略规则完成统一。");
  const resolution = firstValue(objects, ["resolution_rule"]);
  if (resolution) reasons.push(`采用的统一规则：${displayValue(resolution)}`);
  const direct = firstValue(objects, ["skip_retrieval"]);
  reasons.push(
    direct === true
      ? "系统判断无需查询知识库，可直接回答。"
      : "系统判断需要查询知识库后再回答。",
  );
  return [...new Set(reasons)];
});
const queryEvolution = computed(() => {
  const rows: Array<{ label: string; content: string }> = [];
  const original = firstValue(
    [...intentDetails.value, ...payloads.value],
    ["memory_original_question", "original_question", "question"],
  );
  const effective = firstValue(intentDetails.value, [
    "memory_effective_question",
    "effective_question",
  ]);
  if (original)
    rows.push({ label: "用户原始问题", content: displayValue(original) });
  if (effective && effective !== original)
    rows.push({
      label: "结合上下文后的问题",
      content: displayValue(effective),
    });
  const rewrites = firstValue(intentObjects.value, ["query_rewrites"]);
  if (Array.isArray(rewrites))
    rewrites.forEach((item, index) =>
      rows.push({
        label: `检索改写 ${index + 1}`,
        content: displayValue(item),
      }),
    );
  const subQueries = firstValue(intentDetails.value, ["sub_queries"]);
  if (Array.isArray(subQueries))
    subQueries.forEach((item, index) =>
      rows.push({
        label: `拆分问题 ${index + 1}`,
        content: displayValue(item),
      }),
    );
  return rows;
});
const planningDetails = computed(() =>
  payloads.value.map((payload) => asRecord(payload.details)),
);
const planningObjects = computed(() => [
  runtimeRaw.value,
  ...payloads.value.map((payload) => asRecord(payload.output)),
  ...planningDetails.value.map((details) => asRecord(details.retrieval_plan)),
  ...planningDetails.value,
]);
const planningQuery = computed(() => {
  const value = firstValue(
    [
      ...payloads.value.map((payload) => asRecord(payload.input)),
      ...planningDetails.value,
      ...planningObjects.value,
    ],
    ["effective_question", "query", "question", "memory_effective_question"],
  );
  return value === undefined ? originalQuery.value : displayValue(value);
});
const planningChannels = computed(() => {
  const planned = firstValue(planningObjects.value, [
    "selected_retrievers",
    "planned_retrievers",
    "retrievers",
  ]);
  const executed = firstValue(planningObjects.value, ["executed_retrievers"]);
  const skipped = firstValue(planningObjects.value, ["skipped_retrievers"]);
  const rows: Array<{ name: string; status: string; reason: string }> = [];
  const plannedList = Array.isArray(planned) ? planned : [];
  const executedList = Array.isArray(executed) ? executed : [];
  const skippedList = Array.isArray(skipped) ? skipped : [];
  const retrieverReasons = asRecord(
    firstValue(planningObjects.value, ["retriever_reasons"]),
  );
  for (const item of [...new Set([...plannedList, ...executedList])])
    rows.push({
      name: translateValue(String(item)),
      status: executedList.includes(item) ? "实际执行" : "计划执行",
      reason: readableRetrieverReason(retrieverReasons[String(item)]),
    });
  const skipReasons = asRecord(
    firstValue(planningObjects.value, ["skip_reasons"]),
  );
  for (const item of skippedList)
    rows.push({
      name: translateValue(String(item)),
      status: "未执行",
      reason: displayValue(skipReasons[String(item)]),
    });
  return rows;
});
const planningParameters = computed<FieldRow[]>(() => {
  const definitions: Array<[string, string[]]> = [
    ["初始候选数量", ["candidate_k", "top_k", "retrieval_limit"]],
    ["重排后保留数量", ["rerank_top_k", "rerank_top_n"]],
    ["进入证据判断数量", ["eval_top_k", "evidence_top_k"]],
    ["最终回答使用数量", ["answer_top_k", "final_top_k"]],
    ["最低相关度", ["score_threshold", "threshold"]],
    ["结果融合方式", ["fusion_algorithm", "algorithm"]],
    ["检索超时", ["timeout_ms"]],
  ];
  return definitions
    .map(([label, keys]) => ({
      label,
      value: displayValue(firstValue(planningObjects.value, keys)),
    }))
    .filter((row) => row.value !== "未记录");
});
const fallbackPlan = computed(() => {
  const value = firstValue(planningObjects.value, [
    "fallback_ladder",
    "fallback_routes",
    "fallback",
  ]);
  return Array.isArray(value)
    ? value.map((item) => translateValue(String(item)))
    : [];
});
const recallGroups = computed<RecallGroup[]>(() => {
  const queryRuns = Array.isArray(runtimeRaw.value.retrieval_sub_queries)
    ? runtimeRaw.value.retrieval_sub_queries.map(asRecord)
    : [];
  const executed = new Set<string>();
  for (const run of queryRuns)
    for (const item of Array.isArray(run.executed_retrievers)
      ? run.executed_retrievers
      : [])
      executed.add(String(item));
  for (const item of Array.isArray(runtimeRaw.value.executed_retrievers)
    ? runtimeRaw.value.executed_retrievers
    : [])
    executed.add(String(item));
  return [...executed].map((key) => {
    const queries: string[] = [];
    const rawCandidates: unknown[] = [];
    const runs: RecallRun[] = [];
    let hits = 0;
    let elapsed = 0;
    let timedOut = false;
    queryRuns.forEach((run, runIndex) => {
      const runRetrievers = Array.isArray(run.executed_retrievers)
        ? run.executed_retrievers.map(String)
        : [];
      if (!runRetrievers.includes(key)) return;
      const query = String(run.query || "").trim();
      if (query && !queries.includes(query)) queries.push(query);
      const runHits = numberValue(asRecord(run.retriever_hits)[key]);
      const runElapsed = numberValue(asRecord(run.retriever_elapsed_ms)[key]);
      const runTimedOut = asRecord(run.retriever_timeouts)[key] === true;
      hits += runHits;
      elapsed += runElapsed;
      timedOut = timedOut || runTimedOut;
      const candidates = Array.isArray(run.candidates) ? run.candidates : [];
      const ownCandidates = candidates.filter(
        (item) => String(asRecord(item).retriever || "") === key,
      );
      rawCandidates.push(...ownCandidates);
      runs.push({
        key: `${key}-${runIndex}`,
        query: query || "Trace未记录Query",
        hits: runHits,
        elapsed: runElapsed,
        timedOut: runTimedOut,
        candidates: normalizeCandidates(ownCandidates),
      });
    });
    if (!rawCandidates.length) {
      const fallbackCandidates = arraysFrom(runtimeRaw.value, [
        "retrieval_before_rerank_candidates",
      ]).filter((item) => String(asRecord(item).retriever || "") === key);
      rawCandidates.push(...fallbackCandidates);
      // 兼容历史 Trace：旧记录只在融合前候选集中保存原始结果，没有写入逐 Query 的 candidates。
      // 单个子查询时可以无歧义地回填到该次运行，否则保留在检索器汇总中，避免伪造 Query 归属。
      if (runs.length === 1 && !runs[0].candidates.length)
        runs[0].candidates = normalizeCandidates(fallbackCandidates);
    }
    return {
      key,
      name: translateValue(key),
      queries,
      hits,
      elapsed,
      timedOut,
      candidates: normalizeCandidates(rawCandidates),
      runs,
    };
  });
});
const activeRecallGroup = computed(
  () =>
    recallGroups.value.find((group) => group.key === selectedRetriever.value) ||
    recallGroups.value[0] ||
    null,
);
const planningReasons = computed(() => {
  const reasons: string[] = [];
  const reason = firstValue(planningObjects.value, [
    "reason",
    "plan_reason",
    "selection_reason",
  ]);
  if (reason) reasons.push(displayValue(reason));
  const needs = asRecord(
    firstValue(planningObjects.value, ["retrieval_needs"]),
  );
  if (needs.vector === true)
    reasons.push("需要理解问题语义，因此启用语义检索。");
  if (needs.keyword === true)
    reasons.push("问题包含明确术语或参数，因此启用关键词检索。");
  if (needs.visual === true || needs.need_visual_asset === true)
    reasons.push("答案可能位于图纸或表格中，因此启用视觉检索。");
  if (!reasons.length && planningChannels.value.length)
    reasons.push(
      `系统计划使用 ${planningChannels.value
        .filter((item) => item.status !== "未执行")
        .map((item) => item.name)
        .join("、")} 获取候选知识。`,
    );
  return reasons;
});
function semanticObjects(): Record<string, unknown>[] {
  const objects: Record<string, unknown>[] = [
    runtimeRaw.value,
    asRecord(runtimeRaw.value.evidence_judgement),
    asRecord(runtimeRaw.value.evidence_evaluation),
    asRecord(runtimeRaw.value.answer_policy_decision),
    asRecord(runtimeRaw.value.sensitive_filter),
    terminalResult.value,
  ];
  for (const payload of payloads.value) {
    const input = asRecord(payload.input);
    const output = asRecord(payload.output);
    const details = asRecord(payload.details);
    objects.push(
      payload,
      input,
      output,
      details,
      asRecord(details.evidence_judgement),
      asRecord(details.evidence_evaluation),
      asRecord(details.answer_policy_decision),
      asRecord(details.model_route),
      asRecord(payload.result),
      asRecord(output.result),
    );
  }
  return objects;
}
function semanticRows(
  definitions: Array<[string, string[]]>,
  objects = semanticObjects(),
): FieldRow[] {
  return definitions
    .map(([label, keys]) => ({
      label,
      value: displayValue(firstValue(objects, keys)),
    }))
    .filter((row) => row.value !== "未记录");
}
const entryRows = computed(() =>
  semanticRows([
    ["问答类型", ["chat_type"]],
    ["运行模式", ["mode"]],
    ["所属项目", ["project_id"]],
    ["会话编号", ["session_id"]],
    ["提问消息编号", ["user_message_id"]],
  ]),
);
const recallMetrics = computed(() =>
  semanticRows([
    ["实际检索方式", ["executed_retrievers", "used_retrievers"]],
    ["各方式命中数量", ["retriever_hits"]],
    ["各方式最高相关度", ["retriever_top_scores"]],
    ["各方式耗时", ["retriever_elapsed_ms"]],
    ["发生超时的方式", ["retriever_timeouts"]],
    ["是否使用备用方案", ["fallback_used"]],
  ]),
);
const rerankRules = computed(() =>
  semanticRows(
    [
      ["重排服务", ["provider"]],
      ["重排模型", ["model", "model_name"]],
      ["实际执行后端", ["backend"]],
      ["是否使用降级方案", ["fallback_used"]],
      ["输入候选数量", ["candidate_count", "input_count"]],
      ["最终保留数量", ["rerank_top_k", "top_k", "top_n"]],
      ["处理耗时", ["rerank_elapsed_ms", "elapsed_ms"]],
    ],
    [
      asRecord(runtimeRaw.value.reranker_runtime),
      runtimeRaw.value,
      ...semanticObjects(),
    ],
  ),
);
const evidenceConclusions = computed(() =>
  semanticRows([
    ["证据是否充分", ["enough"]],
    ["证据状态", ["evidence_status", "status"]],
    ["判断置信度", ["confidence"]],
    ["强证据数量", ["strong_evidence_count"]],
    ["弱证据数量", ["weak_evidence_count"]],
    ["缺失信息", ["missing_aspects"]],
    ["是否需要补充检索", ["should_retry"]],
    ["是否允许有限回答", ["allow_limited_answer"]],
    ["证据是否冲突", ["conflict"]],
    ["风险等级", ["risk"]],
  ]),
);
const evidenceReasons = computed(() => {
  const objects = semanticObjects();
  const result: string[] = [];
  for (const key of ["reason", "evidence_decision_reason", "retry_reason"]) {
    const value = firstValue(objects, [key]);
    if (value) result.push(displayValue(value));
  }
  return [...new Set(result)];
});
const answerSettings = computed(() => {
  const latestObjects = [...payloads.value]
    .reverse()
    .flatMap((payload) => [
      asRecord(asRecord(payload.details).model_route),
      payload,
      asRecord(payload.effective_config),
      asRecord(payload.output),
    ]);
  return semanticRows(
    [
      ["使用模型", ["model", "model_name", "deployment"]],
      ["模型服务来源", ["source", "provider"]],
      ["回答策略", ["answer_policy", "action"]],
      ["证据数量", ["evidence_count"]],
      ["最大生成长度", ["max_tokens"]],
      ["生成随机度", ["temperature"]],
      ["生成耗时", ["elapsed_ms"]],
    ],
    latestObjects,
  );
});
const filterRows = computed(() =>
  semanticRows(
    [
      ["处理动作", ["action"]],
      [
        "命中规则",
        ["matched_rule_codes", "matched_rules", "rule_hits", "hits"],
      ],
      ["脱敏类型", ["redaction_types"]],
      ["脱敏内容数量", ["redaction_count"]],
      ["处理前内容", ["before_content"]],
      ["处理后内容", ["after_content"]],
    ],
    [asRecord(runtimeRaw.value.sensitive_filter)],
  ),
);
const returnRows = computed(() =>
  semanticRows(
    [
      ["回答消息编号", ["assistant_message_id", "message_id"]],
      ["回答类型", ["answer_type"]],
      ["证据状态", ["evidence_status"]],
      ["检索范围", ["query_scope"]],
      ["实际检索方式", ["used_retrievers"]],
      ["是否使用知识库证据", ["kb_grounded"]],
      ["是否拒绝回答", ["refused"]],
      ["是否发生脱敏", ["redacted"]],
      ["脱敏内容数量", ["redaction_count"]],
    ],
    [terminalResult.value, runtimeRaw.value, ...payloads.value],
  ),
);
const embeddedExecutionMessage = computed(() => {
  if (
    activeStage.value === "reranking" &&
    runtimeRaw.value.reranker_used === true
  )
    return "重排实际在“检索召回与数据组装”内部完成；流程编排没有进入独立重排节点。以下展示内部重排的真实输入、输出和运行信息。";
  if (
    activeStage.value === "sensitive_filtering" &&
    Object.keys(asRecord(runtimeRaw.value.sensitive_filter)).length
  )
    return "敏感内容检查实际在答案返回前完成；流程编排没有进入独立过滤节点。以下展示本次检查的真实处理前后内容。";
  return "";
});
const generatedAnswer = computed(() =>
  displayValue(
    firstValue(
      [asRecord(primaryPayload.value.output), primaryPayload.value],
      ["answer", "content", "response", "final_answer"],
    ),
  ) !== "未记录"
    ? displayValue(
        firstValue(
          [asRecord(primaryPayload.value.output), primaryPayload.value],
          ["answer", "content", "response", "final_answer"],
        ),
      )
    : props.answer || "未记录生成答案正文",
);
const overviewEvidence = computed(() => {
  for (const payload of allPayloads.value) {
    const details = asRecord(payload.details);
    const items = arraysFrom(details, ["final_evidence_set", "evidences"]);
    if (items.length) return normalizeCandidates(items, true);
  }
  return normalizeCandidates(
    arraysFrom(terminalResult.value, ["evidences", "evidence"]),
    true,
  );
});
const reproducibleConfig = computed(() => {
  const rows: FieldRow[] = [];
  for (const payload of allPayloads.value) {
    rows.push(...fields(payload.effective_config));
    const details = asRecord(payload.details);
    rows.push(...fields(details.model_route));
    rows.push(...fields(details.retrieval_plan));
  }
  return rows
    .filter(
      (row, index, self) =>
        self.findIndex(
          (item) => item.label === row.label && item.value === row.value,
        ) === index,
    )
    .slice(0, 18);
});
const issueSignals = computed(() => {
  const issues: string[] = [];
  if (props.result.trace.completeness_status !== "complete")
    issues.push("执行记录不完整，当前结论可能缺少处理上下文。");
  for (const item of stageItems.value)
    if (item.warning) issues.push(`${item.name}存在失败、跳过或降级事件。`);
  if (!overviewEvidence.value.length)
    issues.push("未记录最终证据集合，无法验证答案依据。");
  const slowest = [...stageItems.value].sort(
    (a, b) => b.elapsed - a.elapsed,
  )[0];
  if (slowest?.elapsed > 1500)
    issues.push(
      `${slowest.name}耗时 ${slowest.elapsed} 毫秒，是本次问答的主要耗时点。`,
    );
  return issues;
});
const optimizationHints = computed(() => {
  const hints: string[] = [];
  if (!overviewEvidence.value.length)
    hints.push("在证据判断节点补录最终证据及选择/拒绝原因。");
  if (
    stageItems.value.find((item) => item.stage === "multi_route_recall")
      ?.warning
  )
    hints.push("检查失败的召回通道、超时配置与降级策略。");
  if (props.result.trace.completeness_status !== "complete")
    hints.push("先检查后台记录任务和缺失环节，再进行质量判断。");
  if (!reproducibleConfig.value.length)
    hints.push("补录模型路由、Prompt 版本和运行时生效参数。");
  return hints.length
    ? hints
    : [
        "本次执行记录未发现明确异常；可结合用户反馈继续评估召回相关性和答案准确性。",
      ];
});
function formatScore(value?: number) {
  return value === undefined ? "未记录" : value.toFixed(4);
}
</script>

<template>
  <div class="trace-layout">
    <aside class="node-sidebar">
      <header>
        <small>TRACE 编号</small>
        <h3>处理流程</h3>
        <p>{{ result.trace.trace_id }}</p>
      </header>
      <button
        :class="{ active: activeStage === 'overview' && !activeEventId }"
        @click="chooseStage('overview')"
      >
        <strong>00</strong><i /><span
          ><b>诊断结论</b><small>风险 · 数据流转 · 证据</small></span
        ><em>总览</em>
      </button>
      <section
        v-for="(item, index) in stageItems"
        :key="item.stage"
        class="stage-tree"
      >
        <button
          :class="[
            {
              active: activeStage === item.stage && !activeEventId,
              warning: item.warning,
              missing: !item.summary,
              collapsed: collapsedStages.has(item.stage),
              expandable: item.events.length,
            },
          ]"
          @click="chooseAndToggleStage(item.stage, Boolean(item.events.length))"
        >
          <strong>{{ String(index + 1).padStart(2, "0") }}</strong
          ><i /><span
            ><b>{{ item.name }}</b
            ><small>{{ item.events.length }} 个执行步骤</small></span
          ><em>{{
            item.elapsed
              ? `${item.elapsed}ms`
              : item.summary
                ? "完成"
                : "未执行"
          }}</em>
        </button>
        <div
          v-if="item.events.length && !collapsedStages.has(item.stage)"
          class="step-tree"
        >
          <button
            v-for="event in item.events"
            :key="event.event_id"
            :class="{ active: activeEventId === event.event_id }"
            @click="chooseEvent(event)"
          >
            <i /><span
              ><b>{{ eventName(event) }}</b
              ><small
                >第 {{ event.sequence }} 步 ·
                {{ eventStatus(event.event_type) }}</small
              ></span
            >
          </button>
        </div>
      </section>
      <footer>
        <t-tag
          :theme="result.trace.status === 'success' ? 'success' : 'warning'"
          >{{ translateValue(result.trace.status) }}</t-tag
        ><span>{{ translateValue(result.trace.completeness_status) }}</span
        ><span>{{ result.events_total }} 条记录</span>
      </footer>
    </aside>

    <main class="node-data" @click="toggleDataSection">
      <header class="node-title">
        <div>
          <small>{{
            activeEvent
              ? "真实执行步骤"
              : activeStage === "overview"
                ? "本次问答"
                : "业务阶段"
          }}</small>
          <h2>
            {{
              activeEvent
                ? eventName(activeEvent)
                : activeStage === "overview"
                  ? "问答诊断"
                  : stageNames[activeStage]
            }}
          </h2>
          <p>
            {{
              activeEvent
                ? "仅展示该步骤实际记录的输入、规则、输出和运行状态。"
                : activeStage === "overview"
                  ? "先判断风险，再沿候选知识的数据流转定位问题。"
                  : "查看该业务阶段的汇总数据；也可以从左侧选择具体执行步骤。"
            }}
          </p>
        </div>
        <div>
          <span
            >{{
              activeStage === "overview"
                ? result.events_total
                : activeEvents.length
            }}
            个步骤</span
          ><span
            >耗时
            {{
              activeEvent
                ? numberValue(activeEvent.payload?.elapsed_ms)
                : activeStage === "overview"
                  ? stageItems.reduce((sum, item) => sum + item.elapsed, 0)
                  : stageItems.find((item) => item.stage === activeStage)
                      ?.elapsed || 0
            }}
            毫秒</span
          >
        </div>
      </header>

      <template v-if="activeEvent">
        <section class="step-verdict">
          <div>
            <small>这一步做了什么</small>
            <h3>{{ eventName(activeEvent) }}</h3>
            <p>{{ stepSummary }}</p>
          </div>
          <span
            >{{ stepDisplayStatus }} ·
            {{
              activeEvent.business_stage === "reranking"
                ? numberValue(runtimeRaw.rerank_elapsed_ms)
                : numberValue(activeEvent.payload?.elapsed_ms)
            }}ms</span
          >
        </section>
        <template v-if="activeEvent.business_stage === 'retrieval_planning'">
          <section class="query-compare">
            <article>
              <small>用户原始问题</small>
              <p>{{ originalQuery }}</p>
            </article>
            <i>→</i>
            <article>
              <small>规划后实际用于检索的问题</small>
              <p>{{ planningQuery }}</p>
              <span v-if="planningQuery === originalQuery"
                >本次没有改写问题</span
              >
            </article>
          </section>
          <section class="planning-grid">
            <article>
              <header>
                <h3>规划使用哪些检索器</h3>
                <p>逐个展示是否计划、是否实际执行以及选择原因。</p>
              </header>
              <div class="channel-list">
                <div
                  v-for="channel in planningChannels"
                  :key="`${channel.name}-${channel.status}`"
                  :class="{ skipped: channel.status === '未执行' }"
                >
                  <i /><span
                    ><b>{{ channel.name }}</b
                    ><small
                      >{{ channel.status }} · {{ channel.reason }}</small
                    ></span
                  >
                </div>
              </div>
            </article>
            <article>
              <header>
                <h3>本次检索数量规划</h3>
                <p>各阶段最多处理多少条数据。</p>
              </header>
              <dl>
                <template v-for="row in planningParameters" :key="row.label"
                  ><dt>{{ row.label }}</dt>
                  <dd>{{ row.value }}</dd></template
                >
              </dl>
            </article>
          </section>
        </template>
        <template
          v-else-if="activeEvent.business_stage === 'multi_route_recall'"
        >
          <section class="recall-workbench">
            <header>
              <div>
                <h3>各检索器的 Query 和原始召回数据</h3>
                <p>
                  点击检索器查看每一次 Query 及该 Query 对应的全部原始返回内容。
                </p>
              </div>
              <b>{{ recallGroups.length }} 个检索器</b>
            </header>
            <nav>
              <button
                v-for="group in recallGroups"
                :key="group.key"
                :class="{ active: activeRecallGroup?.key === group.key }"
                @click="selectedRetriever = group.key"
              >
                <span>{{ group.name }}</span
                ><small>{{ group.hits }} 条 · {{ group.elapsed }}ms</small>
              </button>
            </nav>
            <template v-if="activeRecallGroup"
              ><section
                v-for="(run, runIndex) in activeRecallGroup.runs"
                :key="run.key"
                class="retriever-query-run"
              >
                <header>
                  <div>
                    <small
                      >发送给 {{ activeRecallGroup.name }} 的 Query
                      {{ runIndex + 1 }}</small
                    >
                    <p>{{ run.query }}</p>
                  </div>
                  <dl>
                    <div>
                      <dt>召回</dt>
                      <dd>{{ run.hits }}条</dd>
                    </div>
                    <div>
                      <dt>页面已展示</dt>
                      <dd>{{ run.candidates.length }}条</dd>
                    </div>
                    <div>
                      <dt>耗时</dt>
                      <dd>{{ run.elapsed }}ms</dd>
                    </div>
                    <div>
                      <dt>超时</dt>
                      <dd>{{ run.timedOut ? "是" : "否" }}</dd>
                    </div>
                  </dl>
                </header>
                <p
                  v-if="run.hits !== run.candidates.length"
                  class="candidate-count-warning"
                >
                  检索器报告召回 {{ run.hits }} 条，但本条 Trace 只保存了
                  {{ run.candidates.length }} 条原始记录；缺失内容无法从 Trace
                  复现。
                </p>
                <div class="retriever-results">
                  <header>
                    <div>
                      <h3>该 Query 返回的全部原始内容</h3>
                      <p>
                        逐条展示检索器原始返回，不使用重排或最终证据结果回填。
                      </p>
                    </div>
                    <b
                      >展示 {{ run.candidates.length }} / 召回
                      {{ run.hits }} 条</b
                    >
                  </header>
                  <button
                    v-for="row in run.candidates"
                    :key="row.key"
                    @click="selectedCandidate = row"
                  >
                    <strong>第 {{ row.rank }} 名</strong
                    ><img
                      v-if="row.imageUrl"
                      class="recall-preview"
                      :src="row.imageUrl"
                      :alt="`${row.source}视觉资料`"
                    />
                    <div>
                      <header>
                        <b>{{ row.source }} · {{ row.location }}</b
                        ><span>{{ row.channel }}</span>
                      </header>
                    <ChatRichContent class="recall-rich-content" :content="row.content" />
                    </div>
                    <em
                      ><small>原始得分</small>{{ formatScore(row.score) }}</em
                    ></button
                  ><t-empty
                    v-if="!run.candidates.length"
                    :description="`${activeRecallGroup.name} 对该Query没有保存原始内容`"
                  />
                </div>
              </section>
              <t-empty
                v-if="!activeRecallGroup.runs.length"
                description="Trace没有保存该检索器的逐Query运行数据"
            /></template>
          </section>
        </template>
        <section
          v-else
          class="step-data-grid"
          :class="{ 'two-sections': stepSections.length === 2 }"
        >
          <article v-for="section in stepSections" :key="section.title">
            <header>
              <h3>{{ section.title }}</h3>
              <p>{{ section.description }}</p>
            </header>
            <dl>
              <template v-for="row in section.rows" :key="row.label"
                ><dt>{{ row.label }}</dt>
                <dd>{{ row.value }}</dd></template
              >
            </dl>
            <t-empty
              v-if="!section.rows.length"
              :description="section.emptyText"
            />
          </article>
        </section>
      </template>

      <template v-else-if="activeStage === 'overview'">
        <section class="case-summary" :class="overallDiagnosis.level">
          <div>
            <small>本次问答诊断</small>
            <h3>{{ overallDiagnosis.title }}</h3>
            <p v-if="feedbackStatus === 'dislike'">
              用户已明确反馈答案存在问题，应优先核验证据相关性和答案事实支持情况。
            </p>
            <p v-else>根据执行状态、召回数据、重排和最终证据生成的初步判断。</p>
          </div>
          <strong>{{ overallDiagnosis.label }}</strong>
          <dl>
            <div>
              <dt>召回候选</dt>
              <dd>
                {{ lifecycleRows.filter((row) => row.recallRank).length }}
              </dd>
            </div>
            <div>
              <dt>重排保留</dt>
              <dd>
                {{ lifecycleRows.filter((row) => row.rerankRank).length }}
              </dd>
            </div>
            <div>
              <dt>最终证据</dt>
              <dd>
                {{ lifecycleRows.filter((row) => row.inEvidence).length }}
              </dd>
            </div>
            <div>
              <dt>总耗时</dt>
              <dd>
                {{ stageItems.reduce((sum, item) => sum + item.elapsed, 0) }}ms
              </dd>
            </div>
          </dl>
        </section>
        <section class="diagnosis-list">
          <header>
            <h3>诊断结论</h3>
            <p>先看异常和风险，再进入对应步骤核查。</p>
          </header>
          <button
            v-for="item in diagnosisItems"
            :key="item.title"
            :class="item.level"
            @click="chooseStage(item.stage)"
          >
            <i />
            <div>
              <b>{{ item.title }}</b>
              <p>{{ item.detail }}</p>
            </div>
            <span>检查节点 →</span>
          </button>
        </section>
        <section class="lifecycle-table">
          <header>
            <div>
              <h3>候选知识流转</h3>
              <p>同一条知识从召回、重排到最终证据的完整变化。</p>
            </div>
            <b
              >{{ visibleLifecycleRows.length }}/{{
                lifecycleRows.length
              }}
              条</b
            >
          </header>
          <div class="lifecycle-tools">
            <t-input
              v-model="candidateKeyword"
              clearable
              placeholder="搜索文件名、页码或原文"
            />
            <div>
              <button
                v-for="item in candidateFilterOptions"
                :key="item.key"
                :class="{ active: candidateFilter === item.key }"
                @click="setCandidateFilter(item.key)"
              >
                {{ item.label }}
              </button>
            </div>
          </div>
          <div class="lifecycle-head">
            <span>知识来源与原文</span><span>召回</span><span>重排</span
            ><span>最终证据</span><span>答案引用</span>
          </div>
          <button
            v-for="row in visibleLifecycleRows"
            :key="row.key"
            @click="selectedCandidate = row"
          >
            <div>
              <b>{{ row.source }} · {{ row.location }}</b>
              <p>{{ row.content }}</p>
            </div>
            <span
              >{{ row.recallRank ? `第 ${row.recallRank} 名` : "未召回"
              }}<small>{{ formatScore(row.recallScore) }}</small></span
            ><span :class="{ dropped: !row.rerankRank }"
              >{{ row.rerankRank ? `第 ${row.rerankRank} 名` : "已淘汰"
              }}<small v-if="row.rerankRank">{{
                formatScore(row.rerankScore)
              }}</small></span
            ><span :class="{ yes: row.inEvidence }">{{
              row.inEvidence ? "已入选" : "未入选"
            }}</span
            ><span :class="{ yes: row.cited }">{{
              row.cited ? "已引用" : "未引用"
            }}</span></button
          ><t-empty
            v-if="!visibleLifecycleRows.length"
            description="没有符合条件的候选知识"
          />
        </section>
        <section class="answer-review">
          <article>
            <small>用户问题</small>
            <p>{{ question || result.trace.question || "未记录问题" }}</p>
          </article>
          <article>
            <small>最终返回答案</small>
            <p>{{ answer || "未记录答案正文" }}</p>
          </article>
        </section>
      </template>

      <template v-else-if="activeStage === 'question_entry'">
        <section class="entry-card">
          <div>
            <small>用户提交的问题</small>
            <p>{{ originalQuery }}</p>
          </div>
          <span>请求已接收</span>
        </section>
        <section class="readable-card">
          <header>
            <h3>请求信息</h3>
            <p>用于定位本次问答，不参与答案内容判断。</p>
          </header>
          <dl>
            <template v-for="row in entryRows" :key="row.label"
              ><dt>{{ row.label }}</dt>
              <dd>{{ row.value }}</dd></template
            >
          </dl>
          <t-empty
            v-if="!entryRows.length"
            description="本次没有记录请求附加信息"
          />
        </section>
      </template>

      <template v-else-if="activeStage === 'question_understanding'">
        <section class="intent-question">
          <small>系统收到的问题</small>
          <p>{{ originalQuery }}</p>
        </section>
        <section class="intent-conclusion">
          <header>
            <div>
              <h3>系统最终如何理解这个问题</h3>
              <p>这些结论决定后续是否检索、检索什么以及怎样组织答案。</p>
            </div>
            <span>识别结论</span>
          </header>
          <div>
            <article v-for="row in intentConclusions" :key="row.label">
              <small>{{ row.label }}</small
              ><b>{{ row.value }}</b>
            </article>
          </div>
          <t-empty
            v-if="!intentConclusions.length"
            description="本次没有记录可读的意图识别结论"
          />
        </section>
        <section class="intent-details">
          <article>
            <header>
              <h3>为什么这样判断</h3>
              <p>由问题特征和业务规则生成的可解释依据。</p>
            </header>
            <ol>
              <li v-for="reason in intentReasons" :key="reason">
                {{ reason }}
              </li>
            </ol>
            <t-empty
              v-if="!intentReasons.length"
              description="本次没有记录判断依据"
            />
          </article>
          <article>
            <header>
              <h3>问题如何变化</h3>
              <p>查看上下文补全、问题改写和问题拆分。</p>
            </header>
            <div class="query-evolution">
              <div
                v-for="(item, index) in queryEvolution"
                :key="`${item.label}-${index}`"
              >
                <i>{{ index + 1 }}</i
                ><span
                  ><small>{{ item.label }}</small
                  ><b>{{ item.content }}</b></span
                >
              </div>
            </div>
            <t-empty
              v-if="!queryEvolution.length"
              description="问题未发生改写或拆分"
            />
          </article>
        </section>
      </template>

      <template v-else-if="activeStage === 'retrieval_planning'">
        <section class="query-compare">
          <article>
            <small>用户原始问题</small>
            <p>{{ originalQuery }}</p>
          </article>
          <i>→</i>
          <article>
            <small>规划后的检索问题</small>
            <p>{{ planningQuery }}</p>
            <span v-if="planningQuery === originalQuery">本次没有改写问题</span>
          </article>
        </section>
        <section class="planning-flow">
          <article>
            <span>1</span>
            <div>
              <small>检索问题</small><b>{{ planningQuery }}</b>
            </div>
          </article>
          <i>→</i>
          <article>
            <span>2</span>
            <div>
              <small>检索方式</small
              ><b>{{
                planningChannels
                  .filter((item) => item.status !== "未执行")
                  .map((item) => item.name)
                  .join(" + ") || "未记录"
              }}</b>
            </div>
          </article>
          <i>→</i>
          <article>
            <span>3</span>
            <div>
              <small>候选处理</small
              ><b>{{
                planningParameters.find((item) => item.label === "结果融合方式")
                  ?.value || "合并并去重"
              }}</b>
            </div>
          </article>
          <i>→</i>
          <article>
            <span>4</span>
            <div>
              <small>计划输出上限</small
              ><b
                >最多保留
                {{
                  planningParameters.find(
                    (item) => item.label === "重排后保留数量",
                  )?.value || "未记录"
                }}
                条</b
              >
            </div>
          </article>
        </section>
        <section class="planning-grid">
          <article>
            <header>
              <h3>去哪里检索</h3>
              <p>计划使用和实际执行的检索方式。</p>
            </header>
            <div class="channel-list">
              <div
                v-for="channel in planningChannels"
                :key="`${channel.name}-${channel.status}`"
                :class="{ skipped: channel.status === '未执行' }"
              >
                <i /><span
                  ><b>{{ channel.name }}</b
                  ><small
                    >{{ channel.status
                    }}<template
                      v-if="channel.reason && channel.reason !== '未记录'"
                    >
                      · {{ channel.reason }}</template
                    ></small
                  ></span
                >
              </div>
            </div>
            <t-empty
              v-if="!planningChannels.length"
              description="本次没有记录检索方式"
            />
          </article>
          <article>
            <header>
              <h3>取多少、怎样筛选</h3>
              <p>本次实际生效的数量和阈值。</p>
            </header>
            <dl>
              <template v-for="row in planningParameters" :key="row.label"
                ><dt>{{ row.label }}</dt>
                <dd>
                  {{ row.value
                  }}<template v-if="row.label === '检索超时'"> 毫秒</template>
                </dd></template
              >
            </dl>
            <t-empty
              v-if="!planningParameters.length"
              description="本次没有记录检索参数"
            />
          </article>
          <article>
            <header>
              <h3>为什么这样规划</h3>
              <p>根据问题特征形成的检索决策。</p>
            </header>
            <ol>
              <li v-for="reason in planningReasons" :key="reason">
                {{ reason }}
              </li>
            </ol>
            <t-empty
              v-if="!planningReasons.length"
              description="本次没有记录规划依据"
            />
          </article>
          <article>
            <header>
              <h3>失败后怎么办</h3>
              <p>主检索不可用时依次尝试的备用方式。</p>
            </header>
            <div v-if="fallbackPlan.length" class="fallback-list">
              <span
                v-for="(item, index) in fallbackPlan"
                :key="`${item}-${index}`"
                ><i>{{ index + 1 }}</i
                >{{ item }}<b v-if="index < fallbackPlan.length - 1">→</b></span
              >
            </div>
            <t-empty v-else description="本次未配置或未记录备用检索方案" />
          </article>
        </section>
      </template>

      <template v-else-if="activeStage === 'multi_route_recall'">
        <section class="recall-workbench">
          <header>
            <div>
              <h3>按检索器查看召回数据</h3>
              <p>选择检索器，查看它实际收到的 Query 和全部原始候选。</p>
            </div>
            <b>{{ recallGroups.length }} 个检索器</b>
          </header>
          <nav>
            <button
              v-for="group in recallGroups"
              :key="group.key"
              :class="{
                active:
                  (selectedRetriever || recallGroups[0]?.key) === group.key,
              }"
              @click="selectedRetriever = group.key"
            >
              <span>{{ group.name }}</span
              ><small>{{ group.hits }} 条 · {{ group.elapsed }}ms</small>
            </button>
          </nav>
          <template v-if="activeRecallGroup"
            ><section class="retriever-run">
              <div>
                <small>发送给 {{ activeRecallGroup.name }} 的 Query</small>
                <p
                  v-for="(query, index) in activeRecallGroup.queries"
                  :key="`${query}-${index}`"
                >
                  {{ query }}
                </p>
                <p v-if="!activeRecallGroup.queries.length">未记录 Query</p>
              </div>
              <dl>
                <div>
                  <dt>召回数量</dt>
                  <dd>{{ activeRecallGroup.hits }} 条</dd>
                </div>
                <div>
                  <dt>页面已展示</dt>
                  <dd>{{ activeRecallGroup.candidates.length }} 条</dd>
                </div>
                <div>
                  <dt>执行耗时</dt>
                  <dd>{{ activeRecallGroup.elapsed }}ms</dd>
                </div>
                <div>
                  <dt>是否超时</dt>
                  <dd>{{ activeRecallGroup.timedOut ? "是" : "否" }}</dd>
                </div>
              </dl>
            </section>
            <p
              v-if="
                activeRecallGroup.hits !== activeRecallGroup.candidates.length
              "
              class="candidate-count-warning"
            >
              检索器报告召回 {{ activeRecallGroup.hits }} 条，但本条 Trace
              只保存了 {{ activeRecallGroup.candidates.length }} 条原始记录。
            </p>
            <section class="retriever-results">
              <header>
                <div>
                  <h3>{{ activeRecallGroup.name }} 返回的全部原始数据</h3>
                  <p>逐条保留原始文档、页码、正文、视觉预览和该检索器得分。</p>
                </div>
                <b
                  >展示 {{ activeRecallGroup.candidates.length }} / 召回
                  {{ activeRecallGroup.hits }} 条</b
                >
              </header>
              <button
                v-for="row in activeRecallGroup.candidates"
                :key="row.key"
                @click="selectedCandidate = row"
              >
                <strong>第 {{ row.rank }} 名</strong
                ><img
                  v-if="row.imageUrl"
                  class="recall-preview"
                  :src="row.imageUrl"
                  :alt="`${row.source}视觉资料`"
                />
                <div>
                  <header>
                    <b>{{ row.source }} · {{ row.location }}</b
                    ><span>{{ row.channel }}</span>
                  </header>
                  <ChatRichContent class="recall-rich-content" :content="row.content" />
                </div>
                <em
                  ><small>原始得分</small>{{ formatScore(row.score) }}</em
                ></button
              ><t-empty
                v-if="!activeRecallGroup.candidates.length"
                :description="`${activeRecallGroup.name} 本次没有保存原始内容`"
              /></section></template
          ><t-empty v-else description="本次没有记录实际执行的检索器" />
        </section>
        <section v-if="visualRows.length" class="visual-strip">
          <header>
            <h3>召回的视觉资料</h3>
            <span>{{ visualRows.length }} 页</span>
          </header>
          <div>
            <button
              v-for="row in visualRows"
              :key="row.key"
              @click="selectedCandidate = row"
            >
              <img
                v-if="row.imageUrl"
                :src="row.imageUrl"
                alt="视觉资料"
              /><span v-else>未记录预览图</span
              ><b>{{ row.source }} · {{ row.location }}</b
              ><small>{{ formatScore(row.score) }}</small>
            </button>
          </div>
        </section>
      </template>

      <template v-else-if="activeStage === 'reranking'">
        <section class="two-columns rerank-summary">
          <article>
            <header><h3>本次怎样重排</h3></header>
            <dl>
              <template
                v-for="row in rerankRules"
                :key="`${row.label}-${row.value}`"
                ><dt>{{ row.label }}</dt>
                <dd>
                  {{ row.value
                  }}<template v-if="row.label === '处理耗时'"> 毫秒</template>
                </dd></template
              >
            </dl>
            <t-empty
              v-if="!rerankRules.length"
              description="本次没有记录重排参数"
            />
          </article>
          <article>
            <header><h3>筛选结果</h3></header>
            <div class="count-flow">
              <b>{{ rerankInputRows.length }}</b
              ><span>条候选进入重排 →</span><b>{{ rerankOutputRows.length }}</b
              ><span>条内容被保留</span>
            </div>
          </article>
        </section>
        <section class="candidate-list">
          <header>
            <div>
              <h3>重排后保留的内容</h3>
              <p>展示知识原文、排名变化和相关度评分。</p>
            </div>
            <b>{{ rerankOutputRows.length }} 条</b>
          </header>
          <button
            v-for="row in rerankOutputRows"
            :key="row.key"
            @click="selectedCandidate = row"
          >
            <strong>第 {{ row.rank }} 名</strong>
            <div>
              <header>
                <b>{{ row.source }} · {{ row.location }}</b
                ><span v-if="row.previousRank"
                  >重排前第 {{ row.previousRank }} 名</span
                >
              </header>
              <p>{{ row.content }}</p>
            </div>
            <em>相关度 {{ formatScore(row.score) }}</em></button
          ><t-empty
            v-if="!rerankOutputRows.length"
            description="本次记录中没有重排后的候选原文"
          />
        </section>
      </template>

      <template v-else-if="activeStage === 'evidence_judgment'">
        <section class="evidence-verdict">
          <header>
            <div>
              <small>证据判断结论</small>
              <h3>
                {{
                  evidenceConclusions.find(
                    (row) => row.label === "证据是否充分",
                  )?.value ||
                  evidenceConclusions.find((row) => row.label === "证据状态")
                    ?.value ||
                  "未记录明确结论"
                }}
              </h3>
            </div>
            <span>{{ evidenceRows.length }} 条证据</span>
          </header>
          <div>
            <article v-for="row in evidenceConclusions" :key="row.label">
              <small>{{ row.label }}</small
              ><b>{{ row.value }}</b>
            </article>
          </div>
        </section>
        <section class="readable-card">
          <header>
            <h3>为什么得出这个结论</h3>
            <p>证据判断服务记录的业务理由。</p>
          </header>
          <ol class="reason-list">
            <li v-for="reason in evidenceReasons" :key="reason">
              {{ reason }}
            </li>
          </ol>
          <t-empty
            v-if="!evidenceReasons.length"
            description="本次没有记录证据判断理由"
          />
        </section>
        <section class="candidate-list evidence">
          <header>
            <div>
              <h3>判断涉及的原始内容</h3>
              <p>点击查看完整原文。</p>
            </div>
            <b>{{ evidenceRows.length }} 条</b>
          </header>
          <button
            v-for="row in evidenceRows"
            :key="row.key"
            @click="selectedCandidate = row"
          >
            <strong>证据 {{ row.rank }}</strong>
            <div>
              <header>
                <b>{{ row.source }} · {{ row.location }}</b>
              </header>
              <p>{{ row.content }}</p>
            </div>
            <em>{{ formatScore(row.score) }}</em></button
          ><t-empty
            v-if="!evidenceRows.length"
            description="Trace 未记录证据原文"
          />
        </section>
      </template>

      <template v-else-if="activeStage === 'answer_generation'">
        <section class="answer-content">
          <small>模型生成的答案</small>
          <p>{{ generatedAnswer }}</p>
        </section>
        <section class="two-columns">
          <article>
            <header><h3>答案依据</h3></header>
            <div class="answer-source-summary">
              <b>{{ evidenceRows.length }}</b
              ><span>条最终证据进入答案生成</span>
              <p>答案应只陈述这些证据能够支撑的内容。</p>
            </div>
          </article>
          <article>
            <header><h3>本次生成设置</h3></header>
            <dl>
              <template
                v-for="row in answerSettings"
                :key="`${row.label}-${row.value}`"
                ><dt>{{ row.label }}</dt>
                <dd>
                  {{ row.value
                  }}<template v-if="row.label === '生成耗时'"> 毫秒</template>
                </dd></template
              >
            </dl>
            <t-empty
              v-if="!answerSettings.length"
              description="本次没有记录模型和生成设置"
            />
          </article>
        </section>
      </template>

      <template v-else-if="activeStage === 'sensitive_filtering'">
        <section class="filter-verdict">
          <div>
            <small>内容安全检查</small>
            <h3>检查完成</h3>
            <p>
              {{
                filterRows.find((row) => row.label === "处理动作")?.value ||
                "未发现需要处理的内容"
              }}
            </p>
          </div>
          <span
            >{{
              filterRows.find((row) => row.label === "脱敏内容数量")?.value ||
              "0"
            }}
            处处理</span
          >
        </section>
        <section class="two-columns">
          <article>
            <header><h3>检查前内容</h3></header>
            <p class="content-compare">
              {{
                filterRows.find((row) => row.label === "处理前内容")?.value ||
                answer ||
                "未记录"
              }}
            </p>
          </article>
          <article>
            <header><h3>检查后内容</h3></header>
            <p class="content-compare">
              {{
                filterRows.find((row) => row.label === "处理后内容")?.value ||
                answer ||
                "内容未发生变化"
              }}
            </p>
          </article>
        </section>
        <section class="readable-card">
          <header><h3>命中的安全规则</h3></header>
          <p>
            {{
              filterRows.find((row) => row.label === "命中规则")?.value ||
              "未命中安全规则"
            }}
          </p>
        </section>
      </template>

      <template v-else-if="activeStage === 'result_return'">
        <section class="return-result">
          <small>最终返回给用户的答案</small>
          <p>{{ answer || generatedAnswer }}</p>
        </section>
        <section class="metric-strip">
          <article v-for="row in returnRows" :key="row.label">
            <small>{{ row.label }}</small
            ><b>{{ row.value }}</b>
          </article>
          <t-empty
            v-if="!returnRows.length"
            description="本次没有记录返回结果摘要"
          />
        </section>
      </template>

      <section v-if="embeddedExecutionMessage" class="execution-explanation">
        {{ embeddedExecutionMessage }}
      </section>
      <section class="event-notes">
        <h3>流程编排记录</h3>
        <article v-for="event in activeEvents" :key="event.event_id">
          <b>第 {{ event.sequence }} 步 · {{ eventStatus(event.event_type) }}</b
          ><span>{{ readableTime(event.occurred_at) }}</span
          ><span>{{ producerNames[event.producer] || "系统内部服务" }}</span>
        </article>
        <t-button
          v-if="hasMore"
          block
          variant="outline"
          @click="emit('loadMore')"
          >加载更多记录</t-button
        >
      </section>
    </main>

    <t-dialog
      :visible="Boolean(selectedCandidate)"
      width="min(1100px,94vw)"
      :footer="false"
      :header="
        selectedCandidate
          ? `${selectedCandidate.source} · ${selectedCandidate.location}`
          : ''
      "
      @update:visible="
        (value: boolean) => {
          if (!value) selectedCandidate = null;
        }
      "
      ><template v-if="selectedCandidate"
        ><img
          v-if="selectedCandidate.imageUrl"
          class="source-image"
          :src="selectedCandidate.imageUrl"
          alt="资料原图" />
        <div class="source-tags">
          <span>第 {{ selectedCandidate.rank }} 名</span
          ><span>{{ translateValue(selectedCandidate.channel) }}</span
          ><span>相关度 {{ formatScore(selectedCandidate.score) }}</span>
        </div>
        <h4>知识原文</h4>
        <ChatRichContent
          class="source-content recall-rich-content"
          :content="selectedCandidate.content" /></template
    ></t-dialog>
  </div>
</template>

<style scoped>
.trace-layout {
  display: grid;
  grid-template-columns: 245px 1fr;
  min-height: 78vh;
  background: #f4f6fa;
  color: #1d293d;
}
.node-sidebar {
  background: #fff;
  border-right: 1px solid #dce3ed;
}
.node-sidebar > header {
  padding: 18px;
  border-bottom: 1px solid #e3e8ef;
}
.node-sidebar > header small {
  color: #536bc7;
}
.node-sidebar h3 {
  margin: 5px 0;
}
.node-sidebar p {
  margin: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  color: #8190a3;
  font-size: 9px;
}
.node-sidebar > button {
  display: grid;
  grid-template-columns: 28px 9px 1fr auto;
  gap: 8px;
  align-items: center;
  width: 100%;
  padding: 12px;
  border: 0;
  border-bottom: 1px solid #edf0f4;
  background: #fff;
  text-align: left;
}
.node-sidebar > button:hover,
.node-sidebar > button.active {
  background: #edf2ff;
  color: #304baa;
}
.node-sidebar > button > strong {
  color: #8894a5;
  font-size: 9px;
}
.node-sidebar > button > i {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #31a474;
}
.node-sidebar > button.warning > i {
  background: #ec9c17;
}
.node-sidebar > button.missing {
  opacity: 0.45;
}
.node-sidebar > button span b,
.node-sidebar > button span small {
  display: block;
}
.node-sidebar > button span b {
  font-size: 11px;
}
.node-sidebar > button span small,
.node-sidebar > button em {
  color: #8490a1;
  font-size: 8px;
  font-style: normal;
}
.node-sidebar > footer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  padding: 14px;
  font-size: 9px;
}
.node-sidebar > footer span {
  padding: 4px 6px;
  background: #f1f3f6;
  border-radius: 4px;
}
.node-data {
  min-width: 0;
  padding: 20px;
  overflow: auto;
}
.node-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.node-title small {
  color: #5269c6;
}
.node-title h2 {
  margin: 4px 0;
}
.node-title p {
  margin: 0;
  color: #788599;
  font-size: 10px;
}
.node-title > div:last-child {
  display: flex;
  gap: 7px;
}
.node-title > div:last-child span {
  padding: 6px 8px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 5px;
  font-size: 9px;
}
.hero-data,
.answer-content {
  margin-top: 16px;
  padding: 18px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 8px;
}
.hero-data small,
.answer-content small {
  color: #536bc7;
  font-weight: 700;
}
.hero-data > p {
  font-size: 15px;
}
.hero-data footer {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.hero-data footer span {
  padding: 5px 7px;
  background: #edf2ff;
  color: #4c62b8;
  border-radius: 4px;
  font-size: 9px;
}
.two-columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}
.two-columns > article,
.candidate-list,
.visual-strip,
.event-notes {
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 8px;
  overflow: hidden;
}
.two-columns article > header,
.candidate-list > header,
.visual-strip > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 13px 15px;
  border-bottom: 1px solid #e4e9ef;
}
.two-columns h3,
.candidate-list h3,
.visual-strip h3,
.event-notes h3 {
  margin: 0;
  font-size: 13px;
}
.two-columns article > header span,
.candidate-list header p {
  color: #7d8999;
  font-size: 9px;
}
.two-columns dl {
  display: grid;
  grid-template-columns: 145px 1fr;
  gap: 0;
  margin: 0;
  padding: 8px 15px;
}
.two-columns dt,
.two-columns dd {
  padding: 8px 0;
  border-bottom: 1px solid #edf0f4;
  font-size: 10px;
}
.two-columns dt {
  color: #718094;
}
.two-columns dd {
  margin: 0;
  word-break: break-word;
}
.candidate-list {
  margin-top: 14px;
}
.candidate-list header p {
  margin: 4px 0 0;
}
.candidate-list > button {
  display: grid;
  grid-template-columns: 65px 1fr 80px;
  gap: 12px;
  width: 100%;
  padding: 13px 15px;
  border: 0;
  border-top: 1px solid #edf0f4;
  background: #fff;
  text-align: left;
}
.candidate-list > button:hover {
  background: #f5f8ff;
}
.candidate-list > button > strong {
  color: #5168c6;
}
.candidate-list > button div header {
  display: flex;
  gap: 8px;
}
.candidate-list > button div header span {
  padding: 2px 5px;
  background: #eef2f7;
  color: #657388;
  border-radius: 3px;
  font-size: 8px;
}
.candidate-list > button p {
  margin: 6px 0 0;
  color: #617084;
  font-size: 10px;
  line-height: 1.65;
}
.candidate-list > button em {
  color: #3d56b4;
  font-size: 10px;
  font-style: normal;
  text-align: right;
}
.candidate-list.evidence > button > strong {
  color: #18815a;
}
.visual-strip {
  margin-top: 14px;
}
.visual-strip > div {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 10px;
  padding: 12px;
}
.visual-strip button {
  padding: 8px;
  border: 1px solid #dce3ed;
  border-radius: 7px;
  background: #fff;
  text-align: left;
}
.visual-strip img,
.visual-strip button > span {
  display: grid;
  place-content: center;
  width: 100%;
  height: 145px;
  object-fit: contain;
  background: #eef1f5;
  color: #8995a5;
}
.visual-strip b,
.visual-strip small {
  display: block;
  margin-top: 6px;
  font-size: 9px;
}
.count-flow {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 15px;
  padding: 35px;
}
.count-flow b {
  font-size: 28px;
  color: #4861c1;
}
.count-flow span {
  font-size: 10px;
  color: #7b8798;
}
.answer-content {
  background: #19253e;
  color: #fff;
}
.answer-content p {
  font-size: 18px;
  line-height: 1.8;
}
.event-notes {
  margin-top: 14px;
  padding: 14px;
}
.event-notes article {
  display: grid;
  grid-template-columns: 1fr 180px 180px;
  gap: 10px;
  padding: 8px 0;
  border-bottom: 1px solid #edf0f4;
  font-size: 9px;
}
.event-notes article span {
  color: #7c8899;
}
.source-image {
  display: block;
  max-width: 100%;
  max-height: 50vh;
  margin: auto;
}
.source-tags {
  display: flex;
  gap: 7px;
  margin: 12px 0;
}
.source-tags span {
  padding: 5px 7px;
  background: #edf2f8;
  border-radius: 5px;
  font-size: 9px;
}
.source-content {
  padding: 15px;
  border-left: 3px solid #536bc7;
  background: #f5f7fb;
  font-size: 12px;
  line-height: 1.9;
}
@media (max-width: 1000px) {
  .trace-layout {
    grid-template-columns: 205px 1fr;
  }
  .two-columns {
    grid-template-columns: 1fr;
  }
  .visual-strip > div {
    grid-template-columns: repeat(2, 1fr);
  }
}
.overview-answer {
  margin-top: 16px;
  background: #19253e;
  color: #fff;
  border-radius: 9px;
  overflow: hidden;
}
.overview-answer > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 15px 18px;
  border-bottom: 1px solid #3b465c;
}
.overview-answer > header p {
  margin: 5px 0 0;
  font-size: 14px;
}
.overview-answer > div {
  padding: 16px 18px;
}
.overview-answer > div p {
  margin: 6px 0 0;
  font-size: 15px;
  line-height: 1.8;
}
.overview-answer small {
  color: #91a7f0;
}
.goal-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  margin-top: 14px;
}
.goal-grid > article {
  display: flex;
  flex-direction: column;
  min-height: 235px;
  padding: 17px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 9px;
}
.goal-grid article > header {
  display: flex;
  gap: 10px;
  align-items: center;
}
.goal-grid article > header > span {
  display: grid;
  place-content: center;
  width: 34px;
  height: 34px;
  border-radius: 8px;
  background: #edf2ff;
  color: #4961bd;
  font-weight: 700;
}
.goal-grid h3 {
  margin: 0;
}
.goal-grid header p {
  margin: 3px 0 0;
  color: #7c8899;
  font-size: 9px;
}
.goal-grid dl {
  display: grid;
  grid-template-columns: 120px 1fr;
  margin: 14px 0;
}
.goal-grid dt,
.goal-grid dd {
  padding: 6px 0;
  border-bottom: 1px solid #edf0f4;
  font-size: 10px;
}
.goal-grid dt {
  color: #758296;
}
.goal-grid dd {
  margin: 0;
}
.goal-grid ul,
.goal-grid ol {
  padding-left: 20px;
  color: #536175;
  font-size: 10px;
  line-height: 1.8;
}
.goal-grid button {
  align-self: flex-start;
  margin-top: auto;
  border: 0;
  background: none;
  color: #3d57b6;
  font-size: 10px;
}
.missing-message {
  padding: 9px;
  background: #fff2db;
  color: #95620b;
  font-size: 10px;
}
.goal-grid .locate > header > span {
  background: #fff1dd;
  color: #a66809;
}
.goal-grid .reproduce > header > span {
  background: #e9f7f0;
  color: #177d58;
}
.goal-grid .optimize > header > span {
  background: #f1ebff;
  color: #714cc0;
}
.intent-question {
  margin-top: 16px;
  padding: 18px 20px;
  border-radius: 9px;
  background: #19253e;
  color: #fff;
}
.intent-question small {
  color: #9db0ef;
}
.intent-question p {
  margin: 7px 0 0;
  font-size: 17px;
}
.intent-conclusion {
  margin-top: 14px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 9px;
}
.intent-conclusion > header {
  display: flex;
  justify-content: space-between;
  padding: 15px 18px;
  border-bottom: 1px solid #e4e9ef;
}
.intent-conclusion h3,
.intent-details h3 {
  margin: 0;
  font-size: 13px;
}
.intent-conclusion header p,
.intent-details header p {
  margin: 4px 0 0;
  color: #7a8798;
  font-size: 9px;
}
.intent-conclusion > header > span {
  align-self: center;
  padding: 5px 8px;
  border-radius: 5px;
  background: #e9f7f0;
  color: #177e59;
  font-size: 9px;
}
.intent-conclusion > div {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 1px;
  background: #e3e8ef;
}
.intent-conclusion article {
  padding: 16px;
  background: #fff;
}
.intent-conclusion article small,
.intent-conclusion article b {
  display: block;
}
.intent-conclusion article small {
  color: #788598;
  font-size: 9px;
}
.intent-conclusion article b {
  margin-top: 7px;
  font-size: 13px;
}
.intent-details {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-top: 14px;
}
.intent-details > article {
  padding: 16px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 9px;
}
.intent-details ol {
  margin: 14px 0 0;
  padding-left: 23px;
}
.intent-details ol li {
  padding: 6px 4px;
  color: #526074;
  font-size: 11px;
  line-height: 1.6;
}
.query-evolution {
  margin-top: 13px;
}
.query-evolution > div {
  display: grid;
  grid-template-columns: 25px 1fr;
  gap: 8px;
  position: relative;
  padding-bottom: 14px;
}
.query-evolution > div:after {
  content: "";
  position: absolute;
  left: 11px;
  top: 22px;
  bottom: 0;
  width: 1px;
  background: #d6deea;
}
.query-evolution > div:last-child:after {
  display: none;
}
.query-evolution i {
  z-index: 1;
  display: grid;
  place-content: center;
  width: 23px;
  height: 23px;
  border-radius: 50%;
  background: #5269c7;
  color: #fff;
  font-size: 9px;
  font-style: normal;
}
.query-evolution small,
.query-evolution b {
  display: block;
}
.query-evolution small {
  color: #788598;
  font-size: 9px;
}
.query-evolution b {
  margin-top: 4px;
  font-size: 11px;
  line-height: 1.5;
}
.planning-query {
  margin-top: 16px;
  padding: 18px 20px;
  border-radius: 9px;
  background: #19253e;
  color: #fff;
}
.planning-query small {
  color: #9db0ef;
}
.planning-query p {
  margin: 7px 0 0;
  font-size: 16px;
}
.planning-flow {
  display: grid;
  grid-template-columns: 1.2fr 25px 1fr 25px 1fr 25px 0.8fr;
  align-items: center;
  margin-top: 14px;
  padding: 14px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 9px;
}
.planning-flow > article {
  display: flex;
  gap: 9px;
  align-items: center;
  min-width: 0;
}
.planning-flow > article > span {
  display: grid;
  place-content: center;
  flex: none;
  width: 27px;
  height: 27px;
  border-radius: 50%;
  background: #5269c7;
  color: #fff;
  font-size: 10px;
}
.planning-flow small,
.planning-flow b {
  display: block;
}
.planning-flow small {
  color: #7c8899;
  font-size: 8px;
}
.planning-flow b {
  margin-top: 3px;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 10px;
  white-space: nowrap;
}
.planning-flow > i {
  text-align: center;
  color: #9aa5b4;
  font-style: normal;
}
.planning-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 14px;
  margin-top: 14px;
}
.planning-grid > article {
  padding: 16px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 9px;
}
.planning-grid h3 {
  margin: 0;
  font-size: 13px;
}
.planning-grid header p {
  margin: 4px 0 0;
  color: #7b8798;
  font-size: 9px;
}
.planning-grid dl {
  display: grid;
  grid-template-columns: 150px 1fr;
  margin: 12px 0 0;
}
.planning-grid dt,
.planning-grid dd {
  padding: 7px 0;
  border-bottom: 1px solid #edf0f4;
  font-size: 10px;
}
.planning-grid dt {
  color: #738094;
}
.planning-grid dd {
  margin: 0;
}
.planning-grid ol {
  padding-left: 22px;
  color: #536175;
  font-size: 10px;
  line-height: 1.8;
}
.channel-list {
  margin-top: 12px;
}
.channel-list > div {
  display: flex;
  gap: 9px;
  align-items: center;
  padding: 9px;
  border-bottom: 1px solid #edf0f4;
}
.channel-list > div > i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #31a474;
}
.channel-list > div.skipped > i {
  background: #aab3c0;
}
.channel-list > div.skipped {
  opacity: 0.65;
}
.channel-list b,
.channel-list small {
  display: block;
}
.channel-list b {
  font-size: 10px;
}
.channel-list small {
  margin-top: 3px;
  color: #7c899a;
  font-size: 8px;
}
.fallback-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}
.fallback-list > span {
  display: flex;
  gap: 6px;
  align-items: center;
  padding: 7px;
  background: #f0f3f8;
  border-radius: 6px;
  font-size: 9px;
}
.fallback-list i {
  display: grid;
  place-content: center;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #5068c4;
  color: #fff;
  font-style: normal;
}
.fallback-list b {
  margin-left: 5px;
  color: #8e99a8;
}
.entry-card,
.return-result {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  margin-top: 16px;
  padding: 20px;
  border-radius: 9px;
  background: #19253e;
  color: #fff;
}
.entry-card small,
.return-result small {
  color: #9db0ef;
}
.entry-card p,
.return-result p {
  margin: 7px 0 0;
  font-size: 17px;
  line-height: 1.75;
}
.entry-card > span {
  align-self: flex-start;
  padding: 6px 9px;
  border-radius: 5px;
  background: #244a40;
  color: #80dfbd;
  font-size: 9px;
  white-space: nowrap;
}
.readable-card {
  margin-top: 14px;
  padding: 16px 18px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 9px;
}
.readable-card > header {
  padding-bottom: 12px;
  border-bottom: 1px solid #e5eaf0;
}
.readable-card h3 {
  margin: 0;
  font-size: 13px;
}
.readable-card header p {
  margin: 4px 0 0;
  color: #7b8798;
  font-size: 9px;
}
.readable-card dl {
  display: grid;
  grid-template-columns: 160px 1fr;
  margin: 10px 0 0;
}
.readable-card dt,
.readable-card dd {
  padding: 8px 0;
  border-bottom: 1px solid #edf0f4;
  font-size: 10px;
}
.readable-card dt {
  color: #718094;
}
.readable-card dd {
  margin: 0;
  word-break: break-word;
}
.metric-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(145px, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.metric-strip > article {
  padding: 14px 15px;
  background: #fff;
  border: 1px solid #dce3ed;
  border-radius: 8px;
}
.metric-strip small,
.metric-strip b {
  display: block;
}
.metric-strip small {
  color: #788598;
  font-size: 9px;
}
.metric-strip b {
  margin-top: 7px;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}
.evidence-verdict,
.filter-verdict {
  margin-top: 16px;
  padding: 18px;
  background: #eaf7f1;
  border: 1px solid #b9dfcf;
  border-radius: 9px;
}
.evidence-verdict > header,
.filter-verdict {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: center;
}
.evidence-verdict small,
.filter-verdict small {
  color: #4b7666;
}
.evidence-verdict h3,
.filter-verdict h3 {
  margin: 5px 0 0;
  color: #166c4e;
}
.evidence-verdict > header > span,
.filter-verdict > span {
  padding: 6px 9px;
  border-radius: 5px;
  background: #d3eee2;
  color: #166c4e;
  font-size: 9px;
  white-space: nowrap;
}
.evidence-verdict > div {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(130px, 1fr));
  gap: 10px;
  margin-top: 14px;
}
.evidence-verdict article {
  padding: 10px;
  background: rgba(255, 255, 255, 0.7);
  border-radius: 6px;
}
.evidence-verdict article small,
.evidence-verdict article b {
  display: block;
}
.evidence-verdict article b {
  margin-top: 5px;
  font-size: 11px;
}
.reason-list {
  margin: 12px 0 0;
  padding-left: 24px;
  color: #526074;
  font-size: 10px;
  line-height: 1.8;
}
.answer-source-summary {
  padding: 22px;
}
.answer-source-summary b {
  display: block;
  color: #4962c1;
  font-size: 32px;
}
.answer-source-summary span {
  font-size: 11px;
  font-weight: 600;
}
.answer-source-summary p {
  color: #768397;
  font-size: 9px;
  line-height: 1.6;
}
.filter-verdict p {
  margin: 5px 0 0;
  color: #466456;
  font-size: 10px;
}
.content-compare {
  min-height: 110px;
  margin: 0;
  padding: 16px;
  color: #405066;
  font-size: 11px;
  line-height: 1.75;
  white-space: pre-wrap;
}
.return-result {
  display: block;
}
.return-result p {
  white-space: pre-wrap;
}
.return-result + .metric-strip {
  margin-bottom: 0;
}
@media (max-width: 1000px) {
  .planning-flow {
    grid-template-columns: 1fr;
  }
  .planning-flow > i {
    transform: rotate(90deg);
  }
  .planning-grid,
  .intent-details,
  .goal-grid {
    grid-template-columns: 1fr;
  }
}
.execution-explanation {
  margin-top: 14px;
  padding: 11px 14px;
  border: 1px solid #c9d7f5;
  border-radius: 7px;
  background: #eef4ff;
  color: #425a91;
  font-size: 10px;
  line-height: 1.6;
}
.trace-layout {
  grid-template-columns: 310px 1fr;
  font-size: 14px;
}
.node-sidebar {
  max-height: calc(100vh - 110px);
  overflow: auto;
}
.node-sidebar > header small,
.node-sidebar > footer,
.node-title small {
  font-size: 12px;
}
.node-sidebar > header p {
  font-size: 11px;
}
.node-sidebar > .stage-tree {
  border-bottom: 1px solid #e7ebf1;
}
.stage-tree > button {
  display: grid;
  grid-template-columns: 30px 10px 1fr auto;
  gap: 9px;
  align-items: center;
  width: 100%;
  padding: 13px 14px;
  border: 0;
  background: #fff;
  text-align: left;
}
.stage-tree > button:hover,
.stage-tree > button.active {
  background: #edf2ff;
  color: #304baa;
}
.stage-tree > button > strong {
  color: #7e8b9d;
  font-size: 11px;
}
.stage-tree > button > i {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #2fa474;
}
.stage-tree > button.warning > i {
  background: #e99a16;
}
.stage-tree > button.missing {
  opacity: 0.55;
}
.stage-tree > button span b {
  display: block;
  font-size: 14px;
}
.stage-tree > button span small,
.stage-tree > button em {
  display: block;
  color: #7a8799;
  font-size: 11px;
  font-style: normal;
}
.step-tree {
  padding: 0 10px 9px 37px;
}
.step-tree > button {
  display: grid;
  grid-template-columns: 9px 1fr;
  gap: 9px;
  width: 100%;
  padding: 8px 9px;
  border: 0;
  border-left: 1px solid #d6deea;
  background: transparent;
  text-align: left;
}
.step-tree > button:hover,
.step-tree > button.active {
  border-radius: 0 6px 6px 0;
  background: #f0f4ff;
}
.step-tree > button > i {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: #a8b2c0;
}
.step-tree > button.active > i {
  background: #4c64c2;
}
.step-tree b {
  display: block;
  color: #405067;
  font-size: 12px;
}
.step-tree small {
  display: block;
  margin-top: 3px;
  color: #8994a4;
  font-size: 10px;
}
.node-title p {
  font-size: 13px;
}
.node-title > div:last-child span {
  font-size: 12px;
}
.candidate-list header p,
.two-columns article > header span,
.intent-conclusion header p,
.intent-details header p,
.planning-grid header p {
  font-size: 12px;
}
.candidate-list > button p,
.two-columns dt,
.two-columns dd,
.planning-grid dt,
.planning-grid dd,
.goal-grid dt,
.goal-grid dd {
  font-size: 13px;
}
.candidate-list > button > strong,
.candidate-list > button > em {
  font-size: 12px;
}
.event-notes article {
  font-size: 12px;
}
.diagnosis-list,
.lifecycle-table {
  margin-top: 16px;
  overflow: hidden;
  border: 1px solid #d9e0ea;
  border-radius: 10px;
  background: #fff;
}
.diagnosis-list > header,
.lifecycle-table > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 17px 18px;
  border-bottom: 1px solid #e4e9ef;
}
.diagnosis-list h3,
.lifecycle-table h3 {
  margin: 0;
  font-size: 16px;
}
.diagnosis-list header p,
.lifecycle-table header p {
  margin: 4px 0 0;
  color: #758397;
  font-size: 12px;
}
.diagnosis-list > button {
  display: grid;
  grid-template-columns: 10px 1fr auto;
  gap: 13px;
  align-items: start;
  width: 100%;
  padding: 15px 18px;
  border: 0;
  border-top: 1px solid #edf0f4;
  background: #fff;
  text-align: left;
}
.diagnosis-list > button:hover {
  background: #f7f9fc;
}
.diagnosis-list > button > i {
  width: 9px;
  height: 9px;
  margin-top: 5px;
  border-radius: 50%;
}
.diagnosis-list > button.success > i {
  background: #27a276;
}
.diagnosis-list > button.warning > i {
  background: #e99a16;
}
.diagnosis-list > button.danger > i {
  background: #d84b4b;
}
.diagnosis-list > button b {
  font-size: 14px;
}
.diagnosis-list > button p {
  margin: 5px 0 0;
  color: #637186;
  font-size: 13px;
  line-height: 1.6;
}
.diagnosis-list > button span {
  color: #4861bd;
  font-size: 12px;
}
.lifecycle-head,
.lifecycle-table > button {
  display: grid;
  grid-template-columns: minmax(360px, 1fr) 90px 90px 100px 90px;
  gap: 12px;
  align-items: center;
}
.lifecycle-head {
  padding: 10px 16px;
  background: #f2f5f9;
  color: #647288;
  font-size: 12px;
  font-weight: 600;
}
.lifecycle-table > button {
  width: 100%;
  padding: 14px 16px;
  border: 0;
  border-top: 1px solid #e9edf2;
  background: #fff;
  text-align: left;
}
.lifecycle-table > button:hover {
  background: #f7f9fd;
}
.lifecycle-table > button > div b {
  font-size: 13px;
}
.lifecycle-table > button > div p {
  display: -webkit-box;
  margin: 6px 0 0;
  overflow: hidden;
  color: #637186;
  font-size: 13px;
  line-height: 1.55;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
}
.lifecycle-table > button > span {
  font-size: 12px;
  text-align: center;
}
.lifecycle-table > button > span small {
  display: block;
  margin-top: 4px;
  color: #738198;
}
.lifecycle-table .dropped {
  color: #a16a12;
}
.lifecycle-table .yes {
  color: #15815a;
  font-weight: 700;
}
.step-verdict {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  margin-top: 16px;
  padding: 18px;
  border: 1px solid #cbd7ec;
  border-radius: 9px;
  background: #eef4ff;
}
.step-verdict small {
  color: #5b6f96;
  font-size: 12px;
}
.step-verdict h3 {
  margin: 5px 0;
  font-size: 18px;
}
.step-verdict p {
  margin: 0;
  color: #53647e;
  font-size: 13px;
}
.step-verdict > span {
  align-self: flex-start;
  padding: 6px 9px;
  border-radius: 5px;
  background: #fff;
  color: #435b92;
  font-size: 12px;
}
.step-data-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-top: 14px;
}
.step-data-grid > article {
  overflow: hidden;
  border: 1px solid #dae1eb;
  border-radius: 9px;
  background: #fff;
}
.step-data-grid article > header {
  padding: 14px 16px;
  border-bottom: 1px solid #e5eaf0;
}
.step-data-grid h3 {
  margin: 0;
  font-size: 15px;
}
.step-data-grid header p {
  margin: 4px 0 0;
  color: #7a8798;
  font-size: 12px;
}
.step-data-grid dl {
  margin: 0;
  padding: 8px 15px;
}
.step-data-grid dt {
  padding-top: 9px;
  color: #758296;
  font-size: 12px;
}
.step-data-grid dd {
  margin: 4px 0 0;
  padding-bottom: 9px;
  border-bottom: 1px solid #edf0f4;
  color: #29374b;
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}
@media (max-width: 1100px) {
  .trace-layout {
    grid-template-columns: 260px 1fr;
  }
  .step-data-grid {
    grid-template-columns: 1fr;
  }
  .lifecycle-head,
  .lifecycle-table > button {
    grid-template-columns: minmax(260px, 1fr) 70px 70px 80px 70px;
  }
}
.case-summary {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 16px;
  margin-top: 16px;
  padding: 20px;
  border: 1px solid #d5deeb;
  border-left: 5px solid #4d66c4;
  border-radius: 10px;
  background: #fff;
}
.case-summary.warning {
  border-left-color: #e59a18;
  background: #fffaf0;
}
.case-summary.danger {
  border-left-color: #d84b4b;
  background: #fff6f6;
}
.case-summary.success {
  border-left-color: #2aa276;
}
.case-summary small {
  color: #728096;
  font-size: 12px;
}
.case-summary h3 {
  margin: 5px 0;
  font-size: 20px;
}
.case-summary p {
  margin: 0;
  color: #5f6e83;
  font-size: 13px;
}
.case-summary > strong {
  align-self: start;
  padding: 7px 11px;
  border-radius: 16px;
  background: #eef2ff;
  color: #425bb2;
  font-size: 12px;
}
.case-summary.warning > strong {
  background: #fff0d4;
  color: #97620a;
}
.case-summary.danger > strong {
  background: #ffe2e2;
  color: #a83535;
}
.case-summary dl {
  display: flex;
  grid-column: 1/-1;
  gap: 0;
  margin: 4px 0 0;
  border-top: 1px solid #e7ebf1;
}
.case-summary dl > div {
  min-width: 135px;
  padding: 14px 22px 0 0;
}
.case-summary dt {
  color: #7b8798;
  font-size: 12px;
}
.case-summary dd {
  margin: 5px 0 0;
  font-size: 18px;
  font-weight: 700;
}
.lifecycle-tools {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid #e6ebf1;
}
.lifecycle-tools > .t-input {
  max-width: 420px;
}
.lifecycle-tools > div {
  display: flex;
  gap: 6px;
}
.lifecycle-tools button {
  padding: 7px 11px;
  border: 1px solid #d7deea;
  border-radius: 6px;
  background: #fff;
  color: #637086;
  font-size: 12px;
}
.lifecycle-tools button.active {
  border-color: #5870ca;
  background: #edf2ff;
  color: #3f57b0;
}
.answer-review {
  display: grid;
  grid-template-columns: minmax(240px, 0.6fr) minmax(420px, 1.4fr);
  gap: 14px;
  margin-top: 16px;
}
.answer-review > article {
  padding: 18px;
  border: 1px solid #d9e0ea;
  border-radius: 10px;
  background: #fff;
}
.answer-review small {
  color: #6579c5;
  font-size: 12px;
  font-weight: 700;
}
.answer-review p {
  margin: 8px 0 0;
  color: #27364b;
  font-size: 14px;
  line-height: 1.8;
  white-space: pre-wrap;
}
@media (max-width: 1000px) {
  .answer-review {
    grid-template-columns: 1fr;
  }
  .lifecycle-tools {
    align-items: stretch;
    flex-direction: column;
  }
  .lifecycle-tools > .t-input {
    max-width: none;
  }
}
.step-data-grid.two-sections {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}
@media (max-width: 1100px) {
  .step-data-grid.two-sections {
    grid-template-columns: 1fr;
  }
}
.query-compare {
  display: grid;
  grid-template-columns: 1fr 44px 1fr;
  align-items: stretch;
  margin-top: 16px;
}
.query-compare > article {
  padding: 18px 20px;
  border: 1px solid #d8e0eb;
  border-radius: 9px;
  background: #fff;
}
.query-compare > i {
  display: grid;
  place-content: center;
  color: #8491a3;
  font-size: 20px;
  font-style: normal;
}
.query-compare small {
  color: #6579c5;
  font-size: 12px;
  font-weight: 700;
}
.query-compare p {
  margin: 7px 0 0;
  font-size: 16px;
  line-height: 1.6;
}
.query-compare span {
  display: inline-block;
  margin-top: 10px;
  padding: 4px 7px;
  border-radius: 4px;
  background: #eef2f7;
  color: #6d798a;
  font-size: 11px;
}
.channel-list b {
  font-size: 13px;
}
.channel-list small {
  font-size: 12px;
  line-height: 1.55;
}
.recall-workbench {
  margin-top: 16px;
  overflow: hidden;
  border: 1px solid #d7dfe9;
  border-radius: 10px;
  background: #fff;
}
.recall-workbench > header,
.retriever-results > header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 17px 18px;
  border-bottom: 1px solid #e5eaf0;
}
.recall-workbench h3,
.retriever-results h3 {
  margin: 0;
  font-size: 16px;
}
.recall-workbench header p,
.retriever-results header p {
  margin: 4px 0 0;
  color: #748196;
  font-size: 12px;
}
.recall-workbench > nav {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-bottom: 1px solid #e5eaf0;
  background: #f7f9fc;
}
.recall-workbench > nav button {
  min-width: 135px;
  padding: 10px 12px;
  border: 1px solid #d7deea;
  border-radius: 7px;
  background: #fff;
  text-align: left;
}
.recall-workbench > nav button.active {
  border-color: #5269c6;
  background: #edf2ff;
  box-shadow: 0 0 0 1px #5269c6;
}
.recall-workbench > nav span,
.recall-workbench > nav small {
  display: block;
}
.recall-workbench > nav span {
  font-size: 13px;
  font-weight: 700;
}
.recall-workbench > nav small {
  margin-top: 4px;
  color: #778498;
  font-size: 11px;
}
.retriever-run {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 20px;
  padding: 18px;
}
.retriever-run > div {
  padding: 15px;
  border-left: 4px solid #5269c6;
  background: #f3f6fd;
}
.retriever-run > div small {
  color: #596c9e;
  font-size: 12px;
  font-weight: 700;
}
.retriever-run > div p {
  margin: 7px 0 0;
  font-size: 16px;
  line-height: 1.55;
}
.retriever-run dl {
  display: flex;
  gap: 0;
  margin: 0;
}
.retriever-run dl > div {
  min-width: 100px;
  padding: 12px;
  border-left: 1px solid #e2e7ee;
}
.retriever-run dt {
  color: #788598;
  font-size: 11px;
}
.retriever-run dd {
  margin: 6px 0 0;
  font-size: 14px;
  font-weight: 700;
}
.retriever-results {
  border-top: 8px solid #f4f6f9;
}
.retriever-results > button {
  display: grid;
  grid-template-columns: 70px 1fr 110px;
  gap: 14px;
  width: 100%;
  padding: 14px 18px;
  border: 0;
  border-top: 1px solid #e9edf2;
  background: #fff;
  text-align: left;
}
.retriever-results > button:hover {
  background: #f7f9fd;
}
.retriever-results > button > strong {
  color: #5067c2;
  font-size: 12px;
}
.retriever-results > button div header b {
  font-size: 13px;
}
.retriever-results > button p {
  display: -webkit-box;
  margin: 7px 0 0;
  overflow: hidden;
  color: #5c6b7f;
  font-size: 13px;
  line-height: 1.6;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
}
.retriever-results > button > em {
  color: #4059b6;
  font-size: 12px;
  font-style: normal;
  text-align: right;
}
@media (max-width: 1000px) {
  .query-compare {
    grid-template-columns: 1fr;
  }
  .query-compare > i {
    transform: rotate(90deg);
  }
  .recall-workbench > nav {
    overflow: auto;
  }
  .retriever-run {
    grid-template-columns: 1fr;
  }
  .retriever-run dl {
    overflow: auto;
  }
}
.retriever-query-run {
  border-top: 10px solid #f2f4f8;
}
.retriever-query-run > header {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 20px;
  padding: 18px;
}
.retriever-query-run > header > div {
  padding: 15px 17px;
  border-left: 4px solid #5269c6;
  background: #f3f6fd;
}
.retriever-query-run > header small {
  color: #596c9e;
  font-size: 12px;
  font-weight: 700;
}
.retriever-query-run > header p {
  margin: 7px 0 0;
  color: #1f2e43;
  font-size: 16px;
  font-weight: 600;
}
.retriever-query-run > header dl {
  display: flex;
  margin: 0;
}
.retriever-query-run > header dl > div {
  min-width: 85px;
  padding: 10px;
  border-left: 1px solid #e1e6ed;
}
.retriever-query-run dt {
  color: #778498;
  font-size: 11px;
}
.retriever-query-run dd {
  margin: 6px 0 0;
  font-size: 14px;
  font-weight: 700;
}
.retriever-results > button p.full-content {
  display: block;
  overflow: visible;
  color: #425269;
  white-space: pre-wrap;
  -webkit-line-clamp: unset;
}
@media (max-width: 1000px) {
  .retriever-query-run > header {
    grid-template-columns: 1fr;
  }
  .retriever-query-run > header dl {
    overflow: auto;
  }
}
.retriever-results > button:has(.recall-preview) {
  grid-template-columns: 70px 150px 1fr 110px;
}
.recall-preview {
  width: 150px;
  height: 110px;
  border: 1px solid #dce3ed;
  border-radius: 6px;
  background: #f3f5f8;
  object-fit: contain;
}
.retriever-results > button div header {
  display: flex;
  gap: 8px;
  align-items: center;
}
.retriever-results > button div header span {
  padding: 3px 6px;
  border-radius: 4px;
  background: #edf2ff;
  color: #4d63b8;
  font-size: 11px;
}
.retriever-results > button > em small {
  display: block;
  margin-bottom: 4px;
  color: #7c899a;
  font-size: 10px;
  font-style: normal;
}
.candidate-count-warning {
  margin: 0;
  padding: 10px 18px;
  border-top: 1px solid #f2d5a1;
  border-bottom: 1px solid #f2d5a1;
  background: #fff6e6;
  color: #8d5b08;
  font-size: 12px;
}
.retriever-results > header > b {
  color: #4059b6;
  font-size: 13px;
}
@media (max-width: 1000px) {
  .retriever-results > button:has(.recall-preview) {
    grid-template-columns: 55px 100px 1fr;
  }
  .recall-preview {
    width: 100px;
    height: 80px;
  }
  .retriever-results > button > em {
    grid-column: 3;
  }
}
.trace-layout {
  height: calc(100vh - 150px);
  min-height: 560px;
  overflow: hidden;
}
.node-sidebar {
  height: 100%;
  max-height: none;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.node-data {
  height: 100%;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
}
.stage-tree {
  position: relative;
}
.stage-tree > .stage-collapse {
  position: absolute;
  z-index: 2;
  top: 10px;
  right: 8px;
  width: 26px;
  height: 26px;
  padding: 0;
  border: 1px solid #d7deea;
  border-radius: 5px;
  background: #fff;
  color: #617086;
  font-size: 16px;
  line-height: 24px;
  text-align: center;
}
.stage-tree > button:first-child {
  padding-right: 42px;
}
.node-data section > header,
.step-data-grid > article > header,
.planning-grid > article > header,
.two-columns > article > header,
.intent-details > article > header {
  cursor: pointer;
  user-select: none;
}
.node-data section > header::after,
.step-data-grid > article > header::after,
.planning-grid > article > header::after,
.two-columns > article > header::after,
.intent-details > article > header::after {
  content: "−";
  display: grid;
  flex: none;
  place-content: center;
  width: 24px;
  height: 24px;
  margin-left: auto;
  border: 1px solid #d7deea;
  border-radius: 5px;
  background: #fff;
  color: #667489;
  font-size: 15px;
}
.node-data .data-collapsed > header::after {
  content: "＋";
}
.node-data .data-collapsed > :not(header) {
  display: none !important;
}
@media (max-width: 1000px) {
  .trace-layout {
    height: calc(100vh - 120px);
    min-height: 480px;
  }
}
.stage-tree > .stage-collapse {
  display: none;
}
.stage-tree > button:first-child {
  padding-right: 38px;
}
.stage-tree > button.expandable::after {
  content: "⌃";
  position: absolute;
  right: 12px;
  color: #69778a;
  font-size: 17px;
  line-height: 1;
}
.stage-tree > button.expandable.collapsed::after {
  content: "⌄";
}
.node-data section > header::after,
.step-data-grid > article > header::after,
.planning-grid > article > header::after,
.two-columns > article > header::after,
.intent-details > article > header::after {
  content: "⌃";
  border: 0;
  background: transparent;
  font-size: 18px;
}
.node-data .data-collapsed > header::after {
  content: "⌄";
}
</style>
