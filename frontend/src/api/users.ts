/**
 * Users API Client
 *
 * 负责：
 * 1. 用户列表
 * 2. 用户新增和编辑
 * 3. 用户禁用
 */

import { request } from '@/api/request';
import type { ListQueryParams, PageResult, UserInfo } from '@/types/api';

export interface UserListParams extends ListQueryParams {
  keyword?: string;
  status?: string;
  role_id?: number;
}

export function listUsers(params?: UserListParams): Promise<PageResult<UserInfo>> {
  return request.get('/users', { params }) as Promise<PageResult<UserInfo>>;
}

export function createUser(payload: Record<string, unknown>): Promise<UserInfo> {
  return request.post('/users', payload) as Promise<UserInfo>;
}

export function updateUser(id: number, payload: Record<string, unknown>): Promise<UserInfo> {
  return request.put(`/users/${id}`, payload) as Promise<UserInfo>;
}

export function deleteUser(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/users/${id}`) as Promise<{ deleted: boolean }>;
}

export function resetUserPassword(id: number): Promise<{ reset: boolean; default_password: string }> {
  return request.post(`/users/${id}/reset-password`) as Promise<{ reset: boolean; default_password: string }>;
}

export function downloadUserAvatar(id: number): Promise<Blob> {
  return request.get(`/users/${id}/avatar`, { responseType: 'blob' }) as Promise<Blob>;
}
