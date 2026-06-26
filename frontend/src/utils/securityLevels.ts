import type { SecurityLevel } from '@/types/api';

export const SECURITY_LEVEL_OPTIONS: Array<{ label: string; value: SecurityLevel }> = [
  { label: '公开', value: 'public' },
  { label: '内部', value: 'internal' },
  { label: '秘密', value: 'confidential' },
];

export const SECURITY_LEVEL_LABELS: Record<SecurityLevel, string> = {
  public: '公开',
  internal: '内部',
  confidential: '秘密',
};

export const SECURITY_LEVEL_THEMES: Record<SecurityLevel, 'success' | 'warning' | 'danger'> = {
  public: 'success',
  internal: 'warning',
  confidential: 'danger',
};

export function securityLevelLabel(level?: string | null): string {
  return SECURITY_LEVEL_LABELS[(level as SecurityLevel) || 'internal'] || '内部';
}

export function securityLevelTheme(level?: string | null): 'success' | 'warning' | 'danger' {
  return SECURITY_LEVEL_THEMES[(level as SecurityLevel) || 'internal'] || 'warning';
}
