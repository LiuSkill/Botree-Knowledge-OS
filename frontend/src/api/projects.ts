/**
 * Projects API Client
 *
 * 负责：
 * 1. 项目 CRUD
 * 2. 项目成员管理
 * 3. 项目详情数据获取
 */

import { request } from '@/api/request';
import type { ProjectInfo, SecurityLevel } from '@/types/api';

export interface ProjectPayload {
  name: string;
  code: string;
  description?: string;
  client?: string;
  manager?: string;
  status?: string;
  progress?: number;
  security_level?: SecurityLevel;
}

export function listProjects(params?: { keyword?: string }): Promise<ProjectInfo[]> {
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
