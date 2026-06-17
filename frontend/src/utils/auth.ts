/**
 * Auth Utilities
 *
 * 负责：
 * 1. 管理本地 Token
 * 2. 统一登录态存储键
 * 3. 避免请求层和页面层重复读写 localStorage
 */

const TOKEN_KEY = 'botree_access_token';

export function getToken(): string | null {
  /**
   * 获取本地 Token。
   */
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  /**
   * 保存本地 Token。
   */
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  /**
   * 清理本地 Token。
   */
  localStorage.removeItem(TOKEN_KEY);
}
