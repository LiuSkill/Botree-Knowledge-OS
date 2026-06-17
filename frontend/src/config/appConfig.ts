/**
 * Botree Knowledge OS App Configuration
 *
 * 负责：
 * 1. 统一读取前端运行时配置
 * 2. 避免业务模块直接访问 import.meta.env
 * 3. 为后续多环境配置扩展保留集中入口
 */

const DEFAULT_APP_TITLE = 'Botree Knowledge OS';

export interface AppConfig {
  /**
   * 应用显示标题
   */
  appTitle: string;
}

/**
 * 前端应用配置
 *
 * 返回:
 * - 已标准化的应用配置对象
 */
export const appConfig: AppConfig = {
  appTitle: import.meta.env.VITE_APP_TITLE || DEFAULT_APP_TITLE,
};
