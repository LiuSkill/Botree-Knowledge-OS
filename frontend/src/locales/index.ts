import { createI18n } from 'vue-i18n';

import enUS from './en-US';
import { DEFAULT_LOCALE, isSupportedLocale, LOCALE_STORAGE_KEY, type SupportedLocale } from './types';
import zhCN from './zh-CN';

export function resolveInitialLocale(): SupportedLocale {
  const storedLocale = localStorage.getItem(LOCALE_STORAGE_KEY);
  return isSupportedLocale(storedLocale) ? storedLocale : DEFAULT_LOCALE;
}

export const i18n = createI18n({
  legacy: false,
  locale: resolveInitialLocale(),
  fallbackLocale: DEFAULT_LOCALE,
  messages: { 'zh-CN': zhCN, 'en-US': enUS },
  missingWarn: import.meta.env.DEV,
  fallbackWarn: import.meta.env.DEV,
});

export type MessageSchema = typeof zhCN;
export { DEFAULT_LOCALE, isSupportedLocale, LOCALE_STORAGE_KEY } from './types';
export type { SupportedLocale } from './types';
