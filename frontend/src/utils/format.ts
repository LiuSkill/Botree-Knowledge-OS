/**
 * Format Utilities
 *
 * 负责：
 * 1. 统一日期、文件大小格式化
 * 2. 让页面展示逻辑保持简洁
 * 3. 避免魔法格式散落在组件中
 */

export function formatDateTime(value?: string | null): string {
  /**
   * 格式化日期时间。
   */
  if (!value) return '-';
  return value.replace('T', ' ').slice(0, 19);
}

export function formatFileSize(value: number): string {
  /**
   * 格式化文件大小。
   */
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}
