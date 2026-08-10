<!--
  AgentTracePanel

  负责：
  1. 展示 Agent 执行过程
  2. 帮助用户理解检索、规划和回答生成路径
  3. 支持流式场景下的阶段性回显
-->
<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';

import type { AgentTraceStep } from '@/types/api';
import { visibleTraceSteps } from '@/utils/agentTrace';

const props = defineProps<{
  steps: AgentTraceStep[];
}>();

const { t, locale } = useI18n();

interface TraceRouteItem {
  label: string;
  value: string;
}

interface TraceMetric {
  label: string;
  value: string;
  suffix: string;
}

interface TracePair {
  label: string;
  value: string;
}

interface TraceSummaryView {
  lead: string;
  lines: string[];
  metrics: TraceMetric[];
  pairs: TracePair[];
  queries: string[];
}

interface TraceViewItem {
  key: string;
  index: number;
  step: AgentTraceStep;
  title: string;
  routeItems: TraceRouteItem[];
  routeReason: string;
  summary: TraceSummaryView;
}

const TASK_LABELS: Record<string, string> = {
  answer: 'ai.trace.task.answer',
  answer_llm: 'ai.trace.task.answerLlm',
  answer_generator: 'ai.trace.task.answerGenerator',
  answer_policy_gate: 'ai.trace.task.answerPolicyGate',
  answer_policy_router: 'ai.trace.task.answerPolicyRouter',
  chat_policy: 'ai.trace.task.chatPolicy',
  confirm_state: 'ai.trace.task.confirmState',
  direct_answer: 'ai.trace.task.directAnswer',
  evidence_judge: 'ai.trace.task.evidenceJudge',
  evidence_judge_fast: 'ai.trace.task.evidenceJudgeFast',
  evidence_decision: 'ai.trace.task.evidenceDecision',
  intent: 'ai.trace.task.intent',
  llm: 'ai.trace.task.llm',
  policy_resolution: 'ai.trace.task.policyResolution',
  planner: 'ai.trace.task.planner',
  pre_intent_gate: 'ai.trace.task.preIntentGate',
  query_decompose: 'ai.trace.task.queryDecompose',
  query_profile: 'ai.trace.task.queryProfile',
  question_understanding: 'ai.trace.task.questionUnderstanding',
  retrieval: 'ai.trace.task.retrieval',
  retry_retrieval: 'ai.trace.task.retryRetrieval',
  router: 'ai.trace.task.router',
  reranker: 'ai.trace.task.reranker',
  visual_evidence: 'ai.trace.task.visualEvidence',
  visual_reading: 'ai.trace.task.visualReading',
  vision_llm: 'ai.trace.task.visionLlm',
  multi_intent_orchestration: 'ai.trace.task.multiIntent',
};

const SOURCE_LABELS: Record<string, string> = {
  database: 'ai.trace.source.database',
  env_fallback: 'ai.trace.source.envFallback',
  explicit: 'ai.trace.source.explicit',
  not_called: 'ai.trace.source.notCalled',
  policy_matrix: 'ai.trace.source.policyMatrix',
  retrieval_policy_matrix: 'ai.trace.source.retrievalPolicyMatrix',
  rules: 'ai.trace.source.rules',
  rules_fast_path: 'ai.trace.source.rulesFastPath',
  rules_fallback: 'ai.trace.source.rulesFallback',
  unknown: 'ai.trace.source.unknown',
};

const RETRIEVER_LABELS: Record<string, string> = {
  graph: 'ai.trace.retriever.graph',
  graphrag: 'ai.trace.retriever.graphrag',
  keyword: 'ai.trace.retriever.keyword',
  keyword_retrieval: 'ai.trace.retriever.keywordRetrieval',
  milvus: 'ai.trace.retriever.milvus',
  page_index: 'ai.trace.retriever.pageIndex',
  page_level_retrieval: 'ai.trace.retriever.pageLevelRetrieval',
  project_metadata: 'ai.trace.retriever.projectMetadata',
  ripgrep: 'ai.trace.retriever.ripgrep',
  semantic_retrieval: 'ai.trace.retriever.semanticRetrieval',
  visual: 'ai.trace.retriever.visual',
  visual_retrieval: 'ai.trace.retriever.visualRetrieval',
};

