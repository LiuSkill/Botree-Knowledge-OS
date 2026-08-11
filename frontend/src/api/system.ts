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

export interface QADebuggerEvent {
  schema_version: number;
  event_id: string;
  trace_id: string;
  node_id: string;
  parent_node_id?: string | null;
  business_stage: string;
  event_type: string;
  sequence: number;
  occurred_at: string;
  producer: string;
  payload: Record<string, unknown> | null;
  payload_available?: boolean;
}

export interface QADebuggerResult {
  trace: Record<string, unknown> & { trace_id: string; status: string; completeness_status: string };
  stages: Array<Record<string, unknown> & { stage: string; event_count: number }>;
  events: QADebuggerEvent[];
  events_offset: number;
  events_limit: number;
  events_total: number;
}

export function getQADebugger(
  traceId: string,
  offset = 0,
  limit = 100,
  includePayload = false,
  businessStage?: string,
): Promise<QADebuggerResult> {
  return request.get(`/system/qa-audits/${encodeURIComponent(traceId)}/debugger`, {
    params: { offset, limit, include_payload: includePayload, business_stage: businessStage },
  }) as Promise<QADebuggerResult>;
}

export function getQADebuggerEvent(traceId: string, eventId: string): Promise<QADebuggerEvent> {
  return request.get(`/system/qa-audits/${encodeURIComponent(traceId)}/debugger/events/${encodeURIComponent(eventId)}`) as Promise<QADebuggerEvent>;
}
