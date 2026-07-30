import { defineStore } from 'pinia';

import { i18n, isSupportedLocale, LOCALE_STORAGE_KEY, resolveInitialLocale, type SupportedLocale } from '@/locales';

export const useLocaleStore = defineStore('locale', {
  state: () => ({ locale: resolveInitialLocale() as SupportedLocale }),
  actions: {
    setLocale(value: unknown): void {
      const locale = isSupportedLocale(value) ? value : 'zh-CN';
      this.locale = locale;
      i18n.global.locale.value = locale;
      localStorage.setItem(LOCALE_STORAGE_KEY, locale);
      document.documentElement.lang = locale;
      const titleKey = document.documentElement.dataset.titleKey;
      if (titleKey) document.title = `${i18n.global.t(titleKey)} | Botree Knowledge OS`;
    },
    initialize(): void {
      this.setLocale(this.locale);
    },
  },
});
