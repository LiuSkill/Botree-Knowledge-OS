/**
 * Projects API Client
 */

import { request } from '@/api/request';
import type {
  DocumentDeleteResult,
  DocumentInfo,
  DocumentVersionInfo,
  IndexTaskInfo,
  KnowledgeCategory,
  PageResult,
  ProjectInfo,
  ProjectOverviewInfo,
  ProjectStatus,
  SecurityLevel,
} from '@/types/api';

export interface ProjectPayload {
  name?: string;
  code?: string;
  project_name?: string;
  project_code?: string;
  project_short_name?: string;
  project_english_name?: string;
  description?: string;
  client?: string;
  customer_name?: string;
  manager?: string;
  owner_id?: number | null;
  owner_name?: string;
  status?: string;
  project_status?: ProjectStatus | string;
  progress?: number;
  security_level?: SecurityLevel;
  project_type?: string;
  project_stage?: string;
  raw_material_type?: string;
  capacity?: string;
  process_route?: string;
  main_products?: string;
  scope_description?: string;
  deliverables?: string;
  department_id?: number | null;
}

export interface ProjectListParams {
  keyword?: string;
  project_status?: ProjectStatus | string;
  security_level?: SecurityLevel;
}

export interface ProjectDirectoryPayload {
  parent_id?: number | null;
  name: string;
  code: string;
  description?: string | null;
  sort_order?: number;
  enabled?: boolean;
  default_security_level?: SecurityLevel;
}

export interface ProjectDirectoryUpdatePayload {
  parent_id?: number | null;
  name?: string;
  code?: string;
  description?: string | null;
  sort_order?: number;
  enabled?: boolean;
  default_security_level?: SecurityLevel;
}

export function listProjects(params?: ProjectListParams): Promise<ProjectInfo[]> {
  return request.get('/projects', { params }) as Promise<ProjectInfo[]>;
}

export function createProject(payload: ProjectPayload): Promise<ProjectInfo> {
  return request.post('/projects', payload) as Promise<ProjectInfo>;
}

export function getProject(id: number): Promise<ProjectInfo> {
  return request.get(`/projects/${id}`) as Promise<ProjectInfo>;
}

export function updateProject(id: number, payload: Partial<ProjectPayload>): Promise<ProjectInfo> {
  return request.put(`/projects/${id}`, payload) as Promise<ProjectInfo>;
}

