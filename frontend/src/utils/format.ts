/**
 * Format Utilities
 *
 * 负责：
 * 1. 统一日期、文件大小格式化
 * 2. 让页面展示逻辑保持简洁
 * 3. 避免魔法格式散落在组件中
 */

const DISPLAY_TIME_ZONE = 'Asia/Shanghai';
const TIME_ZONE_SUFFIX_PATTERN = /(?:Z|[+-]\d{2}:?\d{2})$/iu;

const dateTimeFormatter = new Intl.DateTimeFormat('en-CA', {
  timeZone: DISPLAY_TIME_ZONE,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

export function formatDateTime(value?: string | null): string {
  /**
   * 格式化日期时间。
   *
   * 后端时间统一按 UTC 存储，接口字段可能没有显式时区后缀；
   * 前端展示时固定转为东八区，避免页面时间比业务时间少 8 小时。
   */
  const rawValue = value?.trim();
  if (!rawValue) return '-';

  const date = parseDateTime(rawValue);
  if (!date) return rawValue.replace('T', ' ').slice(0, 19);

  return formatDateTimeParts(date);
}

function parseDateTime(value: string): Date | null {
  const normalizedSeparatorValue = value.replace(' ', 'T');
  const normalizedValue = TIME_ZONE_SUFFIX_PATTERN.test(normalizedSeparatorValue)
    ? normalizedSeparatorValue
    : `${normalizedSeparatorValue}Z`;
  const date = new Date(normalizedValue);

  return Number.isNaN(date.getTime()) ? null : date;
}

function formatDateTimeParts(date: Date): string {
  const parts = dateTimeFormatter.formatToParts(date).reduce<Record<string, string>>((result, part) => {
    if (part.type !== 'literal') {
      result[part.type] = part.value;
    }
    return result;
  }, {});

  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute}:${parts.second}`;
}

export function formatFileSize(value: number): string {
  /**
   * 格式化文件大小。
   */
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
