/**
 * Reviews API Client
 *
 * 负责：
 * 1. 审核任务列表
 * 2. 审核通过和驳回
 * 3. 审核日志查询
 */

import { request } from '@/api/request';
import type { DocumentInfo, ReviewTask } from '@/types/api';

export function listReviewTasks(params?: { status?: string }): Promise<ReviewTask[]> {
  return request.get('/review-tasks', { params }) as Promise<ReviewTask[]>;
}

export function getReviewTask(id: number): Promise<ReviewTask> {
  return request.get(`/review-tasks/${id}`) as Promise<ReviewTask>;
}

export function approveReviewTask(id: number, comment = '审核通过'): Promise<ReviewTask> {
  return request.post(`/review-tasks/${id}/approve`, { comment }) as Promise<ReviewTask>;
}

export function rejectReviewTask(id: number, comment = '审核驳回'): Promise<ReviewTask> {
  return request.post(`/review-tasks/${id}/reject`, { comment }) as Promise<ReviewTask>;
}

export function listApprovedDocuments(params?: {
  scope_type?: 'base' | 'project';
  project_id?: number | null;
  category_id?: number | null;
  index_status?: string;
  keyword?: string;
}): Promise<DocumentInfo[]> {
  return request.get('/review-tasks/approved-documents', { params }) as Promise<DocumentInfo[]>;
}
