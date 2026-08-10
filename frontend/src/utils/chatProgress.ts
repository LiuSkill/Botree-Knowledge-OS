import type {
  AgentTraceStep,
  ChatProgressEvent,
  ChatProgressStage,
  ChatProgressStatus,
  ChatTraceDeltaEvent,
} from '@/types/api';
import { i18n } from '@/locales';

export interface ChatProgressStageConfig {
  stage: ChatProgressStage;
  title: string;
}

export interface ChatProgressRow extends ChatProgressStageConfig {
  key: string;
  status: ChatProgressStatus;
  detail: string;
}

export const CHAT_PROGRESS_STAGES: ChatProgressStageConfig[] = [
  { stage: 'understanding', title: 'ai.progress.stages.understanding.title' },
  { stage: 'planning', title: 'ai.progress.stages.planning.title' },
  { stage: 'retrieving', title: 'ai.progress.stages.retrieving.title' },
  { stage: 'filtering', title: 'ai.progress.stages.filtering.title' },
  { stage: 'answering', title: 'ai.progress.stages.answering.title' },
];

const STAGE_TITLE_BY_KEY = CHAT_PROGRESS_STAGES.reduce<Record<ChatProgressStage, string>>(
  (result, item) => ({ ...result, [item.stage]: item.title }),
  {} as Record<ChatProgressStage, string>,
);

const STAGE_INDEX = CHAT_PROGRESS_STAGES.reduce<Record<ChatProgressStage, number>>(
  (result, item, index) => ({ ...result, [item.stage]: index }),
  {} as Record<ChatProgressStage, number>,
);

function stageTitle(stage: ChatProgressStage): string {
  return i18n.global.t(`ai.progress.stages.${stage}.title`);
}

function stageDetail(stage: ChatProgressStage, status: ChatProgressStatus): string {
  return i18n.global.t(`ai.progress.stages.${stage}.${status}`);
}

function currentLocale(): string {
  return String(i18n.global.locale.value || 'zh-CN');
}

function hasCjkText(value: string): boolean {
  return /[\u3400-\u9fff]/u.test(value);
}

