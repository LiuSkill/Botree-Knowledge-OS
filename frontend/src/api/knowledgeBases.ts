/**
 * Knowledge Bases API Client
 *
 * 负责：
 * 1. 知识库 CRUD
 * 2. 知识库文档查询
 * 3. 文件上传
 */

import { request } from '@/api/request';
import type { DocumentInfo, KnowledgeBaseInfo } from '@/types/api';

export interface KnowledgeBasePayload {
  name: string;
  code: string;
  type: 'base' | 'project';
  project_id?: number | null;
  description?: string;
  visibility?: string;
  enabled?: boolean;
}

export function listKnowledgeBases(params?: { type?: string; project_id?: number }): Promise<KnowledgeBaseInfo[]> {
  return request.get('/knowledge-bases', { params }) as Promise<KnowledgeBaseInfo[]>;
}

export function createKnowledgeBase(payload: KnowledgeBasePayload): Promise<KnowledgeBaseInfo> {
  return request.post('/knowledge-bases', payload) as Promise<KnowledgeBaseInfo>;
}

export function getKnowledgeBase(id: number): Promise<KnowledgeBaseInfo> {
  return request.get(`/knowledge-bases/${id}`) as Promise<KnowledgeBaseInfo>;
}

export function listKnowledgeBaseDocuments(id: number, params?: { category_id?: number | null }): Promise<DocumentInfo[]> {
  return request.get(`/knowledge-bases/${id}/documents`, { params }) as Promise<DocumentInfo[]>;
}

export function uploadKnowledgeDocument(id: number, file: File, categoryId: number): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('category_id', String(categoryId));
  return request.post(`/knowledge-bases/${id}/documents/upload`, formData) as Promise<DocumentInfo>;
}

export function getAuthorizationSummary(): Promise<Record<string, unknown>> {
  return request.get('/knowledge-bases/authorization-summary') as Promise<Record<string, unknown>>;
}
