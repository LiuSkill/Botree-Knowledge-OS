/**
 * Users API Client
 *
 * 负责：
 * 1. 用户列表
 * 2. 用户新增和编辑
 * 3. 用户禁用
 */

import { request } from '@/api/request';
import type { DepartmentInfo, ListQueryParams, PageResult, UserInfo } from '@/types/api';

export interface UserListParams extends ListQueryParams {
  keyword?: string;
  status?: string;
  role_id?: number;
  department_id?: number;
}

export interface UserAvatarSubmitOptions {
  avatarFile?: File | null;
  clearAvatar?: boolean;
}

function buildUserRequestBody(payload: Record<string, unknown>, options?: UserAvatarSubmitOptions): Record<string, unknown> | FormData {
  if (!options?.avatarFile && !options?.clearAvatar) {
    return payload;
  }
  const formData = new FormData();
  formData.append('payload', JSON.stringify(payload));
  if (options.avatarFile) {
    formData.append('avatar', options.avatarFile);
  }
  if (options.clearAvatar) {
    formData.append('clear_avatar', 'true');
  }
  return formData;
}

export function listUsers(params?: UserListParams): Promise<PageResult<UserInfo>> {
  return request.get('/users', { params }) as Promise<PageResult<UserInfo>>;
}

export function listUserDepartmentTree(): Promise<DepartmentInfo[]> {
  return request.get('/users/departments/tree') as Promise<DepartmentInfo[]>;
}

export function createUser(payload: Record<string, unknown>, options?: UserAvatarSubmitOptions): Promise<UserInfo> {
  return request.post('/users', buildUserRequestBody(payload, options)) as Promise<UserInfo>;
}

export function updateUser(id: number, payload: Record<string, unknown>, options?: UserAvatarSubmitOptions): Promise<UserInfo> {
  return request.put(`/users/${id}`, buildUserRequestBody(payload, options)) as Promise<UserInfo>;
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
