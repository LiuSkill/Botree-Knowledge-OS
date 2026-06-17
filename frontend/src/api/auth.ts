/**
 * Auth API Client
 *
 * 负责：
 * 1. 登录
 * 2. 获取当前用户
 * 3. 退出登录
 */

import { request } from '@/api/request';
import type { UserInfo } from '@/types/api';

export interface LoginResult {
  access_token: string;
  token_type: string;
  user: UserInfo;
}

export function loginApi(payload: { username: string; password: string }): Promise<LoginResult> {
  return request.post('/auth/login', payload) as Promise<LoginResult>;
}

export function meApi(): Promise<UserInfo> {
  return request.get('/auth/me') as Promise<UserInfo>;
}

export function logoutApi(): Promise<{ logged_out: boolean }> {
  return request.post('/auth/logout') as Promise<{ logged_out: boolean }>;
}
