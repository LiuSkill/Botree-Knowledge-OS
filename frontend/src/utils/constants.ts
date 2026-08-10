import { i18n } from '@/locales';

const REVIEW_STATUS_KEY: Record<string, string> = {
  draft: 'status.review.draft',
  submitted: 'status.review.reviewing',
  reviewing: 'status.review.reviewing',
  approved: 'status.review.approved',
  rejected: 'status.review.rejected',
  archived: 'status.review.archived',
};

export const PROJECT_DOCUMENT_STATUS_PENDING = '待审核';
export const PROJECT_DOCUMENT_STATUS_REVIEWING = '审核中';
export const PROJECT_DOCUMENT_STATUS_REJECTED = '已驳回';
export const PROJECT_DOCUMENT_STATUS_PUBLISHED = '已发布';
export const PROJECT_DOCUMENT_STATUS_VALUES = [
  PROJECT_DOCUMENT_STATUS_PENDING,
  PROJECT_DOCUMENT_STATUS_REVIEWING,
  PROJECT_DOCUMENT_STATUS_REJECTED,
  PROJECT_DOCUMENT_STATUS_PUBLISHED,
];

const PROJECT_DOCUMENT_STATUS_KEY: Record<string, string> = {
  [PROJECT_DOCUMENT_STATUS_PENDING]: 'project.detail.document.statusPendingReview',
  [PROJECT_DOCUMENT_STATUS_REVIEWING]: 'status.review.reviewing',
  [PROJECT_DOCUMENT_STATUS_REJECTED]: 'status.review.rejected',
  [PROJECT_DOCUMENT_STATUS_PUBLISHED]: 'project.detail.document.statusPublished',
  pending: 'project.detail.document.statusPendingReview',
  pending_review: 'project.detail.document.statusPendingReview',
  draft: 'project.detail.document.statusPendingReview',
  submitted: 'status.review.reviewing',
  reviewing: 'status.review.reviewing',
  rejected: 'status.review.rejected',
  active: 'project.detail.document.statusPublished',
  approved: 'project.detail.document.statusPublished',
  published: 'project.detail.document.statusPublished',
  reviewed: 'project.detail.document.statusPublished',
};

const PROJECT_DOCUMENT_PUBLISHED_STATUSES = new Set(['active', 'approved', 'published', 'reviewed', PROJECT_DOCUMENT_STATUS_PUBLISHED]);
const PROJECT_DOCUMENT_REJECTED_STATUSES = new Set(['rejected', PROJECT_DOCUMENT_STATUS_REJECTED]);
const PROJECT_DOCUMENT_REVIEWING_STATUSES = new Set(['reviewing', PROJECT_DOCUMENT_STATUS_REVIEWING]);
const PROJECT_DOCUMENT_SUBMITTED_STATUSES = new Set(['submitted']);
const PROJECT_DOCUMENT_PENDING_STATUSES = new Set([
  'pending',
  'pending_review',
  'draft',
  'submitted',
  PROJECT_DOCUMENT_STATUS_PENDING,
]);

export const REVIEW_TASK_STATUS = {
  reviewing: 'reviewing',
  rejected: 'rejected',
  approved: 'approved',
} as const;

export function isReviewTaskPending(status: string | null | undefined): boolean {
  /**
   * 判断审核任务是否仍处于可处理状态。
   */
  return status === REVIEW_TASK_STATUS.reviewing;
}

const INDEX_STATUS_KEY: Record<string, string> = {
  not_indexed: 'status.notIndexed',
  parsing: 'status.parsing',
  parsed_pending_review: 'status.parsedPendingReview',
  parsed: 'status.parsed',
  indexing: 'status.indexing',
  indexed: 'status.indexed',
  failed: 'status.indexFailed',
  invalid: 'status.invalid',
};

const PARSE_STATUS_KEY: Record<string, string> = {
  unparsed: 'status.unparsed',
  parsing: 'status.parsing',
  success: 'status.parseSuccess',
  failed: 'status.parseFailed',
};

const INDEX_TASK_STATUS_KEY: Record<string, string> = {
  pending: 'status.queued',
  running: 'status.running',
  success: 'status.completed',
  failed: 'status.failed',
  canceled: 'status.canceled',
};

export const PARSE_STATUS_OPTION_VALUES = ['parsing', 'failed', 'success'];
export const INDEX_STATUS_OPTION_VALUES = ['not_indexed', 'failed', 'indexed'];

