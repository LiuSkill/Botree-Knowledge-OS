/**
 * Departments API Client
 *
 * 负责：
 * 1. 部门树与列表查询
 * 2. 部门新增、编辑、启停和软删除
 * 3. 部门负责人候选用户查询
 */

import { request } from '@/api/request';
import type { DepartmentInfo, DepartmentStatus, DepartmentUserOption } from '@/types/api';

export interface DepartmentQueryParams {
  keyword?: string;
  status?: DepartmentStatus | '';
  parent_id?: number | null;
}

export interface DepartmentSubmitPayload {
  name: string;
  code: string;
  parent_id?: number | null;
  leader_user_id?: number | null;
  sort_order: number;
  status: DepartmentStatus;
  description?: string | null;
}

export function listDepartmentTree(params?: DepartmentQueryParams): Promise<DepartmentInfo[]> {
  return request.get('/system/departments/tree', { params }) as Promise<DepartmentInfo[]>;
}

export function listDepartments(params?: DepartmentQueryParams): Promise<DepartmentInfo[]> {
  return request.get('/system/departments', { params }) as Promise<DepartmentInfo[]>;
}

export function getDepartment(id: number): Promise<DepartmentInfo> {
  return request.get(`/system/departments/${id}`) as Promise<DepartmentInfo>;
}

export function createDepartment(payload: DepartmentSubmitPayload): Promise<DepartmentInfo> {
  return request.post('/system/departments', payload) as Promise<DepartmentInfo>;
}

export function updateDepartment(id: number, payload: DepartmentSubmitPayload): Promise<DepartmentInfo> {
  return request.put(`/system/departments/${id}`, payload) as Promise<DepartmentInfo>;
}

export function updateDepartmentStatus(id: number, status: DepartmentStatus): Promise<DepartmentInfo> {
  return request.patch(`/system/departments/${id}/status`, { status }) as Promise<DepartmentInfo>;
}

export function deleteDepartment(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/system/departments/${id}`) as Promise<{ deleted: boolean }>;
}

export function listDepartmentUserOptions(): Promise<DepartmentUserOption[]> {
  return request.get('/system/departments/user-options') as Promise<DepartmentUserOption[]>;
}
