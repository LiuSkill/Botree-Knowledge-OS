/**
 * Model Configs API Client
 *
 * 负责：
 * 1. 模型配置列表
 * 2. 新增模型配置
 * 3. 默认模型设置
 */

import { request } from '@/api/request';
import type { ListQueryParams, ModelConfig, PageResult } from '@/types/api';

export interface ModelConfigListParams extends ListQueryParams {
  keyword?: string;
  model_type?: string;
  enabled?: boolean;
  is_default?: boolean;
}

export function listModelConfigs(params?: ModelConfigListParams): Promise<PageResult<ModelConfig>> {
  return request.get('/model-configs', { params }) as Promise<PageResult<ModelConfig>>;
}

export function createModelConfig(payload: Record<string, unknown>): Promise<ModelConfig> {
  return request.post('/model-configs', payload) as Promise<ModelConfig>;
}

export function updateModelConfig(id: number, payload: Record<string, unknown>): Promise<ModelConfig> {
  return request.put(`/model-configs/${id}`, payload) as Promise<ModelConfig>;
}

export function deleteModelConfig(id: number): Promise<{ deleted: boolean }> {
  return request.delete(`/model-configs/${id}`) as Promise<{ deleted: boolean }>;
}

export function testModelConfig(id: number): Promise<Record<string, unknown>> {
  return request.post(`/model-configs/${id}/test`) as Promise<Record<string, unknown>>;
}

export function setDefaultModelConfig(id: number): Promise<ModelConfig> {
  return request.post(`/model-configs/${id}/set-default`) as Promise<ModelConfig>;
}