const PROFILE_LABELS: Record<string, string> = {
  base: 'ai.trace.profile.base',
  base_chat: 'ai.trace.profile.baseChat',
  bot_identity: 'ai.trace.profile.botIdentity',
  calculation: 'ai.trace.profile.calculation',
  casual: 'ai.trace.profile.casual',
  comparison: 'ai.trace.profile.comparison',
  comparison_table: 'ai.trace.profile.comparisonTable',
  concept: 'ai.trace.profile.concept',
  document: 'ai.trace.profile.document',
  document_location: 'ai.trace.profile.documentLocation',
  direct_answer: 'ai.trace.profile.directAnswer',
  direct_value: 'ai.trace.profile.directValue',
  equipment: 'ai.trace.profile.equipment',
  equipment_lookup: 'ai.trace.profile.equipmentLookup',
  exact_lookup: 'ai.trace.profile.exactLookup',
  flow_description: 'ai.trace.profile.flowDescription',
  general: 'ai.trace.profile.general',
  general_qa: 'ai.trace.profile.generalQa',
  graph_reasoning: 'ai.trace.profile.graphReasoning',
  help: 'ai.trace.profile.help',
  identity: 'ai.trace.profile.identity',
  industry: 'ai.trace.profile.industry',
  industry_explanation: 'ai.trace.profile.industryExplanation',
  industry_knowledge_qa: 'ai.trace.profile.industryKnowledgeQa',
  knowledge_qa: 'ai.trace.profile.knowledgeQa',
  limited_answer: 'ai.trace.profile.limitedAnswer',
  material_flow: 'ai.trace.profile.materialFlow',
  normal_answer: 'ai.trace.profile.normalAnswer',
  page_location: 'ai.trace.profile.pageLocation',
  parameter: 'ai.trace.profile.parameter',
  parameter_lookup: 'ai.trace.profile.parameterLookup',
  parameter_table: 'ai.trace.profile.parameterTable',
  partial_answer: 'ai.trace.profile.partialAnswer',
  partial_answer_with_llm: 'ai.trace.profile.partialAnswerWithLlm',
  process: 'ai.trace.profile.process',
  process_flow: 'ai.trace.profile.processFlow',
  process_steps: 'ai.trace.profile.processSteps',
  project: 'ai.trace.profile.project',
  project_chat: 'ai.trace.profile.projectChat',
  project_overview: 'ai.trace.profile.projectOverview',
  project_qa: 'ai.trace.profile.projectQa',
  project_summary: 'ai.trace.profile.projectSummary',
  project_with_industry: 'ai.trace.profile.projectWithIndustry',
  pure_general_qa: 'ai.trace.profile.pureGeneralQa',
  refusal: 'ai.trace.profile.refusal',
  source_location: 'ai.trace.profile.sourceLocation',
  summary: 'ai.trace.profile.summary',
  troubleshooting: 'ai.trace.profile.troubleshooting',
  unknown: 'ai.trace.profile.unknown',
};

const POLICY_LABELS: Record<string, string> = {
  ASK_GENERAL_CONFIRM: 'ai.trace.policy.askGeneralConfirm',
  CLARIFY: 'ai.trace.policy.clarify',
  EMPTY: 'ai.trace.policy.empty',
  ENOUGH: 'ai.trace.policy.enough',
  CONFLICTED: 'ai.trace.policy.conflicted',
  GENERAL_ALLOWED: 'ai.trace.policy.generalAllowed',
  INVALID_QUERY: 'ai.trace.policy.invalidQuery',
  KB_FIRST: 'ai.trace.policy.kbFirst',
  PARTIAL: 'ai.trace.policy.partial',
  PRESET_REPLY: 'ai.trace.policy.presetReply',
  STRICT_KB: 'ai.trace.policy.strictKb',
  WEAK_ONLY: 'ai.trace.policy.weakOnly',
};

const VALUE_LABELS: Record<string, string> = {
  answered: 'ai.trace.value.answered',
  completed: 'ai.trace.value.completed',
  CONFLICTED: 'ai.trace.policy.conflicted',
  EMPTY: 'ai.trace.policy.empty',
  ENOUGH: 'ai.trace.policy.enough',
  failed: 'ai.trace.value.failed',
  insufficient_evidence: 'ai.trace.value.insufficientEvidence',
  INVALID_QUERY: 'ai.trace.policy.invalidQuery',
  PARTIAL: 'ai.trace.policy.partial',
  partially_answered: 'ai.trace.value.partiallyAnswered',
  pending: 'ai.trace.value.pending',
  running: 'ai.trace.value.running',
  success: 'ai.trace.value.success',
  timeout: 'ai.trace.value.timeout',
  unavailable: 'ai.trace.value.unavailable',
  WEAK_ONLY: 'ai.trace.policy.weakOnly',
  PENDING: 'ai.trace.value.pending',
};

const MEMORY_DECISION_LABELS: Record<string, string> = {
  disabled: 'ai.trace.memoryDecision.disabled',
  no_memory: 'ai.trace.memoryDecision.noMemory',
  stable_scope_only_complete_question: 'ai.trace.memoryDecision.stableScopeOnlyCompleteQuestion',
  question_complete: 'ai.trace.memoryDecision.questionComplete',
  explicit_reference_rewrite: 'ai.trace.memoryDecision.explicitReferenceRewrite',
  stable_scope_only_incomplete_question: 'ai.trace.memoryDecision.stableScopeOnlyIncompleteQuestion',
  context_dependent_low_confidence: 'ai.trace.memoryDecision.contextDependentLowConfidence',
  stable_scope_only_topic_shift: 'ai.trace.memoryDecision.stableScopeOnlyTopicShift',
  topic_shift: 'ai.trace.memoryDecision.topicShift',
  skip: 'ai.trace.memoryDecision.skip',
};