function isAsciiOnlyText(value: string): boolean {
  return /^[\x00-\x7f\s.,;:!?()'"-]+$/u.test(value);
}

function usesWrongDisplayLanguage(value: string): boolean {
  if (!value) return false;
  if (currentLocale() === 'en-US') return hasCjkText(value);
  if (currentLocale() === 'zh-CN') return isAsciiOnlyText(value);
  return false;
}

const TRACE_STAGE_KEYWORDS: Array<[ChatProgressStage, string[]]> = [
  [
    'understanding',
    [
      '问答模式策略',
      '问答策略',
      '通用回答确认状态',
      '确认状态',
      '快速意图门控',
      '用户意图识别',
      '意图识别',
      '答案策略路由',
      '答案策略',
      'chat_policy',
      'confirm_state',
      'pre_intent_gate',
      'intent',
      'answer_policy_router',
    ],
  ],
  [
    'planning',
    [
      '任务拆解',
      '查询拆解',
      '查询画像生成',
      '查询画像',
      '问题理解生成',
      '问题理解',
      '策略解析',
      '数据检索规划',
      '检索规划',
      'query_decompose',
      'query_profile',
      'question_understanding',
      'policy_resolution',
      'planner',
    ],
  ],
  [
    'retrieving',
    [
      '检索执行',
      '向量检索',
      '关键词检索',
      '页级检索',
      '图谱检索',
      '精准检索',
      '精确检索',
      '项目资料检索',
      '内部知识检索',
      '检索召回与数据组装',
      '补充检索',
      '视觉图纸阅读',
      'retrieval',
      'retry_retrieval',
      'visual_reading',
      'visual_evidence',
    ],
  ],
  [
    'filtering',
    [
      '证据判断',
      '证据筛选',
      '资料聚合',
      '证据状态',
      '答案门控',
      '答案策略门控',
      'evidence_judge',
      'evidence_decision',
      'answer_policy_gate',
      'rerank',
      'context build',
    ],
  ],
  ['answering', ['回答生成', 'LLM生成', 'answer', 'answer_generator', 'direct_answer']],
];

const RETRIEVAL_EMPTY_PATTERNS = ['未命中有效资料', '未找到足够的相关资料'];
const PROJECT_REFUSAL_PATTERNS = ['当前项目资料中未检索到', '当前项目资料中未找到'];

const FORBIDDEN_DETAIL_PATTERNS = [
  'intent',
  'route',
  'implementation',
  'query_type',
  'answer_shape',
  'task_type',
  'answer_policy',
  'STRICT_KB',
  'project_id',
  'user_id',
  'run_id',
  'skip_retrieval',
  'direct_answer_type',
  'sub_query_total',
  'evidence_count',
  'project_metadata',
  'page_index',
  'ripgrep',
  'milvus',
  'graphrag',
  'semantic_search',
  'keyword_search',
  'exact_search',
  'rerank',
  'planner',
  'evidence_judge',
  'answer_generator',
  'LangGraph',
  'Python',
  'Service',
  'Node',
  'elapsed',
  'duration',
  'latency',
  'ms',
];

function containsInternalProgressToken(value: string): boolean {
  const lowered = value.toLowerCase();
  return FORBIDDEN_DETAIL_PATTERNS.some((pattern) => lowered.includes(pattern.toLowerCase()));
}

function isProgressStage(value: unknown): value is ChatProgressStage {
  return typeof value === 'string' && value in STAGE_TITLE_BY_KEY;
}

function normalizeStatus(value: unknown): ChatProgressStatus {
  if (value === 'pending' || value === 'running' || value === 'success' || value === 'failed') {
    return value;
  }
  return 'success';
}

function safeTitle(stage: ChatProgressStage, status: ChatProgressStatus, sourceText = ''): string {
  if (stage === 'retrieving' && status === 'failed') {
    return stageDetail('retrieving', 'failed');
  }
  if (stage === 'retrieving' && RETRIEVAL_EMPTY_PATTERNS.some((pattern) => sourceText.includes(pattern))) {
    return i18n.global.t('ai.progress.stages.retrieving.emptyTitle');
  }
  return stageTitle(stage);
}

function defaultDetail(stage: ChatProgressStage, status: ChatProgressStatus, sourceText = ''): string {
  if (stage === 'retrieving' && status === 'failed') {
    return i18n.global.t('ai.progress.stages.retrieving.failedDetail');
  }
  if (stage === 'retrieving' && RETRIEVAL_EMPTY_PATTERNS.some((pattern) => sourceText.includes(pattern))) {
    return i18n.global.t('ai.progress.stages.retrieving.emptyDetail');
  }
  if (PROJECT_REFUSAL_PATTERNS.some((pattern) => sourceText.includes(pattern))) {
    return i18n.global.t('ai.progress.stages.retrieving.projectRefusalDetail');
  }
  return stageDetail(stage, status);
}

function safeDetail(
  stage: ChatProgressStage,
  status: ChatProgressStatus,
  sourceText = '',
  candidate?: string | null,
): string {
  const trimmedDetail = typeof candidate === 'string' ? candidate.trim() : '';
  if (
    trimmedDetail &&
    !usesWrongDisplayLanguage(trimmedDetail) &&
    trimmedDetail.length <= 80 &&
    !containsInternalProgressToken(trimmedDetail)
  ) {
    return trimmedDetail;
  }
  return defaultDetail(stage, status, sourceText);
}

function safeInlineText(candidate?: string | null): string {
  const trimmed = typeof candidate === 'string' ? candidate.trim() : '';
  if (!trimmed || trimmed.length > 80 || usesWrongDisplayLanguage(trimmed) || containsInternalProgressToken(trimmed)) return '';
  return trimmed;
}

function intentTitle(event: ChatProgressEvent, intentCount: number): string {
  const readableName = safeInlineText(event.intent_name || event.title);
  if (readableName) return readableName;
  return i18n.global.t('ai.progress.intentTitle', {
    current: event.intent_order ?? 1,
    total: event.intent_total ?? intentCount,
  });
}

function rowTitle(event: ChatProgressEvent, intentCount = 1): string {
  if (event.intent_id) return intentTitle(event, intentCount);
  return safeTitle(event.stage, normalizeStatus(event.status), event.title);
}

function customProgressDetail(event: ChatProgressEvent): string | null {
  const eventType = event.event_type || '';
  const executionStatus = event.execution_status || (event.status === 'failed' ? 'failed' : 'completed');
  const answerabilityStatus = event.answerability_status || 'unavailable';

  if (eventType === 'turn.planned') return i18n.global.t('ai.progress.custom.turnPlanned');
  if (eventType === 'answer.composing') return i18n.global.t('ai.progress.custom.answerComposing');
  if (eventType === 'answer.completed') return i18n.global.t('ai.progress.custom.answerCompleted');
  if (eventType === 'intent.retrieving') return i18n.global.t('ai.progress.custom.intentRetrieving');
  if (eventType === 'intent.started') return i18n.global.t('ai.progress.custom.intentStarted');
  if (executionStatus === 'timeout') return i18n.global.t('ai.progress.custom.timeout');
  if (executionStatus === 'failed') return i18n.global.t('ai.progress.custom.failed');
  if (answerabilityStatus === 'answered') return i18n.global.t('ai.progress.custom.answered');
  if (answerabilityStatus === 'partially_answered') return i18n.global.t('ai.progress.custom.partiallyAnswered');
  if (answerabilityStatus === 'insufficient_evidence') return i18n.global.t('ai.progress.custom.insufficientEvidence');
  if (eventType === 'intent.evidence_evaluated') return i18n.global.t('ai.progress.custom.evidenceEvaluated');
  if (eventType === 'intent.completed') return i18n.global.t('ai.progress.custom.completed');
  return null;
}

function rowDetail(event: ChatProgressEvent): string {
  return customProgressDetail(event) || safeDetail(event.stage, normalizeStatus(event.status), event.title, event.detail);
}

function traceText(step: Partial<AgentTraceStep>): string {
  return [step.step, step.implementation, step.display_text, step.result]
    .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
    .join('\n');
}

function resolveStageFromTrace(step: Partial<AgentTraceStep> & { stage?: unknown }): ChatProgressStage | null {
  if (isProgressStage(step.stage)) return step.stage;
  const rawText = traceText(step);
  const lowerText = rawText.toLowerCase();
  for (const [stage, keywords] of TRACE_STAGE_KEYWORDS) {
    if (keywords.some((keyword) => lowerText.includes(keyword.toLowerCase()))) {
      return stage;
    }
  }
  return null;
}

export function progressEventFromTrace(step: ChatTraceDeltaEvent | AgentTraceStep): ChatProgressEvent | null {
  const stage = resolveStageFromTrace(step);
  if (!stage) return null;
  const status = normalizeStatus(step.status);
  const sourceText = traceText(step);
  return {
    visible: true,
    stage,
    title: safeTitle(stage, status, sourceText),
    status,
    detail: safeDetail(stage, status, sourceText),
    sequence: step.sequence ?? null,
  };
}

export function parseProgressJson(rawValue?: string | null): ChatProgressEvent[] {
  if (!rawValue) return [];
  try {
    const parsed = JSON.parse(rawValue) as unknown;
    if (!Array.isArray(parsed)) return [];
    return normalizeProgressEvents(parsed.filter(isRawProgressEvent));
  } catch {
    return [];
  }
}

export function progressEventsFromTrace(steps: AgentTraceStep[], completed = false): ChatProgressEvent[] {
  const events = normalizeProgressEvents(steps.map(progressEventFromTrace).filter(Boolean) as ChatProgressEvent[]);
  if (completed && events.length) {
    const hasAnswering = events.some((event) => event.stage === 'answering');
    const answeringEvent: ChatProgressEvent = {
      visible: true,
      stage: 'answering',
      title: stageTitle('answering'),
      status: 'success',
      detail: safeDetail('answering', 'success'),
      sequence: null,
    };
    const completedEvents = hasAnswering
      ? events
      : [...events, answeringEvent];
    return markProgressComplete(completedEvents);
  }
  return events;
}

export function mergeProgressEvent(items: ChatProgressEvent[], nextEvent: ChatProgressEvent | null): ChatProgressEvent[] {
  if (!nextEvent || nextEvent.visible !== true) return items;
  return normalizeProgressEvents([...items, sanitizeProgressEvent(nextEvent)]);
}

export function normalizeProgressEvents(events: ChatProgressEvent[]): ChatProgressEvent[] {
  const byKey = new Map<string, ChatProgressEvent>();
  for (const event of events) {
    if (!isProgressStage(event.stage)) continue;
    const key = [event.turn_id ?? '', event.plan_version ?? '', event.intent_id ?? '', event.event_type ?? event.stage, event.stage].join(':');
    byKey.set(key, sanitizeProgressEvent(event));
  }
  const normalized = Array.from(byKey.values()).sort((left, right) => (left.sequence ?? 0) - (right.sequence ?? 0));
  if (normalized.some((event) => event.event_type || event.intent_id)) {
    return normalized;
  }
  const byStage = new Map(normalized.map((item) => [item.stage, item]));
  return CHAT_PROGRESS_STAGES.map((item) => byStage.get(item.stage)).filter(Boolean) as ChatProgressEvent[];
}

export function buildProgressRows(events: ChatProgressEvent[], streaming = false): ChatProgressRow[] {
  const normalized = normalizeProgressEvents(events);
  if (normalized.some((event) => event.intent_id || event.event_type)) {
    const intentLatest = new Map<string, ChatProgressEvent>();
    let answeringEvent: ChatProgressEvent | null = null;
    for (const event of normalized) {
      if (event.intent_id) {
        intentLatest.set(event.intent_id, event);
        continue;
      }
      if (event.event_type === 'answer.composing' || event.event_type === 'answer.completed') {
        answeringEvent = event;
      }
    }
    const rows: ChatProgressRow[] = Array.from(intentLatest.values())
      .sort((left, right) => (left.intent_order ?? 0) - (right.intent_order ?? 0))
      .map((event) => ({
        key: event.intent_id || `${event.stage}:${event.sequence ?? ''}`,
        stage: event.stage,
        title: rowTitle(event, intentLatest.size),
        status: streaming && event.status === 'pending' ? 'running' : toVisibleStatus(event.status),
        detail: rowDetail(event) || i18n.global.t('ai.progress.intentDetail', { current: event.intent_order ?? 1, total: event.intent_total ?? intentLatest.size }),
      }));
    if (answeringEvent) {
      rows.push({
        key: answeringEvent.event_type || `answering:${answeringEvent.sequence ?? ''}`,
        stage: answeringEvent.stage,
        title: rowTitle(answeringEvent),
        status: streaming && answeringEvent.status === 'pending' ? 'running' : toVisibleStatus(answeringEvent.status),
        detail: rowDetail(answeringEvent),
      });
    }
    return rows;
  }
  const eventByStage = new Map(normalized.map((item) => [item.stage, item]));
  if (normalized.some((event) => event.compact)) {
    return normalized.map((event) => ({
      key: event.event_type || event.stage,
      stage: event.stage,
      title: rowTitle(event),
      status: streaming && event.status === 'pending' ? 'running' : toVisibleStatus(event.status),
      detail: rowDetail(event),
    }));
  }
  let activeIndex = -1;
  for (const event of normalized) {
    activeIndex = Math.max(activeIndex, STAGE_INDEX[event.stage]);
  }
  if (activeIndex < 0) {
    if (!streaming) return [];
    activeIndex = 0;
  }
  if (streaming && activeIndex < CHAT_PROGRESS_STAGES.length - 1) {
    const activeStage = CHAT_PROGRESS_STAGES[activeIndex].stage;
    const activeEvent = eventByStage.get(activeStage);
    if (activeEvent && normalizeStatus(activeEvent.status) === 'success') {
      activeIndex += 1;
    }
  }

  return CHAT_PROGRESS_STAGES.slice(0, activeIndex + 1).map((config, index) => {
    const event = eventByStage.get(config.stage);
    if (activeIndex >= 0 && index < activeIndex) {
      const completedDetail = event && normalizeStatus(event.status) === 'success' ? event.detail : null;
      return {
        key: config.stage,
        ...config,
        title: event ? rowTitle(event) : stageTitle(config.stage),
        status: 'success',
        detail: safeDetail(config.stage, 'success', event?.title ?? '', completedDetail),
      };
    }
    if (event) {
      const eventStatus = toVisibleStatus(event.status);
      const status = streaming && index === activeIndex && eventStatus === 'pending' ? 'running' : eventStatus;
      return {
        key: config.stage,
        ...config,
        title: rowTitle(event),
        status,
        detail: rowDetail(event),
      };
    }
    if (streaming && index === activeIndex) {
      return { key: config.stage, ...config, title: stageTitle(config.stage), status: 'running', detail: safeDetail(config.stage, 'running') };
    }
    return { key: config.stage, ...config, title: stageTitle(config.stage), status: 'pending', detail: safeDetail(config.stage, 'pending') };
  });
}

export function markProgressComplete(events: ChatProgressEvent[]): ChatProgressEvent[] {
  const normalized = normalizeProgressEvents(events);
  if (normalized.some((event) => event.intent_id)) {
    return normalized.map((event) => ({
      ...event,
      status: event.status === 'failed' ? 'failed' : 'success',
    }));
  }
  const byStage = new Map(normalized.map((item) => [item.stage, item]));
  const latestIndex = Math.max(...Array.from(byStage.keys()).map((stage) => STAGE_INDEX[stage]), -1);
  if (latestIndex < 0) return [];
  return CHAT_PROGRESS_STAGES.slice(0, latestIndex + 1).map((item) => ({
    visible: true,
    stage: item.stage,
    title: stageTitle(item.stage),
    status: 'success',
    detail: safeDetail(item.stage, 'success', byStage.get(item.stage)?.title ?? '', byStage.get(item.stage)?.detail),
    sequence: byStage.get(item.stage)?.sequence ?? null,
  }));
}

export function restoreStoredProgress(events: ChatProgressEvent[], completed: boolean): ChatProgressEvent[] {
  return completed ? markProgressComplete(events) : events;
}

function isRawProgressEvent(value: unknown): value is ChatProgressEvent {
  if (!value || typeof value !== 'object') return false;
  const record = value as Record<string, unknown>;
  return record.visible === true && isProgressStage(record.stage);
}

function sanitizeProgressEvent(event: ChatProgressEvent): ChatProgressEvent {
  const status = normalizeStatus(event.status);
  return {
    visible: true,
    stage: event.stage,
    title: safeTitle(event.stage, status, event.title),
    status,
    detail: safeDetail(event.stage, status, event.title, event.detail),
    sequence: event.sequence ?? null,
    compact: event.compact === true,
    intent_id: event.intent_id ?? null,
    intent_name: event.intent_name ?? null,
    intent_order: event.intent_order ?? null,
    intent_total: event.intent_total ?? null,
    event_type: event.event_type ?? null,
    turn_id: event.turn_id ?? null,
    plan_version: event.plan_version ?? null,
    execution_status: event.execution_status ?? null,
    answerability_status: event.answerability_status ?? null,
  };
}

function toVisibleStatus(status: ChatProgressStatus): ChatProgressStatus {
  if (status === 'failed') return 'failed';
  if (status === 'success') return 'success';
  if (status === 'pending') return 'pending';
  return 'running';
}
