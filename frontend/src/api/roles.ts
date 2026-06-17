/**
 * Roles API Client
 *
 * 负责：
 * 1. 角色列表
 * 2. 权限矩阵
 * 3. 角色维护
 */

import { request } from '@/api/request';
import type { PermissionInfo, RoleInfo } from '@/types/api';

export function listRoles(): Promise<RoleInfo[]> {
  return request.get('/roles') as Promise<RoleInfo[]>;
}

export function createRole(payload: Record<string, unknown>): Promise<RoleInfo> {
  return request.post('/roles', payload) as Promise<RoleInfo>;
}

export function getPermissionMatrix(): Promise<{ roles: RoleInfo[]; permissions: PermissionInfo[] }> {
  return request.get('/roles/permissions/matrix') as Promise<{ roles: RoleInfo[]; permissions: PermissionInfo[] }>;
}
