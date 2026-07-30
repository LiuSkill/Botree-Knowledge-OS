import { i18n } from '@/locales';

const REVIEW_STATUS_KEY: Record<string, string> = {
  draft: 'status.review.draft',
  submitted: 'status.review.submitted',
  reviewing: 'status.review.reviewing',
  approved: 'status.review.approved',
  rejected: 'status.review.rejected',
  archived: 'status.review.archived',
};

export const REVIEW_TASK_STATUS = {
  reviewing: 'reviewing',
  approved: 'approved',
  rejected: 'rejected',
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
  failed: 'status.failed',
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

export function reviewStatusText(status: string | null | undefined): string {
  return translateByKeyMap(REVIEW_STATUS_KEY, status);
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

export function indexStatusOptions(): Array<{ value: string; label: string }> {
  return Object.keys(INDEX_STATUS_KEY).map((value) => ({ value, label: indexStatusText(value) }));
}

export function parseStatusOptions(): Array<{ value: string; label: string }> {
  return Object.keys(PARSE_STATUS_KEY).map((value) => ({ value, label: parseStatusText(value) }));
}
