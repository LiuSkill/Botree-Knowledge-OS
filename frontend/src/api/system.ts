/**
 * System API Client
 *
 * 负责：
 * 1. 首页统计
 * 2. 操作日志
 * 3. 问答审计
 */

import { request } from '@/api/request';
import type { DashboardStats, OperationLog } from '@/types/api';

export function getDashboardStats(): Promise<DashboardStats> {
  return request.get('/system/dashboard') as Promise<DashboardStats>;
}

export function listOperationLogs(): Promise<OperationLog[]> {
  return request.get('/system/operation-logs') as Promise<OperationLog[]>;
}

export function listQAAudits(): Promise<Array<Record<string, unknown>>> {
  return request.get('/system/qa-audits') as Promise<Array<Record<string, unknown>>>;
}
