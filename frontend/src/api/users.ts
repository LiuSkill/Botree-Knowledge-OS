/**
 * Users API Client
 *
 * 负责：
 * 1. 用户列表
 * 2. 用户新增和编辑
 * 3. 用户禁用
 */

import { request } from '@/api/request';
import type { UserInfo } from '@/types/api';

export function listUsers(): Promise<UserInfo[]> {
  return request.get('/users') as Promise<UserInfo[]>;
}

export function createUser(payload: Record<string, unknown>): Promise<UserInfo> {
  return request.post('/users', payload) as Promise<UserInfo>;
}

export function updateUser(id: number, payload: Record<string, unknown>): Promise<UserInfo> {
  return request.put(`/users/${id}`, payload) as Promise<UserInfo>;
}
