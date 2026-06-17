/**
 * Axios Request Client
 *
 * 负责：
 * 1. 创建统一 API 客户端
 * 2. 自动携带 JWT Token
 * 3. 处理后端统一响应与 401 跳转
 * 4. 为写操作提供全局遮罩，避免重复点击
 */

import axios from 'axios';
import type { InternalAxiosRequestConfig } from 'axios';
import { MessagePlugin } from 'tdesign-vue-next';

import { beginActionMask, endActionMask } from '@/stores/actionMask';
import type { ApiResponse } from '@/types/api';
import { clearToken, getToken } from '@/utils/auth';

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL || '/api';

interface ActionMaskRequestConfig extends InternalAxiosRequestConfig {
  __actionMaskToken?: symbol;
  actionMaskText?: string;
  skipActionMask?: boolean;
}

function shouldShowActionMask(config: ActionMaskRequestConfig): boolean {
  const method = (config.method || 'get').toLowerCase();
  return method !== 'get' && !config.skipActionMask;
}

export const request = axios.create({
  baseURL: apiBaseUrl,
  timeout: 30000,
});

request.interceptors.request.use((config) => {
  const requestConfig = config as ActionMaskRequestConfig;
  const token = getToken();
  if (token) {
    requestConfig.headers.Authorization = `Bearer ${token}`;
  }
  if (shouldShowActionMask(requestConfig)) {
    requestConfig.__actionMaskToken = beginActionMask(requestConfig.actionMaskText);
  }
  return requestConfig;
});

request.interceptors.response.use(
  (response): any => {
    endActionMask((response.config as ActionMaskRequestConfig).__actionMaskToken);
    if (response.config.responseType === 'blob') {
      return response.data;
    }
    const payload = response.data as ApiResponse<unknown>;
    if (payload.code !== 0) {
      MessagePlugin.error(payload.message || '请求失败');
      return Promise.reject(new Error(payload.message || '请求失败'));
    }
    return payload.data;
  },
  (error) => {
    endActionMask((error.config as ActionMaskRequestConfig | undefined)?.__actionMaskToken);
    const status = error.response?.status;
    if (status === 401) {
      clearToken();
      window.location.href = '/login';
    } else {
      MessagePlugin.error(error.response?.data?.message || error.message || '网络请求失败');
    }
    return Promise.reject(error);
  },
);
