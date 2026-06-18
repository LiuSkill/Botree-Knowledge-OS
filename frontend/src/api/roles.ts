/**
 * Roles API Client
 *
 * 负责：
 * 1. 角色列表
 * 2. 权限矩阵
 * 3. 角色维护
 */

import { request } from '@/api/request';
import type { ListQueryParams, PageResult, PermissionInfo, RoleInfo } from '@/types/api';

export interface RoleListParams extends ListQueryParams {
  keyword?: string;
  enabled?: boolean;
}

export function listRoles(params?: RoleListParams): Promise<PageResult<RoleInfo>> {
  return request.get('/roles', { params }) as Promise<PageResult<RoleInfo>>;
}

export function createRole(payload: Record<string, unknown>): Promise<RoleInfo> {
  return request.post('/roles', payload) as Promise<RoleInfo>;
}

export function updateRole(id: number, payload: Record<string, unknown>): Promise<RoleInfo> {
  return request.put(`/roles/${id}`, payload) as Promise<RoleInfo>;
}

export function deleteRole(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/roles/${id}`) as Promise<{ deleted: boolean }>;
}

export function getPermissionMatrix(): Promise<{ roles: RoleInfo[]; permissions: PermissionInfo[] }> {
  return request.get('/roles/permissions/matrix') as Promise<{ roles: RoleInfo[]; permissions: PermissionInfo[] }>;
}