const FIELD_LABELS: Record<string, string> = {
  action: 'ai.trace.field.action',
  answer_policy: 'ai.trace.field.answerPolicy',
  answer_policy_action: 'ai.trace.field.answerPolicyAction',
  answer_shape: 'ai.trace.field.answerShape',
  chat_type: 'ai.trace.field.chatType',
  confidence: 'ai.trace.field.confidence',
  conflict_detected: 'ai.trace.field.conflictDetected',
  direct_llm_used: 'ai.trace.field.directLlmUsed',
  document_id: 'ai.trace.field.documentId',
  drawing_no: 'ai.trace.field.drawingNo',
  evidence_status: 'ai.trace.field.evidenceStatus',
  strong_evidence_count: 'ai.trace.field.strongEvidenceCount',
  weak_evidence_count: 'ai.trace.field.weakEvidenceCount',
  exact_text_search: 'ai.trace.field.exactTextSearch',
  executed_retrievers: 'ai.trace.field.executedRetrievers',
  fallback_ladder: 'ai.trace.field.fallbackLadder',
  fallback_retrievers: 'ai.trace.field.fallbackRetrievers',
  fallback_used: 'ai.trace.field.fallbackUsed',
  graph_retrieval: 'ai.trace.field.graphRetrieval',
  has_doc_code: 'ai.trace.field.hasDocCode',
  has_exact_token: 'ai.trace.field.hasExactToken',
  has_graph_relation: 'ai.trace.field.hasGraphRelation',
  has_page_hint: 'ai.trace.field.hasPageHint',
  has_section_hint: 'ai.trace.field.hasSectionHint',
  has_table_hint: 'ai.trace.field.hasTableHint',
  has_value_hint: 'ai.trace.field.hasValueHint',
  images: 'ai.trace.field.images',
  implementation: 'ai.trace.field.implementation',
  intent: 'ai.trace.field.intent',
  intent_type: 'ai.trace.field.intentType',
  kb_grounded: 'ai.trace.field.kbGrounded',
  keyword_retrieval: 'ai.trace.field.keywordRetrieval',
  knowledge_scope: 'ai.trace.field.knowledgeScope',
  mode: 'ai.trace.field.mode',
  model_route: 'ai.trace.field.modelRoute',
  need_general_confirm: 'ai.trace.field.needGeneralConfirm',
  need_graph_reasoning: 'ai.trace.field.needGraphReasoning',
  need_page_location: 'ai.trace.field.needPageLocation',
  object_type: 'ai.trace.field.objectType',
  page_level_retrieval: 'ai.trace.field.pageLevelRetrieval',
  page_no: 'ai.trace.field.pageNo',
  planned_retrievers: 'ai.trace.field.plannedRetrievers',
  policy_matrix_used: 'ai.trace.field.policyMatrixUsed',
  project_id: 'ai.trace.field.projectId',
  qwen_used: 'ai.trace.field.qwenUsed',
  query_features: 'ai.trace.field.queryFeatures',
  query_profile: 'ai.trace.field.queryProfile',
  query_rewrite: 'ai.trace.field.queryRewrite',
  query_rewrites: 'ai.trace.field.queryRewrites',
  reason: 'ai.trace.field.reason',
  resolved_answer_policy: 'ai.trace.field.resolvedAnswerPolicy',
  resolved_answer_shape: 'ai.trace.field.resolvedAnswerShape',
  resolved_knowledge_scope: 'ai.trace.field.resolvedKnowledgeScope',
  resolved_task_type: 'ai.trace.field.resolvedTaskType',
  retrieval_needs: 'ai.trace.field.retrievalNeeds',
  rule_id: 'ai.trace.field.ruleId',
  semantic_retrieval: 'ai.trace.field.semanticRetrieval',
  selected_retrievers: 'ai.trace.field.selectedRetrievers',
  skip_reasons: 'ai.trace.field.skipReasons',
  skipped_retrievers: 'ai.trace.field.skippedRetrievers',
  source: 'ai.trace.field.source',
  strategy: 'ai.trace.field.strategy',
  task: 'ai.trace.field.task',
  task_type: 'ai.trace.field.taskType',
  user_id: 'ai.trace.field.userId',
  visual_evidence: 'ai.trace.field.visualEvidence',
  answerability_status: 'ai.trace.field.answerabilityStatus',
  answered_intent_ids: 'ai.trace.field.answeredIntentIds',
  citation_ids: 'ai.trace.field.citationIds',
  conclusion: 'ai.trace.field.conclusion',
  depends_on: 'ai.trace.field.dependsOn',
  displayed_intent_ids: 'ai.trace.field.displayedIntentIds',
  executed_intent_ids: 'ai.trace.field.executedIntentIds',
  failure_reason: 'ai.trace.field.failureReason',
  intent_results: 'ai.trace.field.intentResults',
  missing_information: 'ai.trace.field.missingInformation',
  omitted_targets: 'ai.trace.field.omittedTargets',
  original_target: 'ai.trace.field.originalTarget',
  parallel_group_id: 'ai.trace.field.parallelGroupId',
  parent_node_id: 'ai.trace.field.parentNodeId',
  plan_version: 'ai.trace.field.planVersion',
  planned_intent_ids: 'ai.trace.field.plannedIntentIds',
  risk_notices: 'ai.trace.field.riskNotices',
  sub_question_id: 'ai.trace.field.subQuestionId',
  sub_question_outcomes: 'ai.trace.field.subQuestionOutcomes',
  sub_questions: 'ai.trace.field.subQuestions',
  turn_id: 'ai.trace.field.turnId',
  unexpected_intent_ids: 'ai.trace.field.unexpectedIntentIds',
};

const PROVIDER_LABELS: Record<string, string> = {
  dashscope: 'ai.trace.provider.dashscope',
  env_fallback: 'ai.trace.provider.envFallback',
  local: 'ai.trace.provider.local',
  openai: 'OpenAI',
  openai_compatible: 'ai.trace.provider.openaiCompatible',
  qwen: 'ai.trace.provider.qwen',
  qwen_api: 'ai.trace.provider.qwenApi',
};