const INDEX_TASK_TYPE_KEY: Record<string, string> = {
  mineru_parse: 'status.indexTaskType.mineruParse',
  pageindex_build: 'status.indexTaskType.pageIndexBuild',
  milvus_build: 'status.indexTaskType.milvusBuild',
  ripgrep_build: 'status.indexTaskType.ripgrepBuild',
  graphrag_build: 'status.indexTaskType.graphRagBuild',
  index_publish: 'status.indexTaskType.indexPublish',
  full_build: 'status.indexTaskType.fullBuild',
};

function translateByKeyMap(map: Record<string, string>, value: string | null | undefined): string {
  const normalized = value || '';
  const key = map[normalized];
  return key ? i18n.global.t(key) : normalized;
}

function orderedStatusValues(values: string[] | undefined, fallbackOrder: string[]): string[] {
  if (values === undefined) return fallbackOrder;
  const valueSet = new Set(values.filter(Boolean));
  return fallbackOrder.filter((value) => valueSet.has(value));
}

export function reviewStatusText(status: string | null | undefined): string {
  return translateByKeyMap(REVIEW_STATUS_KEY, status);
}

export function reviewTaskStatusOptions(statusValues?: string[]): Array<{ value: string; label: string }> {
  return orderedStatusValues(statusValues, Object.values(REVIEW_TASK_STATUS)).map((value) => ({ value, label: reviewStatusText(value) }));
}

export function projectDocumentStatusText(status: string | null | undefined): string {
  return translateByKeyMap(PROJECT_DOCUMENT_STATUS_KEY, status);
}

export function projectDocumentStatusValue(status: string | null | undefined): string {
  const normalized = status || '';
  if (PROJECT_DOCUMENT_PUBLISHED_STATUSES.has(normalized)) return PROJECT_DOCUMENT_STATUS_PUBLISHED;
  if (PROJECT_DOCUMENT_REJECTED_STATUSES.has(normalized)) return PROJECT_DOCUMENT_STATUS_REJECTED;
  if (PROJECT_DOCUMENT_SUBMITTED_STATUSES.has(normalized)) return PROJECT_DOCUMENT_STATUS_REVIEWING;
  if (PROJECT_DOCUMENT_REVIEWING_STATUSES.has(normalized)) return PROJECT_DOCUMENT_STATUS_REVIEWING;
  if (PROJECT_DOCUMENT_PENDING_STATUSES.has(normalized)) return PROJECT_DOCUMENT_STATUS_PENDING;
  return normalized;
}

export function projectDocumentStatusTheme(status: string | null | undefined): 'success' | 'warning' | 'danger' | 'default' {
  const normalized = status || '';
  if (PROJECT_DOCUMENT_PUBLISHED_STATUSES.has(normalized)) return 'success';
  if (PROJECT_DOCUMENT_REJECTED_STATUSES.has(normalized)) return 'danger';
  if (PROJECT_DOCUMENT_SUBMITTED_STATUSES.has(normalized)) return 'warning';
  if (PROJECT_DOCUMENT_PENDING_STATUSES.has(normalized)) return 'warning';
  if (PROJECT_DOCUMENT_REVIEWING_STATUSES.has(normalized)) return 'warning';
  return 'default';
}

export function indexStatusText(status: string | null | undefined): string {
  return translateByKeyMap(INDEX_STATUS_KEY, status);
}

export function parseStatusText(status: string | null | undefined): string {
  return translateByKeyMap(PARSE_STATUS_KEY, status);
}

export function indexTaskStatusText(status: string | null | undefined): string {
  return translateByKeyMap(INDEX_TASK_STATUS_KEY, status);
}

export function indexTaskTypeText(taskType: string | null | undefined): string {
  return translateByKeyMap(INDEX_TASK_TYPE_KEY, taskType);
}

export function indexStatusOptions(statusValues?: string[]): Array<{ value: string; label: string }> {
  return orderedStatusValues(statusValues, INDEX_STATUS_OPTION_VALUES).map((value) => ({ value, label: indexStatusText(value) }));
}

export function projectDocumentStatusOptions(statusValues?: string[]): Array<{ value: string; label: string }> {
  return orderedStatusValues(statusValues, PROJECT_DOCUMENT_STATUS_VALUES).map((value) => ({ value, label: projectDocumentStatusText(value) }));
}

export function parseStatusOptions(statusValues?: string[]): Array<{ value: string; label: string }> {
  return orderedStatusValues(statusValues, PARSE_STATUS_OPTION_VALUES).map((value) => ({ value, label: parseStatusText(value) }));
}
