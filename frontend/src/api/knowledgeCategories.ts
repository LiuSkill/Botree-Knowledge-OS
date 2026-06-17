/**
 * Knowledge Categories API Client
 *
 * 负责：
 * 1. 查询企业和项目隔离的知识分类树
 * 2. 创建、编辑、删除动态分类
 * 3. 为上传弹窗和资料筛选提供分类数据
 */

import { request } from '@/api/request';
import type { KnowledgeCategory } from '@/types/api';

export interface KnowledgeCategoryPayload {
  scope_type: 'base' | 'project';
  project_id?: number | null;
  parent_id?: number | null;
  name: string;
  code: string;
  description?: string | null;
  sort_order?: number;
  enabled?: boolean;
}

export interface KnowledgeCategoryUpdatePayload {
  parent_id?: number | null;
  name?: string;
  code?: string;
  description?: string | null;
  sort_order?: number;
  enabled?: boolean;
}

export function listKnowledgeCategories(params: { scope_type: 'base' | 'project'; project_id?: number | null }): Promise<KnowledgeCategory[]> {
  return request.get('/knowledge-categories', { params }) as Promise<KnowledgeCategory[]>;
}

export function createKnowledgeCategory(payload: KnowledgeCategoryPayload): Promise<{ category_id: number; tree: KnowledgeCategory[] }> {
  return request.post('/knowledge-categories', payload) as Promise<{ category_id: number; tree: KnowledgeCategory[] }>;
}

export function updateKnowledgeCategory(id: number, payload: KnowledgeCategoryUpdatePayload): Promise<{ category_id: number; tree: KnowledgeCategory[] }> {
  return request.put(`/knowledge-categories/${id}`, payload) as Promise<{ category_id: number; tree: KnowledgeCategory[] }>;
}

export function deleteKnowledgeCategory(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/knowledge-categories/${id}`) as Promise<{ deleted: boolean }>;
}