const QWEN_MODEL_TOKEN_LABELS: Record<string, string> = {
  chat: 'ai.trace.modelToken.chat',
  coder: 'ai.trace.modelToken.coder',
  embedding: 'ai.trace.modelToken.embedding',
  flash: 'ai.trace.modelToken.flash',
  instruct: 'ai.trace.modelToken.instruct',
  max: 'ai.trace.modelToken.max',
  plus: 'ai.trace.modelToken.plus',
  turbo: 'ai.trace.modelToken.turbo',
  vl: 'ai.trace.modelToken.vl',
};

const PAIR_LABELS: Record<string, string> = {
  选择: 'ai.trace.pair.select',
  跳过: 'ai.trace.pair.skip',
  补充: 'ai.trace.pair.supplement',
  关联: 'ai.trace.pair.relation',
  依据: 'ai.trace.pair.evidence',
  改写: 'ai.trace.pair.rewrite',
  冲突: 'ai.trace.pair.conflict',
};

const TRACE_STEP_LABELS: Record<string, string> = {
  会话短期记忆上下文化: 'ai.trace.task.sessionMemory',
  问题理解生成: 'ai.trace.task.questionUnderstanding',
  策略解析: 'ai.trace.task.policyResolution',
  数据检索规划: 'ai.trace.task.planner',
  检索召回与数据组装: 'ai.trace.task.retrieval',
  检索召回执行: 'ai.trace.task.retrieval',
  证据评估: 'ai.trace.task.evidenceJudge',
  资料证据有效性判断: 'ai.trace.task.evidenceJudge',
  回答生成: 'ai.trace.task.answerGenerator',
  多意图执行汇总: 'ai.trace.task.multiIntent',
};

const traceItems = computed<TraceViewItem[]>(() => {
  locale.value;
  return visibleTraceSteps(props.steps).map((step, index) => ({
    key: traceStepKey(step, index),
    index,
    step,
    title: traceStepTitle(step),
    routeItems: modelRouteItems(step),
    routeReason: modelRouteReason(step),
    summary: buildSummaryView(step),
  }));
});

function translatedValue(value: string): string {
  return value.startsWith('ai.') ? t(value) : value;
}

function hasCjkText(value: string): boolean {
  return /[\u3400-\u9fff]/u.test(value);
}

function usesWrongDisplayLanguage(value: string): boolean {
  if (!value) return false;
  if (locale.value === 'en-US') return hasCjkText(value);
  return false;
}

function isInternalIdentifier(value: string): boolean {
  return /^(intent|sub-question|turn|node)[-:][\w:-]+$/i.test(value);
}

function displayTextOrFallback(value: unknown, fallback: string): string {
  const text = rawTextValue(value);
  if (!text || usesWrongDisplayLanguage(text) || isInternalIdentifier(text)) return fallback;
  return localizeKnownCodes(text);
}

function stepSummary(step: AgentTraceStep): string {
  if (step.display_text) return step.display_text;
  if (step.result) return step.result;
  if (step.output_summary && Object.keys(step.output_summary).length) {
    return readableRecordLines(step.output_summary).join('\n');
  }
  if (step.details && Object.keys(step.details).length) {
    const { model_route: _modelRoute, ...visibleDetails } = step.details;
    if (Object.keys(visibleDetails).length) {
      return readableRecordLines(visibleDetails).join('\n');
    }
  }
  return t('ai.trace.executed');
}

function traceStepKey(step: AgentTraceStep, index: number): string {
  return `${step.sequence ?? index}-${step.step}-${step.elapsed_ms ?? 'pending'}`;
}

function traceStepTitle(step: AgentTraceStep): string {
  const rawTitle = step.step || step.implementation || t('ai.trace.generatedStep');
  return translatedValue(TRACE_STEP_LABELS[rawTitle] || localizeKnownCodes(rawTitle));
}

function tagTheme(status?: string): 'primary' | 'success' | 'danger' {
  if (status === 'failed') return 'danger';
  if (status === 'success') return 'success';
  return 'primary';
}

function statusClass(status?: string): string {
  if (status === 'running') return 'running';
  if (status === 'failed') return 'failed';
  return 'success';
}

function statusText(status?: string): string {
  if (status === 'running') return t('ai.trace.status.running');
  if (status === 'failed') return t('ai.trace.status.failed');
  return t('ai.trace.status.success');
}

function elapsedText(step: AgentTraceStep): string {
  return step.elapsed_ms !== undefined && step.elapsed_ms !== null ? `${step.elapsed_ms} ms` : '';
}

function asRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return null;
}

function rawTextValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (Array.isArray(value)) return value.map((item) => rawTextValue(item)).filter(Boolean).join(t('common.separator.list'));
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value).trim();
}

function textValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'boolean') return value ? t('ai.trace.phrase.true') : t('ai.trace.phrase.false');
  if (Array.isArray(value)) return value.map((item) => textValue(item)).filter(Boolean).join(t('common.separator.list'));
  if (typeof value === 'object') return readableValue(value);
  return localizeKnownCodes(String(value).trim());
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function localizeKnownCodes(text: string): string {
  const labels = {
    ...PROFILE_LABELS,
    ...TASK_LABELS,
    ...SOURCE_LABELS,
    ...RETRIEVER_LABELS,
    ...POLICY_LABELS,
    ...MEMORY_DECISION_LABELS,
    ...FIELD_LABELS,
    ...PROVIDER_LABELS,
    ...VALUE_LABELS,
  };
  const phraseReplacements: Array<[RegExp, string]> = [
    [/已完成会话上下文化/g, t('ai.trace.phrase.sessionContextCompleted')],
    [/已生成问题理解/g, t('ai.trace.phrase.questionUnderstandingGenerated')],
    [/已解析最终策略/g, t('ai.trace.phrase.finalPolicyResolved')],
    [/已生成数据检索规划/g, t('ai.trace.phrase.retrievalPlanGenerated')],
    [
      /基于\s*(?:Policy\s*Resolver|PolicyResolver)\s*(?:Resolved Task Type|resolved_task_type)\s*和\s*(?:Question\s*Understanding|QuestionUnderstanding)\s*(?:Retrieval Needs|retrieval_needs)\s*选择检索器/gi,
      t('ai.trace.phrase.retrieverSelectionBasis'),
    ],
    [/未改写检索问题[：:]\s*/g, t('ai.trace.phrase.searchQuestionUnchangedPrefix')],
    [/会话短期记忆/g, t('ai.trace.phrase.sessionMemory')],
    [/问题理解/g, t('ai.trace.phrase.questionUnderstanding')],
    [/策略解析/g, t('ai.trace.phrase.policyResolution')],
    [/数据检索规划/g, t('ai.trace.phrase.retrievalPlanning')],
    [/检索召回与数据组装/g, t('ai.trace.task.retrieval')],
    [/资料证据有效性判断/g, t('ai.trace.task.evidenceJudge')],
    [/证据状态/g, t('ai.trace.field.evidenceStatus')],
    [/强证据/g, t('ai.trace.field.strongEvidenceCount')],
    [/弱证据/g, t('ai.trace.field.weakEvidenceCount')],
    [/语义检索/g, t('ai.trace.retriever.milvus')],
    [/关键词检索/g, t('ai.trace.retriever.keyword')],
    [/页级检索/g, t('ai.trace.retriever.pageIndex')],
    [/精确检索/g, t('ai.trace.phrase.exactTextSearch')],
    [/图谱检索/g, t('ai.trace.retriever.graph')],
    [/冲突\s*否/g, `${t('ai.trace.pair.conflict')} ${t('ai.trace.phrase.false')}`],
    [/冲突\s*是/g, `${t('ai.trace.pair.conflict')} ${t('ai.trace.phrase.true')}`],
    [/冲突/g, t('ai.trace.pair.conflict')],
    [/\bPolicyResolver\b/g, t('ai.trace.phrase.policyResolver')],
    [/\bQuestionUnderstanding\b/g, t('ai.trace.phrase.questionUnderstanding')],
    [/\bretrieval_needs\b/g, t('ai.trace.phrase.retrievalNeeds')],
    [/\bresolved_task_type\b/g, t('ai.trace.phrase.resolvedTaskType')],
    [/\banswer_policy\b/g, t('ai.trace.phrase.answerPolicy')],
    [/\bknowledge_scope\b/g, t('ai.trace.phrase.knowledgeScope')],
    [/\bpolicy_matrix\b/g, t('ai.trace.phrase.policyMatrix')],
    [/\boptional graph retrieval\b/gi, t('ai.trace.phrase.optionalGraphRetrieval')],
    [/\bexact_text_search\b/g, t('ai.trace.phrase.exactTextSearch')],
    [/\btrue\b/g, t('ai.trace.phrase.true')],
    [/\bfalse\b/g, t('ai.trace.phrase.false')],
  ];
  const replacedText = phraseReplacements
    .reduce((result, [pattern, replacement]) => result.replace(pattern, replacement), text)
    .replace(/\bintent-(\d+)-sub-(\d+)\b/g, (_match, intent: string, subQuestion: string) =>
      t('ai.trace.phrase.subQuestionWithIndex', { intent, subQuestion }),
    )
    .replace(/\bintent-(\d+)\b/g, (_match, index: string) => t('ai.trace.phrase.intentWithIndex', { index }));
  const localizedText = Object.entries(labels)
    .sort(([left], [right]) => right.length - left.length)
    .reduce((result, [code, label]) => {
      const pattern = new RegExp(`(^|[^A-Za-z0-9_])${escapeRegExp(code)}(?=$|[^A-Za-z0-9_])`, 'g');
      return result.replace(pattern, `$1${translatedValue(label)}`);
    }, replacedText);
  return locale.value === 'en-US' ? localizedText.replace(/[、，]/g, ', ') : localizedText;
}

function readableLabel(key: string): string {
  return localizeKnownCodes(key);
}

function readableValue(value: unknown): string {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'boolean') return value ? t('ai.trace.phrase.true') : t('ai.trace.phrase.false');
  if (Array.isArray(value)) return value.map((item) => readableValue(item)).filter(Boolean).join(t('common.separator.list'));
  if (typeof value === 'object') {
    const record = asRecord(value);
    if (!record) return '';
    return Object.entries(record)
      .map(([key, item]) => {
        const text = readableValue(item);
        return text ? `${readableLabel(key)}: ${text}` : '';
      })
      .filter(Boolean)
      .join('; ');
  }
  return localizeKnownCodes(String(value).trim());
}

function readableRecordLines(record: Record<string, unknown>): string[] {
  return Object.entries(record)
    .map(([key, value]) => {
      const text = readableValue(value);
      return text ? `${readableLabel(key)}: ${text}` : '';
    })
    .filter(Boolean);
}

