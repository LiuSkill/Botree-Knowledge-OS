/**
 * Retrieval API Client
 *
 * 负责：
 * 1. 知识检索请求
 * 2. 返回引用来源
 * 3. 供后续知识中心搜索扩展
 */

import { request } from '@/api/request';

export function searchKnowledge(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return request.post('/retrieval/search', payload) as Promise<Record<string, unknown>>;
}
