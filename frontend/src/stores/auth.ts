/**
 * Auth Store
 *
 * 负责：
 * 1. 保存当前用户和登录态
 * 2. 封装登录、退出和刷新用户信息
 * 3. 为路由守卫提供认证状态
 */

import { defineStore } from 'pinia';

import { changeMyPassword, deleteMyAvatar, loginApi, logoutApi, meApi, uploadMyAvatar } from '@/api/auth';
import type { UserInfo } from '@/types/api';
import { clearToken, getToken, setToken } from '@/utils/auth';

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: null as UserInfo | null,
    loaded: false,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    isAdmin: (state) => Boolean(state.user?.roles?.some((role) => role.code === 'admin')),
    hasPermission: (state) => {
      /**
       * 判断当前用户是否拥有指定权限编码。
       */
      return (permissionCode: string): boolean =>
        Boolean(state.user?.roles?.some((role) => role.code === 'admin') || state.user?.permission_codes?.includes(permissionCode));
    },
  },
  actions: {
    async login(username: string, password: string) {
      /**
       * 执行登录并保存 Token。
       */
      const result = await loginApi({ username, password });
      this.token = result.access_token;
      this.user = result.user;
      this.loaded = true;
      setToken(result.access_token);
    },
    async loadMe() {
      /**
       * 根据本地 Token 刷新当前用户。
       */
      if (!this.token) return;
      this.user = await meApi();
      this.loaded = true;
    },
    async uploadAvatar(file: File) {
      /**
       * 上传当前用户头像并刷新用户资料。
       */
      this.user = await uploadMyAvatar(file);
    },
    async deleteAvatar() {
      /**
       * 删除当前用户头像并刷新用户资料。
       */
      this.user = await deleteMyAvatar();
    },
    async changePassword(currentPassword: string, newPassword: string) {
      /**
       * 修改当前用户密码。
       */
      await changeMyPassword({ current_password: currentPassword, new_password: newPassword });
    },
    async logout() {
      /**
       * 退出登录并清理本地状态。
       */
      if (this.token) {
        await logoutApi().catch(() => undefined);
      }
      this.token = null;
      this.user = null;
      this.loaded = false;
      clearToken();
    },
  },
});
