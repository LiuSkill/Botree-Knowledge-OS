import { i18n, type SupportedLocale } from '@/locales';

const DISPLAY_TIME_ZONE = 'Asia/Shanghai';

function currentLocale(): SupportedLocale {
  return i18n.global.locale.value as SupportedLocale;
}

export function formatDate(value: string | number | Date): string {
  return new Intl.DateTimeFormat(currentLocale(), { timeZone: DISPLAY_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value));
}

export function formatLocalizedDateTime(value: string | number | Date): string {
  return new Intl.DateTimeFormat(currentLocale(), {
    timeZone: DISPLAY_TIME_ZONE, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23',
  }).format(new Date(value));
}

export function formatNumber(value: number, options?: Intl.NumberFormatOptions): string {
  return new Intl.NumberFormat(currentLocale(), options).format(value);
}

export function formatPercent(value: number, options?: Intl.NumberFormatOptions): string {
  return formatNumber(value, { style: 'percent', ...options });
}
