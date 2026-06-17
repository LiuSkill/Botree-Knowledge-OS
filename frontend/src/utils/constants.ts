/**
 * Frontend Constants
 *
 * 负责：
 * 1. 维护状态文案
 * 2. 避免页面中出现魔法字符串
 * 3. 与后端枚举字段保持一致
 */

export const REVIEW_STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  submitted: '已提交',
  reviewing: '审核中',
  approved: '已通过',
  rejected: '已驳回',
  archived: '已归档',
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

export const INDEX_STATUS_TEXT: Record<string, string> = {
  not_indexed: '未索引',
  parsing: '解析中',
  parsed_pending_review: '待质检',
  parsed: '已解析',
  indexing: '索引构建中',
  indexed: '已索引',
  failed: '失败',
};

export const INDEX_TASK_STATUS_TEXT: Record<string, string> = {
  pending: '排队中',
  running: '执行中',
  success: '已完成',
  failed: '失败',
  canceled: '已取消',
};

export const MODE_OPTIONS = [
  { label: '自动判断', value: 'auto' },
  { label: '仅基础知识', value: 'base_only' },
  { label: '仅项目知识', value: 'project_only' },
  { label: '联合分析', value: 'hybrid' },
];
