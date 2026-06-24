<!--
  AgentTracePanel

  负责：
  1. 展示 Agent 执行过程
  2. 帮助用户理解检索、规划和回答生成路径
  3. 支持流式场景下的阶段性回显
-->
<script setup lang="ts">
import { computed } from 'vue';

import type { AgentTraceStep } from '@/types/api';
import { visibleTraceSteps } from '@/utils/agentTrace';

const props = defineProps<{
  steps: AgentTraceStep[];
}>();

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
  routeItems: TraceRouteItem[];
  routeReason: string;
  summary: TraceSummaryView;
}

const TASK_LABELS: Record<string, string> = {
  answer: '回答生成',
  answer_llm: '回答模型',
  evidence_judge: '证据判断',
  evidence_judge_fast: '快速证据判断',
  intent: '用户意图识别',
  llm: '通用文本模型',
  planner: '检索规划',
  query_decompose: '任务拆解',
  visual_reading: '图像资料理解',
  vision_llm: '视觉模型',
};

const SOURCE_LABELS: Record<string, string> = {
  database: '数据库配置',
  env_fallback: '环境变量兜底',
  explicit: '指定配置',
  not_called: '未调用模型',
  rules: '规则判断',
  rules_fast_path: '规则快速路径',
  rules_fallback: '规则回退',
  unknown: '未知来源',
};

const RETRIEVER_LABELS: Record<string, string> = {
  graph: '图谱检索',
  graphrag: '图谱检索',
  keyword: '关键词检索',
  milvus: '语义检索',
  page_index: '页级检索',
  project_metadata: '项目主数据',
  ripgrep: '精确检索',
};

const PROFILE_LABELS: Record<string, string> = {
  comparison: '对比问答',
  comparison_table: '对比表格',
  direct_answer: '直接回答',
  direct_value: '精确答案',
  exact_lookup: '精确定位问答',
  general: '常规回答',
  general_qa: '通用问答',
  graph_reasoning: '图谱推理问答',
  industry_explanation: '行业知识回答',
  industry_knowledge_qa: '行业基础知识问答',
  knowledge_qa: '知识问答',
  page_location: '页级定位问答',
  process_flow: '流程问答',
  process_steps: '流程步骤',
  project_overview: '项目概览问答',
  project_qa: '项目资料问答',
  project_summary: '项目概览',
  pure_general_qa: '纯通用问答',
  source_location: '来源定位',
  unknown: '未知类型',
};

const PROVIDER_LABELS: Record<string, string> = {
  dashscope: '阿里云百炼',
  env_fallback: '环境变量兜底',
  local: '本地模型',
  openai: 'OpenAI',
  openai_compatible: '兼容 OpenAI 接口',
  qwen: '通义千问',
  qwen_api: '通义千问接口',
};

const QWEN_MODEL_TOKEN_LABELS: Record<string, string> = {
  chat: '对话模型',
  coder: '代码模型',
  embedding: '向量模型',
  flash: '极速版',
  instruct: '指令模型',
  max: '旗舰版',
  plus: '增强版',
  turbo: '高速版',
  vl: '视觉版',
};

const PAIR_LABELS = new Set(['选择', '跳过', '补充', '关联', '依据']);

const traceItems = computed<TraceViewItem[]>(() =>
  visibleTraceSteps(props.steps).map((step, index) => ({
    key: traceStepKey(step, index),
    index,
    step,
    routeItems: modelRouteItems(step),
    routeReason: modelRouteReason(step),
    summary: buildSummaryView(step),
  })),
);

function stepSummary(step: AgentTraceStep): string {
  if (step.display_text) return step.display_text;
  if (step.result) return step.result;
  if (step.output_summary && Object.keys(step.output_summary).length) {
    return JSON.stringify(step.output_summary, null, 2);
  }
  if (step.details && Object.keys(step.details).length) {
    const { model_route: _modelRoute, ...visibleDetails } = step.details;
    if (Object.keys(visibleDetails).length) {
      return JSON.stringify(visibleDetails, null, 2);
    }
  }
  return '已执行';
}

function traceStepKey(step: AgentTraceStep, index: number): string {
  return `${step.sequence ?? index}-${step.step}-${step.elapsed_ms ?? 'pending'}`;
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
  if (status === 'running') return '进行中';
  if (status === 'failed') return '失败';
  return '完成';
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

function textValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (Array.isArray(value)) return value.map((item) => textValue(item)).filter(Boolean).join('、');
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value).trim();
}