function providerText(value: unknown): string {
  const text = rawTextValue(value);
  return translatedValue(PROVIDER_LABELS[text.toLowerCase()] || localizeKnownCodes(text));
}

function modelNameText(value: unknown): string {
  const text = rawTextValue(value);
  const normalized = text.toLowerCase();
  if (!normalized.startsWith('qwen')) return localizeKnownCodes(text);

  const tokens = normalized
    .replace(/^qwen[-/]?/, '')
    .split('-')
    .map((item) => item.trim())
    .filter(Boolean);
  if (!tokens.length) return t('ai.trace.phrase.qwen');

  const suffix = tokens.map((token) => translatedValue(QWEN_MODEL_TOKEN_LABELS[token] || token.toUpperCase())).join(' ');
  return `${t('ai.trace.phrase.qwen')} ${suffix}`;
}

function modelRoute(step: AgentTraceStep): Record<string, unknown> | null {
  const route = asRecord(step.details?.model_route);
  if (!route) return null;
  const hasMeaningfulValue = Object.entries(route).some(([key, value]) => {
    const text = rawTextValue(value);
    return text && !(key === 'source' && text === 'unknown');
  });
  if (hasMeaningfulValue) {
    return route;
  }
  return null;
}

function translateCode(value: unknown, labels: Record<string, string>): string {
  const text = rawTextValue(value);
  return translatedValue(labels[text] || labels[text.toLowerCase()] || localizeKnownCodes(text));
}

function modelRouteItems(step: AgentTraceStep): TraceRouteItem[] {
  const route = modelRoute(step);
  if (!route) return [];
  const items: TraceRouteItem[] = [];
  const source = rawTextValue(route.source);
  const sourceIsInternalRule = ['rules', 'rules_fast_path', 'not_called'].includes(source);
  if (source && source !== 'unknown' && !sourceIsInternalRule) {
    items.push({ label: t('ai.trace.route.method'), value: translateCode(source, SOURCE_LABELS) });
  }
  if (route.model_type) {
    items.push({ label: t('ai.trace.route.type'), value: translateCode(route.model_type, TASK_LABELS) });
  }
  if (route.provider) {
    items.push({ label: t('ai.trace.route.service'), value: providerText(route.provider) });
  }
  if (route.model_name) {
    items.push({ label: t('ai.trace.route.model'), value: modelNameText(route.model_name) });
  }
  if (!items.length && route.task) {
    items.push({ label: t('ai.trace.route.task'), value: translateCode(route.task, TASK_LABELS) });
  }
  return items;
}

function modelRouteReason(step: AgentTraceStep): string {
  const route = modelRoute(step);
  if (!route) return '';
  const source = rawTextValue(route.source);
  if (['rules', 'rules_fast_path', 'not_called'].includes(source)) return '';
  const reason = rawTextValue(route.reason);
  if (!reason) return '';
  if (shouldShowRetrieverMetrics(step)) return localizeKnownCodes(reason);
  const cleanedReason = reason.replace(/[，,；;]?\s*(evidence|hits|images|tables)\s*=\s*[\w.-]+/gi, '').trim();
  return localizeKnownCodes(cleanedReason);
}

function splitSummaryLines(text: string): string[] {
  return text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function retrieverLabel(name: string): string {
  const normalized = name.trim();
  return translatedValue(RETRIEVER_LABELS[normalized] || RETRIEVER_LABELS[normalized.toLowerCase()] || localizeKnownCodes(normalized));
}

function parseHitLine(line: string): TraceMetric | null {
  const match = line.match(/^(.+?)\s*命中\s*(\d+)\s*条$/);
  if (!match) return null;
  return {
    label: retrieverLabel(match[1]),
    value: match[2],
    suffix: t('ai.trace.unit.items'),
  };
}

function shouldShowRetrieverMetrics(step: AgentTraceStep): boolean {
  const implementation = String(step.implementation || '');
  const stepName = step.step || '';
  return (
    implementation === 'router+reranker' ||
    stepName.includes('检索召回') ||
    stepName.includes('检索执行') ||
    stepName.includes('补充检索')
  );
}

function metricsFromDetails(step: AgentTraceStep): TraceMetric[] {
  if (!shouldShowRetrieverMetrics(step)) return [];
  const hits = asRecord(step.details?.retriever_hits);
  if (!hits) return [];
  const orderedNames = ['project_metadata', 'milvus', 'keyword', 'page_index', 'ripgrep', 'graphrag'];
  const names = [
    ...orderedNames.filter((name) => Object.prototype.hasOwnProperty.call(hits, name)),
    ...Object.keys(hits).filter((name) => !orderedNames.includes(name)),
  ];
  return names
    .map((name) => {
      const hitCount = Number(hits[name] ?? 0);
      if (Number.isNaN(hitCount)) return null;
      return {
        label: retrieverLabel(name),
        value: String(hitCount),
        suffix: t('ai.trace.unit.items'),
      };
    })
    .filter((item): item is TraceMetric => Boolean(item));
}

function parseDisplayPair(line: string): TracePair | null {
  const match = line.match(/^([^：:]{1,8})[：:]\s*(.+)$/);
  if (!match) return null;
  const label = match[1].trim();
  const labelKey = PAIR_LABELS[label];
  if (!labelKey) return null;
  return {
    label: t(labelKey),
    value: localizeKnownCodes(match[2].trim()),
  };
}

function querySummaryView(text: string): TraceSummaryView | null {
  const match = text.match(/^生成\s*(\d+)\s*个检索问题[：:]\s*([\s\S]+)$/);
  if (!match) return null;
  const queries = match[2].split(/[；;]\s*/).map((item) => item.trim()).filter(Boolean);
  return {
    lead: t('ai.trace.summary.generatedQueries', { count: match[1] }),
    lines: [],
    metrics: [],
    pairs: [],
    queries: queries.length ? queries : [match[2].trim()],
  };
}

function evidenceSummaryView(text: string): TraceSummaryView | null {
  const match = text.match(
    /^证据状态[：:]\s*([^，,\n]+)[，,]\s*强证据\s*(\d+)\s*条[，,]\s*弱证据\s*(\d+)\s*条[，,]\s*合并后保留\s*(\d+)\s*条证据(?:\s*\n\s*关联\s*(\d+)\s*张图纸图片)?$/,
  );
  if (!match) return null;
  const [, status, strongCount, weakCount, retainedCount, imageCount] = match;
  const metrics: TraceMetric[] = [
    { label: t('ai.trace.field.strongEvidenceCount'), value: strongCount, suffix: t('ai.trace.unit.items') },
    { label: t('ai.trace.field.weakEvidenceCount'), value: weakCount, suffix: t('ai.trace.unit.items') },
    { label: t('ai.trace.field.retainedEvidenceCount'), value: retainedCount, suffix: t('ai.trace.unit.items') },
  ];
  if (imageCount !== undefined) {
    metrics.push({ label: t('ai.trace.field.linkedImageCount'), value: imageCount, suffix: t('ai.trace.unit.images') });
  }
  return {
    lead: t('ai.trace.summary.evidenceStatus', { status: translateTraceStatus(status.trim()) }),
    lines: [],
    metrics,
    pairs: [],
    queries: [],
  };
}

function objectArray(value: unknown): Record<string, unknown>[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => asRecord(item)).filter((item): item is Record<string, unknown> => Boolean(item));
}