export function deleteProject(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/projects/${id}`) as Promise<{ deleted: boolean }>;
}

export function listProjectMembers(id: number): Promise<Array<Record<string, unknown>>> {
  return request.get(`/projects/${id}/members`) as Promise<Array<Record<string, unknown>>>;
}

export function getProjectOverview(id: number): Promise<ProjectOverviewInfo> {
  return request.get(`/projects/${id}/overview`) as Promise<ProjectOverviewInfo>;
}

export function listProjectDirectories(
  projectId: number,
  params?: {
    keyword?: string;
    status?: string;
    security_level?: string;
    parse_status?: string;
    index_status?: string;
  },
): Promise<KnowledgeCategory[]> {
  return request.get(`/projects/${projectId}/directories`, { params }) as Promise<KnowledgeCategory[]>;
}

export function createProjectDirectory(projectId: number, payload: ProjectDirectoryPayload): Promise<{ category_id: number; tree: KnowledgeCategory[] }> {
  return request.post(`/projects/${projectId}/directories`, payload) as Promise<{ category_id: number; tree: KnowledgeCategory[] }>;
}

export function updateProjectDirectory(
  projectId: number,
  directoryId: number,
  payload: ProjectDirectoryUpdatePayload,
): Promise<{ category_id: number; tree: KnowledgeCategory[] }> {
  return request.put(`/projects/${projectId}/directories/${directoryId}`, payload) as Promise<{ category_id: number; tree: KnowledgeCategory[] }>;
}

export function deleteProjectDirectory(projectId: number, directoryId: number): Promise<{ deleted: boolean; project_id: number }> {
  return request.delete(`/projects/${projectId}/directories/${directoryId}`) as Promise<{ deleted: boolean; project_id: number }>;
}

export function initProjectDirectoryTemplate(projectId: number): Promise<{ created: number; skipped: boolean; tree: KnowledgeCategory[] }> {
  return request.post(`/projects/${projectId}/directories/init-template`) as Promise<{ created: number; skipped: boolean; tree: KnowledgeCategory[] }>;
}

export function listProjectDocuments(
  projectId: number,
  params?: {
    keyword?: string;
    directory_id?: number | null;
    category_id?: number | null;
    status?: string;
    security_level?: SecurityLevel;
    parse_status?: string;
    index_status?: string;
    document_type?: string;
    discipline?: string;
    upload_user_id?: number;
  },
): Promise<DocumentInfo[]> {
  return request.get(`/projects/${projectId}/documents`, { params }) as Promise<DocumentInfo[]>;
}

export function listProjectDocumentsPage(
  projectId: number,
  params?: {
    page?: number;
    page_size?: number;
    keyword?: string;
    directory_id?: number | null;
    category_id?: number | null;
    status?: string;
    security_level?: SecurityLevel;
    parse_status?: string;
    index_status?: string;
    document_type?: string;
    discipline?: string;
    upload_user_id?: number;
  },
): Promise<PageResult<DocumentInfo>> {
  return request.get(`/projects/${projectId}/documents/page`, { params }) as Promise<PageResult<DocumentInfo>>;
}

export function uploadProjectDocument(projectId: number, file: File, directoryId: number, securityLevel?: SecurityLevel | null): Promise<DocumentInfo> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('directory_id', String(directoryId));
  if (securityLevel) formData.append('security_level', securityLevel);
  return request.post(`/projects/${projectId}/documents/upload`, formData, { timeout: 120000 }) as Promise<DocumentInfo>;
}

export function updateProjectDocument(projectId: number, documentId: number, payload: Partial<DocumentInfo>): Promise<DocumentInfo> {
  return request.put(`/projects/${projectId}/documents/${documentId}`, payload) as Promise<DocumentInfo>;
}

export function deleteProjectDocument(projectId: number, documentId: number): Promise<DocumentDeleteResult> {
  return request.delete(`/projects/${projectId}/documents/${documentId}`) as Promise<DocumentDeleteResult>;
}

export function publishProjectDocument(projectId: number, documentId: number): Promise<DocumentInfo> {
  return request.post(`/projects/${projectId}/documents/${documentId}/publish`) as Promise<DocumentInfo>;
}

export function retryParseProjectDocument(projectId: number, documentId: number, versionNo?: number | null): Promise<Record<string, unknown>> {
  return request.post(
    `/projects/${projectId}/documents/${documentId}/retry-parse`,
    undefined,
    { params: versionNo ? { version_no: versionNo } : undefined },
  ) as Promise<Record<string, unknown>>;
}

export function retryIndexProjectDocument(projectId: number, documentId: number, versionNo?: number | null): Promise<IndexTaskInfo> {
  return request.post(
    `/projects/${projectId}/documents/${documentId}/retry-index`,
    undefined,
    { params: versionNo ? { version_no: versionNo } : undefined },
  ) as Promise<IndexTaskInfo>;
}

export function updateProjectDocumentSecurityLevel(projectId: number, documentId: number, securityLevel: SecurityLevel): Promise<DocumentInfo> {
  return request.post(`/projects/${projectId}/documents/${documentId}/security-level`, { security_level: securityLevel }) as Promise<DocumentInfo>;
}

export function listProjectDocumentVersions(projectId: number, documentId: number): Promise<DocumentVersionInfo[]> {
  return request.get(`/projects/${projectId}/documents/${documentId}/versions`) as Promise<DocumentVersionInfo[]>;
}

export function createProjectDocumentVersion(
  projectId: number,
  documentId: number,
  file: File,
  payload?: { directory_id?: number | null; category_id?: number | null; change_summary?: string | null; version_note?: string | null },
): Promise<DocumentVersionInfo> {
  const formData = new FormData();
  formData.append('file', file);
  if (payload?.directory_id) formData.append('directory_id', String(payload.directory_id));
  if (payload?.category_id) formData.append('category_id', String(payload.category_id));
  if (payload?.change_summary) formData.append('change_summary', payload.change_summary);
  if (payload?.version_note) formData.append('version_note', payload.version_note);
  return request.post(`/projects/${projectId}/documents/${documentId}/versions`, formData, { timeout: 120000 }) as Promise<DocumentVersionInfo>;
}

export function setProjectDocumentCurrentVersion(projectId: number, documentId: number, versionId: number): Promise<DocumentInfo> {
  return request.post(`/projects/${projectId}/documents/${documentId}/versions/${versionId}/set-current`) as Promise<DocumentInfo>;
}
