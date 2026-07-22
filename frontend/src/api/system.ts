/**
 * System API Client
 *
 * 负责：
 * 1. 首页统计
 * 2. 操作日志
 * 3. 问答审计
 */

import { request } from '@/api/request';
import type {
  ActionPermissionGroup,
  DashboardStats,
  ListQueryParams,
  OperationLog,
  OperationLogUserOption,
  PageResult,
  QAAuditDetail,
  QAAuditFilters,
  QAAuditSession,
  SystemMenuNode,
} from '@/types/api';

export function getDashboardStats(): Promise<DashboardStats> {
  return request.get('/system/dashboard') as Promise<DashboardStats>;
}

export function getSystemMenus(): Promise<SystemMenuNode[]> {
  return request.get('/system/menus') as Promise<SystemMenuNode[]>;
}

export function getActionPermissions(): Promise<ActionPermissionGroup[]> {
  return request.get('/system/permissions/actions') as Promise<ActionPermissionGroup[]>;
}

export interface OperationLogFilters extends ListQueryParams {
  user_id?: number;
  username?: string;
  keyword?: string;
  result?: string;
  target_type?: string;
  started_at?: string;
  ended_at?: string;
}

export function listOperationLogs(params?: OperationLogFilters): Promise<PageResult<OperationLog>> {
  return request.get('/system/operation-logs', { params }) as Promise<PageResult<OperationLog>>;
}

export function listOperationLogUsers(): Promise<OperationLogUserOption[]> {
  return request.get('/system/operation-log-users') as Promise<OperationLogUserOption[]>;
}

export function listQAAuditSessions(params?: QAAuditFilters): Promise<PageResult<QAAuditSession>> {
  return request.get('/system/qa-audit-sessions', { params }) as Promise<PageResult<QAAuditSession>>;
}

export function listQAAudits(params?: QAAuditFilters): Promise<PageResult<QAAuditDetail>> {
  return request.get('/system/qa-audits', { params }) as Promise<PageResult<QAAuditDetail>>;
}