function localizedIntentTitle(record: Record<string, unknown>, index: number): string {
  const order = Number(record.order);
  const fallbackIndex = Number.isFinite(order) && order > 0 ? order : index + 1;
  return displayTextOrFallback(record.name || record.original_target, t('ai.trace.phrase.intentWithIndex', { index: fallbackIndex }));
}

function translateTraceStatus(value: unknown): string {
  return translateCode(value || 'unavailable', VALUE_LABELS);
}

function multiIntentSummaryView(step: AgentTraceStep): TraceSummaryView | null {
  if (step.implementation !== 'multi_intent_orchestration') return null;
  const details = asRecord(step.details);
  const intentResults = objectArray(details?.intent_results);
  if (!intentResults.length) return null;

  const lines = intentResults.map((record, index) => {
    const order = Number(record.order);
    const displayOrder = Number.isFinite(order) && order > 0 ? order : index + 1;
    return t('ai.trace.summary.multiIntentItem', {
      order: displayOrder,
      title: localizedIntentTitle(record, index),
      status: translateTraceStatus(record.status || 'completed'),
      answerability: translateTraceStatus(record.answerability_status || 'unavailable'),
    });
  });

  const omittedCount = Array.isArray(details?.omitted_targets) ? details.omitted_targets.length : 0;
  if (omittedCount > 0) {
    lines.push(t('ai.trace.summary.multiIntentOmitted', { count: omittedCount }));
  }

  return {
    lead: t('ai.trace.summary.multiIntentCompleted', { count: intentResults.length }),
    lines,
    metrics: [],
    pairs: [],
    queries: [],
  };
}

function fallbackLead(step: AgentTraceStep, metrics: TraceMetric[], pairs: TracePair[]): string {
  if (metrics.length) return t('ai.trace.summary.retrievalStats');
  if (pairs.some((item) => item.label === t('ai.trace.pair.select'))) return t('ai.trace.summary.retrieversSelected');
  if (step.status === 'running') return t('ai.trace.summary.running');
  return t('ai.trace.executed');
}

function buildSummaryView(step: AgentTraceStep): TraceSummaryView {
  const multiIntentView = multiIntentSummaryView(step);
  if (multiIntentView) return multiIntentView;

  const rawSummaryText = stepSummary(step).trim();
  const evidenceView = evidenceSummaryView(rawSummaryText);
  if (evidenceView) return evidenceView;

  const text = localizeKnownCodes(rawSummaryText);
  const queryView = querySummaryView(text);
  if (queryView) return queryView;

  const lines = splitSummaryLines(text);
  const metrics = metricsFromDetails(step);
  const parsedMetrics: TraceMetric[] = [];
  const remainingLines: string[] = [];

  lines.forEach((line) => {
    const metric = parseHitLine(line);
    if (metric) {
      parsedMetrics.push(metric);
      return;
    }
    remainingLines.push(line);
  });

  const effectiveMetrics = metrics.length ? metrics : parsedMetrics;
  const pairs: TracePair[] = [];
  let detailLines: string[] = [];

  remainingLines.forEach((line) => {
    const pair = parseDisplayPair(line);
    if (pair) {
      pairs.push(pair);
      return;
    }
    detailLines.push(line);
  });
  if (effectiveMetrics.length && shouldShowRetrieverMetrics(step)) {
    detailLines = detailLines.filter((line) => !line.toLowerCase().startsWith('retriever_hits'));
  }

  return {
    lead: detailLines.shift() || fallbackLead(step, effectiveMetrics, pairs),
    lines: detailLines,
    metrics: effectiveMetrics,
    pairs,
    queries: [],
  };
}
</script>

