import type { SecurityLevel, UserInfo } from '@/types/api';

export interface SecurityLevelOption {
  label: string;
  value: SecurityLevel;
  disabled?: boolean;
}

export const SECURITY_LEVEL_RANK: Record<SecurityLevel, number> = {
  public: 0,
  internal: 1,
  confidential: 2,
};

export const SECURITY_LEVEL_OPTIONS: SecurityLevelOption[] = [
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

export function normalizeSecurityLevel(level?: string | null, fallback: SecurityLevel = 'internal'): SecurityLevel {
  if (level === 'public' || level === 'internal' || level === 'confidential') return level;
  return fallback;
}

/** 优先使用后端计算结果；兼容旧接口时仅从启用角色推导，避免禁用角色扩大权限。 */
export function resolveUserMaxSecurityLevel(user?: UserInfo | null): SecurityLevel {
  if (user?.max_security_level) return normalizeSecurityLevel(user.max_security_level, 'public');

  return (user?.roles || [])
    .filter((role) => role.enabled)
    .reduce<SecurityLevel>((current, role) => {
      const roleLevel = normalizeSecurityLevel(role.security_level, 'public');
      return SECURITY_LEVEL_RANK[roleLevel] > SECURITY_LEVEL_RANK[current] ? roleLevel : current;
    }, 'public');
}

export function allowedSecurityLevels(maxSecurityLevel?: string | null): SecurityLevel[] {
  const normalizedMax = normalizeSecurityLevel(maxSecurityLevel, 'public');
  return SECURITY_LEVEL_OPTIONS.filter((option) => SECURITY_LEVEL_RANK[option.value] <= SECURITY_LEVEL_RANK[normalizedMax]).map(
    (option) => option.value,
  );
}

/** 越权旧值仅用于兼容展示，并明确禁用，防止编辑表单打开时静默修改数据。 */
export function securityLevelOptions(maxSecurityLevel?: string | null, currentValue?: string | null): SecurityLevelOption[] {
  const normalizedMax = normalizeSecurityLevel(maxSecurityLevel, 'public');
  const options = SECURITY_LEVEL_OPTIONS.filter((option) => SECURITY_LEVEL_RANK[option.value] <= SECURITY_LEVEL_RANK[normalizedMax]).map(
    (option) => ({ ...option }),
  );
  const normalizedCurrent = currentValue ? normalizeSecurityLevel(currentValue, 'public') : null;
  if (normalizedCurrent && SECURITY_LEVEL_RANK[normalizedCurrent] > SECURITY_LEVEL_RANK[normalizedMax]) {
    const legacyOption = SECURITY_LEVEL_OPTIONS.find((option) => option.value === normalizedCurrent);
    if (legacyOption) options.push({ ...legacyOption, disabled: true });
  }
  return options.sort((left, right) => SECURITY_LEVEL_RANK[left.value] - SECURITY_LEVEL_RANK[right.value]);
}

export function clampSecurityLevel(
  level: string | null | undefined,
  maxSecurityLevel?: string | null,
  fallback: SecurityLevel = 'internal',
): SecurityLevel {
  const normalizedMax = normalizeSecurityLevel(maxSecurityLevel, 'public');
  const normalizedLevel = normalizeSecurityLevel(level, fallback);
  return SECURITY_LEVEL_RANK[normalizedLevel] <= SECURITY_LEVEL_RANK[normalizedMax] ? normalizedLevel : normalizedMax;
}

export function securityLevelLabel(level?: string | null): string {
  return SECURITY_LEVEL_LABELS[normalizeSecurityLevel(level)];
}

export function securityLevelTheme(level?: string | null): 'success' | 'warning' | 'danger' {
  return SECURITY_LEVEL_THEMES[normalizeSecurityLevel(level)];
}
