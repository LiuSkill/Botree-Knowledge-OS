/**
 * Documents API Client
 *
 * 负责：
 * 1. 文档列表、详情和 Chunk 查询
 * 2. 提交审核、解析、索引、归档
 * 3. 版本列表
 */

import { request } from '@/api/request';
import type {
  DocumentChunk,
  DocumentDeleteResult,
  DocumentIndexSummary,
  DocumentInfo,
  DocumentPreview,
  DocumentVersionInfo,
  IndexTaskInfo,
  SecurityLevel,
} from '@/types/api';

export function listDocuments(params?: {
  project_id?: number;
  review_status?: string;
  category_id?: number | null;
  index_status?: string;
  knowledge_type?: 'base' | 'project';
  keyword?: string;
}): Promise<DocumentInfo[]> {
  return request.get('/documents', { params }) as Promise<DocumentInfo[]>;
}

export function getDocument(id: number): Promise<DocumentInfo> {
  return request.get(`/documents/${id}`) as Promise<DocumentInfo>;
}

export function deleteDocument(id: number): Promise<DocumentDeleteResult> {
  return request.delete(`/documents/${id}`) as Promise<DocumentDeleteResult>;
}

export function updateDocumentSecurityLevel(id: number, securityLevel: SecurityLevel): Promise<DocumentInfo> {
  return request.put(`/documents/${id}/security-level`, { security_level: securityLevel }) as Promise<DocumentInfo>;
}

export function publishDocument(id: number): Promise<DocumentInfo> {
  return request.post(`/documents/${id}/publish`) as Promise<DocumentInfo>;
}

export function listDocumentChunks(id: number, versionNo?: number | null): Promise<DocumentChunk[]> {
  return request.get(`/documents/${id}/chunks`, { params: versionNo ? { version_no: versionNo } : undefined }) as Promise<DocumentChunk[]>;
}

export function getDocumentPreview(id: number, versionNo?: number | null): Promise<DocumentPreview> {
  return request.get(`/documents/${id}/preview`, { params: versionNo ? { version_no: versionNo } : undefined }) as Promise<DocumentPreview>;
}

export function downloadDocumentPdfPreview(id: number, versionNo?: number | null): Promise<Blob> {
  return request.get(`/documents/${id}/preview-pdf`, {
    params: versionNo ? { version_no: versionNo } : undefined,
    responseType: 'blob',
    timeout: 120000,
  }) as Promise<Blob>;
}

export function submitDocumentReview(
  id: number,
  comment = '提交审核',
  versionNo?: number | null,
): Promise<{ review_task_id: number; review_status: string; version_id?: number | null; version_no?: number | null }> {
  return request.post(
    `/documents/${id}/submit-review`,
    { comment },
    { params: versionNo ? { version_no: versionNo } : undefined },
  ) as Promise<{ review_task_id: number; review_status: string; version_id?: number | null; version_no?: number | null }>;
}

export function parseDocument(id: number, versionNo?: number | null): Promise<Record<string, unknown>> {
  return request.post(`/documents/${id}/parse`, undefined, { params: versionNo ? { version_no: versionNo } : undefined }) as Promise<Record<string, unknown>>;
}

export function indexDocument(id: number): Promise<Record<string, unknown>> {
  return request.post(`/documents/${id}/index`) as Promise<Record<string, unknown>>;
}

export function buildDocumentIndex(id: number, versionNo?: number | null): Promise<Record<string, unknown>> {
  return request.post(`/documents/${id}/build-index`, undefined, { params: versionNo ? { version_no: versionNo } : undefined }) as Promise<Record<string, unknown>>;
}

export function createDocumentIndexBuildTask(id: number, versionNo?: number | null): Promise<IndexTaskInfo> {
  return request.post(`/documents/${id}/indexes/build`, undefined, { params: versionNo ? { version_no: versionNo } : undefined }) as Promise<IndexTaskInfo>;
}

export function listDocumentIndexTasks(id: number): Promise<IndexTaskInfo[]> {
  return request.get(`/documents/${id}/index-tasks`) as Promise<IndexTaskInfo[]>;
}

export function getDocumentIndexSummary(id: number): Promise<DocumentIndexSummary> {
  return request.get(`/documents/${id}/indexes`) as Promise<DocumentIndexSummary>;
}

export function createDocumentVersion(
  id: number,
  file: File,
  payload?: { category_id?: number | null; change_summary?: string | null },
): Promise<DocumentVersionInfo> {
  const formData = new FormData();
  formData.append('file', file);
  if (payload?.category_id) formData.append('category_id', String(payload.category_id));
  if (payload?.change_summary) formData.append('change_summary', payload.change_summary);
  return request.post(`/documents/${id}/versions`, formData, { timeout: 120000 }) as Promise<DocumentVersionInfo>;
}

export function listDocumentVersions(id: number): Promise<DocumentVersionInfo[]> {
  return request.get(`/documents/${id}/versions`) as Promise<DocumentVersionInfo[]>;
}

export function setDocumentCurrentVersion(id: number, versionId: number): Promise<DocumentInfo> {
  return request.post(`/documents/${id}/versions/${versionId}/set-current`) as Promise<DocumentInfo>;
}

export function downloadDocumentVersion(id: number, versionNo: number): Promise<Blob> {
  return request.get(`/documents/${id}/versions/${versionNo}/download`, { responseType: 'blob' }) as Promise<Blob>;
}

export function downloadDocumentAsset(assetId: number): Promise<Blob> {
  return request.get(`/documents/assets/${assetId}`, { responseType: 'blob' }) as Promise<Blob>;
}

export function archiveDocument(id: number): Promise<DocumentInfo> {
  return request.post(`/documents/${id}/archive`, { comment: '归档资料' }) as Promise<DocumentInfo>;
}