function escapeRegExp(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

function localizeKnownCodes(text: string): string {
  const labels = { ...PROFILE_LABELS, ...PROVIDER_LABELS };
  return Object.entries(labels)
    .sort(([left], [right]) => right.length - left.length)
    .reduce((result, [code, label]) => {
      const pattern = new RegExp(`(^|[^A-Za-z0-9_])${escapeRegExp(code)}(?=$|[^A-Za-z0-9_])`, 'g');
      return result.replace(pattern, `$1${label}`);
    }, text);
}

function providerText(value: unknown): string {
  const text = textValue(value);
  return PROVIDER_LABELS[text.toLowerCase()] || localizeKnownCodes(text);
}

function modelNameText(value: unknown): string {
  const text = textValue(value);
  const normalized = text.toLowerCase();
  if (!normalized.startsWith('qwen')) return localizeKnownCodes(text);

  const tokens = normalized
    .replace(/^qwen[-/]?/, '')
    .split('-')
    .map((item) => item.trim())
    .filter(Boolean);
  if (!tokens.length) return '通义千问';

  const suffix = tokens.map((token) => QWEN_MODEL_TOKEN_LABELS[token] || token.toUpperCase()).join(' ');
  return `通义千问 ${suffix}`;
}

function modelRoute(step: AgentTraceStep): Record<string, unknown> | null {
  const route = asRecord(step.details?.model_route);
  if (!route) return null;
  const hasMeaningfulValue = Object.entries(route).some(([key, value]) => {
    const text = textValue(value);
    return text && !(key === 'source' && text === 'unknown');
  });
  if (hasMeaningfulValue) {
    return route;
  }
  return null;
}

function translateCode(value: unknown, labels: Record<string, string>): string {
  const text = String(value || '');
  return labels[text] || text;
}

function modelRouteItems(step: AgentTraceStep): TraceRouteItem[] {
  const route = modelRoute(step);
  if (!route) return [];
  const items: TraceRouteItem[] = [];
  const source = textValue(route.source);
  const sourceIsInternalRule = ['rules', 'rules_fast_path', 'not_called'].includes(source);
  if (source && source !== 'unknown' && !sourceIsInternalRule) {
    items.push({ label: '方式', value: translateCode(source, SOURCE_LABELS) });
  }
  if (route.model_type) {
    items.push({ label: '类型', value: translateCode(route.model_type, TASK_LABELS) });
  }
  if (route.provider) {
    items.push({ label: '服务', value: providerText(route.provider) });
  }
  if (route.model_name) {
    items.push({ label: '模型', value: modelNameText(route.model_name) });
  }
  if (!items.length && route.task) {
    items.push({ label: '任务', value: translateCode(route.task, TASK_LABELS) });
  }
  return items;
}

function modelRouteReason(step: AgentTraceStep): string {
  const route = modelRoute(step);
  if (!route) return '';
  const source = textValue(route.source);
  if (['rules', 'rules_fast_path', 'not_called'].includes(source)) return '';
  const reason = textValue(route.reason);
  if (!reason || shouldShowRetrieverMetrics(step)) return reason;
  const cleanedReason = reason.replace(/[，,；;]?\s*(evidence|hits|images|tables)\s*=\s*[\w.-]+/gi, '').trim();
  return localizeKnownCodes(cleanedReason);
}

function splitSummaryLines(text: string): string[] {
  return text.split(/\r?\n/).map((item) => item.trim()).filter(Boolean);
}

function retrieverLabel(name: string): string {
  const normalized = name.trim();
  return RETRIEVER_LABELS[normalized] || RETRIEVER_LABELS[normalized.toLowerCase()] || normalized;
}

function parseHitLine(line: string): TraceMetric | null {
  const match = line.match(/^(.+?)\s*命中\s*(\d+)\s*条$/);
  if (!match) return null;
  return {
    label: retrieverLabel(match[1]),
    value: match[2],
    suffix: '条',
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
        suffix: '条',
      };
    })
    .filter((item): item is TraceMetric => Boolean(item));
}

function parseDisplayPair(line: string): TracePair | null {
  const match = line.match(/^([^：:]{1,8})[：:]\s*(.+)$/);
  if (!match) return null;
  const label = match[1].trim();
  if (!PAIR_LABELS.has(label)) return null;
  return {
    label,
    value: localizeKnownCodes(match[2].trim()),
  };
}

function querySummaryView(text: string): TraceSummaryView | null {
  const match = text.match(/^生成\s*(\d+)\s*个检索问题[：:]\s*([\s\S]+)$/);
  if (!match) return null;
  const queries = match[2].split(/[；;]\s*/).map((item) => item.trim()).filter(Boolean);
  return {
    lead: `生成 ${match[1]} 个检索问题`,
    lines: [],
    metrics: [],
    pairs: [],
    queries: queries.length ? queries : [match[2].trim()],
  };
}

function fallbackLead(step: AgentTraceStep, metrics: TraceMetric[], pairs: TracePair[]): string {
  if (metrics.length) return '检索命中统计';
  if (pairs.some((item) => item.label === '选择')) return '检索方式已确定';
  if (step.status === 'running') return '正在执行';
  return '已执行';
}

function buildSummaryView(step: AgentTraceStep): TraceSummaryView {
  const text = localizeKnownCodes(stepSummary(step).trim());
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
  const detailLines: string[] = [];

  remainingLines.forEach((line) => {
    const pair = parseDisplayPair(line);
    if (pair) {
      pairs.push(pair);
      return;
    }
    detailLines.push(line);
  });

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
  <t-empty v-if="!traceItems.length" size="small" description="暂无执行过程" />
  <div v-else class="trace-list">
    <article v-for="item in traceItems" :key="item.key" class="trace-card" :class="statusClass(item.step.status)">
      <div class="trace-header">
        <div class="trace-title">
          <span class="trace-index">{{ item.index + 1 }}</span>
          <strong>{{ item.step.step }}</strong>
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
        <p v-if="item.routeReason" class="route-reason">依据：{{ item.routeReason }}</p>
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
