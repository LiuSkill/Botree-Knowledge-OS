import { i18n } from '@/locales';

const ERROR_CODE_KEYS: Record<string, string> = {
  PROJECT_ACCESS_DENIED: 'auth.permissionDenied',
};

type ApiErrorPayload = { code?: unknown; message?: unknown };

export function resolveApiErrorMessage(error: unknown): string {
  const candidate = error as { response?: { data?: ApiErrorPayload }; message?: unknown };
  const payload = candidate?.response?.data;
  const code = typeof payload?.code === 'string' ? payload.code : '';
  const key = ERROR_CODE_KEYS[code];
  if (key) return i18n.global.t(key);
  if (typeof payload?.message === 'string' && payload.message.trim()) return payload.message;
  if (typeof candidate?.message === 'string' && candidate.message.trim()) return candidate.message;
  return i18n.global.t('common.message.requestFailed');
}