<template>
  <t-empty v-if="!traceItems.length" size="small" :description="t('ai.trace.empty')" />
  <div v-else class="trace-list">
    <article v-for="item in traceItems" :key="item.key" class="trace-card" :class="statusClass(item.step.status)">
      <div class="trace-header">
        <div class="trace-title">
          <span class="trace-index">{{ item.index + 1 }}</span>
          <strong>{{ item.title }}</strong>
        </div>
        <div class="trace-meta">
          <span v-if="elapsedText(item.step)" class="trace-time">{{ elapsedText(item.step) }}</span>
          <t-tag size="small" variant="light" :theme="tagTheme(item.step.status)">
            {{ statusText(item.step.status) }}
          </t-tag>
        </div>
      </div>

      <section class="trace-summary">
        <p class="trace-lead">{{ item.summary.lead }}</p>

        <div v-if="item.summary.metrics.length" class="trace-metrics">
          <div v-for="metric in item.summary.metrics" :key="`${item.key}-${metric.label}`" class="trace-metric">
            <span>{{ metric.label }}</span>
            <strong>{{ metric.value }}</strong>
            <em>{{ metric.suffix }}</em>
          </div>
        </div>

        <div v-if="item.summary.pairs.length" class="trace-pairs">
          <div v-for="pair in item.summary.pairs" :key="`${item.key}-${pair.label}`" class="trace-pair">
            <span>{{ pair.label }}</span>
            <strong>{{ pair.value }}</strong>
          </div>
        </div>

        <ol v-if="item.summary.queries.length" class="trace-query-list">
          <li v-for="query in item.summary.queries" :key="`${item.key}-${query}`">{{ query }}</li>
        </ol>

        <p v-for="line in item.summary.lines" :key="`${item.key}-${line}`" class="trace-line">{{ line }}</p>
      </section>

      <div v-if="item.routeItems.length || item.routeReason" class="trace-route">
        <div v-if="item.routeItems.length" class="route-chips">
          <span v-for="routeItem in item.routeItems" :key="`${item.key}-${routeItem.label}`" class="route-chip">
            <em>{{ routeItem.label }}</em>
            {{ routeItem.value }}
          </span>
        </div>
        <p v-if="item.routeReason" class="route-reason">{{ t('ai.trace.route.reason', { reason: item.routeReason }) }}</p>
      </div>
    </article>
  </div>
</template>

<style scoped>
.trace-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 2px 4px 8px;
}

.trace-card {
  position: relative;
  overflow: hidden;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 9px 10px 9px 13px;
}

.trace-card::before {
  position: absolute;
  top: 10px;
  bottom: 10px;
  left: 0;
  width: 2px;
  border-radius: 999px;
  background: #00a870;
  content: '';
}

.trace-card.running::before {
  background: #2f6fed;
}

.trace-card.failed::before {
  background: #d54941;
}

.trace-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  color: #334155;
  font-size: 13px;
}

.trace-title {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.trace-index {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: #eef4ff;
  color: #2f6fed;
  font-size: 12px;
  font-weight: 700;
}

.trace-title strong {
  min-width: 0;
  overflow: hidden;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  flex: 0 0 auto;
  color: #6b7280;
  font-size: 12px;
}

.trace-time {
  color: #64748b;
  font-variant-numeric: tabular-nums;
}

.trace-summary {
  margin-top: 7px;
  border-radius: 6px;
  background: #f9fbfd;
  padding: 7px 9px;
}

.trace-lead {
  margin: 0;
  color: #1f2937;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
  word-break: break-word;
}

.trace-line {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
  word-break: break-word;
}

.trace-metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 5px;
  margin-top: 7px;
}

.trace-metric {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: baseline;
  gap: 4px;
  border: 1px solid #e6edf5;
  border-radius: 6px;
  background: #fff;
  padding: 5px 7px;
}

.trace-metric span {
  min-width: 0;
  overflow: hidden;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.trace-metric strong {
  color: #111827;
  font-size: 15px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}

.trace-metric em {
  color: #64748b;
  font-size: 11px;
  font-style: normal;
}

.trace-pairs {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 7px;
}

.trace-pair {
  display: flex;
  gap: 8px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
}

.trace-pair span {
  flex: 0 0 34px;
}

.trace-pair strong {
  min-width: 0;
  color: #334155;
  font-weight: 600;
  word-break: break-word;
}

.trace-query-list {
  max-height: 96px;
  margin: 7px 0 0;
  overflow: auto;
  padding-left: 18px;
  color: #475569;
  font-size: 12px;
  line-height: 1.45;
}

.trace-query-list li + li {
  margin-top: 4px;
}

.trace-route {
  margin-top: 7px;
  border-top: 1px solid #edf2f7;
  padding-top: 7px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
  word-break: break-word;
}

.route-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.route-chip {
  display: inline-flex;
  max-width: 100%;
  align-items: center;
  gap: 4px;
  border-radius: 999px;
  background: #f1f5f9;
  padding: 3px 8px;
  color: #475569;
  line-height: 1.4;
}

.route-chip em {
  color: #64748b;
  font-style: normal;
}

.route-reason {
  margin: 6px 0 0;
  color: #64748b;
}
</style>
