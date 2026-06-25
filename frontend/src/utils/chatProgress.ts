import type {
  AgentTraceStep,
  ChatProgressEvent,
  ChatProgressStage,
  ChatProgressStatus,
  ChatTraceDeltaEvent,
} from '@/types/api';

export interface ChatProgressStageConfig {
  stage: ChatProgressStage;
  title: string;
}

export interface ChatProgressRow extends ChatProgressStageConfig {
  status: Exclude<ChatProgressStatus, 'failed'>;
}

export const CHAT_PROGRESS_STAGES: ChatProgressStageConfig[] = [
  { stage: 'understanding', title: '正在理解你的问题' },
  { stage: 'planning', title: '正在规划资料检索方式' },
  { stage: 'retrieving', title: '正在检索相关资料' },
  { stage: 'filtering', title: '正在筛选可用依据' },
  { stage: 'answering', title: '正在整理回答内容' },
];

const STAGE_TITLE_BY_KEY = CHAT_PROGRESS_STAGES.reduce<Record<ChatProgressStage, string>>(
  (result, item) => ({ ...result, [item.stage]: item.title }),
  {} as Record<ChatProgressStage, string>,
);

const STAGE_INDEX = CHAT_PROGRESS_STAGES.reduce<Record<ChatProgressStage, number>>(
  (result, item, index) => ({ ...result, [item.stage]: index }),
  {} as Record<ChatProgressStage, number>,
);

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
    return '资料检索遇到问题，正在尝试继续处理';
  }
  if (stage === 'retrieving' && RETRIEVAL_EMPTY_PATTERNS.some((pattern) => sourceText.includes(pattern))) {
    return '未找到足够的相关资料';
  }
  return STAGE_TITLE_BY_KEY[stage];
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
      title: STAGE_TITLE_BY_KEY.answering,
      status: 'success',
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
  const byStage = new Map<ChatProgressStage, ChatProgressEvent>();
  for (const event of events) {
    if (!isProgressStage(event.stage)) continue;
    byStage.set(event.stage, sanitizeProgressEvent(event));
  }
  return CHAT_PROGRESS_STAGES.map((item) => byStage.get(item.stage)).filter(Boolean) as ChatProgressEvent[];
}

export function buildProgressRows(events: ChatProgressEvent[], streaming = false): ChatProgressRow[] {
  const normalized = normalizeProgressEvents(events);
  const eventByStage = new Map(normalized.map((item) => [item.stage, item]));
  let activeIndex = -1;
  for (const event of normalized) {
    activeIndex = Math.max(activeIndex, STAGE_INDEX[event.stage]);
  }
  if (activeIndex < 0 && streaming) activeIndex = 0;

  return CHAT_PROGRESS_STAGES.map((config, index) => {
    const event = eventByStage.get(config.stage);
    if (event) {
      return {
        ...config,
        title: event.title,
        status: toVisibleStatus(event.status),
      };
    }
    if (activeIndex >= 0 && index < activeIndex) {
      return { ...config, status: 'success' };
    }
    if (streaming && index === activeIndex) {
      return { ...config, status: 'running' };
    }
    return { ...config, status: 'pending' };
  });
}

export function markProgressComplete(events: ChatProgressEvent[]): ChatProgressEvent[] {
  const byStage = new Map(normalizeProgressEvents(events).map((item) => [item.stage, item]));
  const latestIndex = Math.max(...Array.from(byStage.keys()).map((stage) => STAGE_INDEX[stage]), -1);
  if (latestIndex < 0) return [];
  return CHAT_PROGRESS_STAGES.slice(0, latestIndex + 1).map((item) => ({
    visible: true,
    stage: item.stage,
    title: STAGE_TITLE_BY_KEY[item.stage],
    status: 'success',
    sequence: byStage.get(item.stage)?.sequence ?? null,
  }));
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
    sequence: event.sequence ?? null,
  };
}

function toVisibleStatus(status: ChatProgressStatus): Exclude<ChatProgressStatus, 'failed'> {
  if (status === 'success') return 'success';
  if (status === 'pending') return 'pending';
  return 'running';
}
