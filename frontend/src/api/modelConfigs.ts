/**
 * Model Configs API Client
 *
 * 负责：
 * 1. 模型配置列表
 * 2. 新增模型配置
 * 3. 默认模型设置
 */

import { request } from '@/api/request';
import type { ModelConfig } from '@/types/api';

export function listModelConfigs(): Promise<ModelConfig[]> {
  return request.get('/model-configs') as Promise<ModelConfig[]>;
}

export function createModelConfig(payload: Record<string, unknown>): Promise<ModelConfig> {
  return request.post('/model-configs', payload) as Promise<ModelConfig>;
}

export function setDefaultModelConfig(id: number): Promise<ModelConfig> {
  return request.post(`/model-configs/${id}/set-default`) as Promise<ModelConfig>;
}
