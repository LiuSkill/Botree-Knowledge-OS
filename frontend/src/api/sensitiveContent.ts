import { request } from '@/api/request';

export interface SensitiveType {
  id: number; code: string; name: string; default_mask_text: string; enabled: boolean; updated_at: string;
}
export interface SensitiveRule {
  id: number; code: string; name: string; sensitive_type_code: string; match_type: 'regex' | 'keyword' | 'keyword_window' | 'table_column' | 'table_row' | 'table_cell';
  pattern: string; context_keywords: string[]; window_size: number; mask_text: string | null; priority: number;
  enabled: boolean; version: number; updated_at: string;
}
export interface SensitiveRoleMatrix {
  types: SensitiveType[];
  roles: Array<{ role_id: number; role_name: string; permissions: Record<string, boolean> }>;
}
export interface SensitiveAudit {
  id: number; user_id: number | null; username: string | null; role_ids: number[]; role_names: string[];
  message_id: number | null; chat_type: string; project_id: number | null; project_name: string | null;
  redaction_types: string[]; redaction_count: number;
  final_answer_redacted: boolean; created_at: string;
}
export interface SensitiveAuditFilters {
  page?: number; page_size?: number; started_at?: string; ended_at?: string; user_id?: number;
  sensitive_type?: string; final_answer_redacted?: boolean; chat_type?: string; project_id?: number;
}
export const listSensitiveTypes = () => request.get('/sensitive-content/types') as Promise<SensitiveType[]>;
export const saveSensitiveType = (payload: Omit<SensitiveType, 'id' | 'updated_at'>, id?: number) =>
  (id ? request.put(`/sensitive-content/types/${id}`, payload) : request.post('/sensitive-content/types', payload)) as Promise<SensitiveType>;
export const listSensitiveRules = () => request.get('/sensitive-content/rules') as Promise<SensitiveRule[]>;
export const saveSensitiveRule = (payload: Omit<SensitiveRule, 'id' | 'version' | 'updated_at'>, id?: number) =>
  (id ? request.put(`/sensitive-content/rules/${id}`, payload) : request.post('/sensitive-content/rules', payload)) as Promise<SensitiveRule>;
export const testSensitiveRule = (payload: { content: string; role_id?: number; rule_id?: number; rule_enabled: boolean }) =>
  request.post('/sensitive-content/rules/test', payload) as Promise<{ safe_content: string; redacted: boolean; redaction_types: string[]; matched_rule_names: string[] }>;
export const getSensitivePermissionMatrix = () => request.get('/sensitive-content/roles/permissions/matrix') as Promise<SensitiveRoleMatrix>;
export const saveSensitiveRolePermissions = (roleId: number, permissions: Record<string, boolean>) =>
  request.put(`/sensitive-content/roles/${roleId}/permissions`, { permissions }) as Promise<{ saved: boolean }>;
export const refreshSensitiveCache = () =>
  request.post('/sensitive-content/cache/refresh') as Promise<{ refreshed: boolean }>;
export const listSensitiveAudits = (params: SensitiveAuditFilters = {}) =>
  request.get('/sensitive-content/audits', { params }) as Promise<{
    items: SensitiveAudit[]; total: number; page: number; page_size: number;
  }>;
