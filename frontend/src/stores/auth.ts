/**
 * Auth Store
 *
 * 负责：
 * 1. 保存当前用户和登录态
 * 2. 封装登录、退出和刷新用户信息
 * 3. 为路由守卫提供认证状态
 */

import { defineStore } from 'pinia';

import { changeMyPassword, currentPermissionsApi, deleteMyAvatar, loginApi, logoutApi, meApi, uploadMyAvatar } from '@/api/auth';
import { getSystemMenus } from '@/api/system';
import type { CurrentPermissions, SystemMenuNode, UserInfo } from '@/types/api';
import { clearToken, getToken, setToken } from '@/utils/auth';
import { filterAuthorizedMenuTree, normalizeAuthorizedMenuTree, preferredFirstMenuPath } from '@/utils/rbacMenus';
import { resolveUserMaxSecurityLevel, securityLevelOptions } from '@/utils/securityLevels';

const EMPTY_PERMISSIONS: CurrentPermissions = {
  menus: [],
  actions: [],
};

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: getToken(),
    user: null as UserInfo | null,
    permissions: { ...EMPTY_PERMISSIONS } as CurrentPermissions,
    menuTree: [] as SystemMenuNode[],
    loaded: false,
  }),
  getters: {
    isLoggedIn: (state) => Boolean(state.token),
    isAdmin: (state) => Boolean(state.user?.roles?.some((role) => role.code === 'admin' && role.enabled)),
    maxSecurityLevel: (state) => resolveUserMaxSecurityLevel(state.user),
    allowedSecurityLevelOptions: (state) => securityLevelOptions(resolveUserMaxSecurityLevel(state.user)),
    hasPermission: (state) => {
      /**
       * 判断当前用户是否拥有指定权限编码。
       */
      return (permissionCode: string): boolean =>
        Boolean(
          state.user?.roles?.some((role) => role.code === 'admin' && role.enabled) ||
            state.permissions.menus.includes(permissionCode) ||
            state.permissions.actions.includes(permissionCode) ||
            state.user?.permission_codes?.includes(permissionCode),
        );
    },
    hasMenuPermission: (state) => {
      /**
       * 判断当前用户是否拥有菜单/路由访问权限。
       */
      return (permissionCode: string): boolean =>
        Boolean(state.user?.roles?.some((role) => role.code === 'admin' && role.enabled) || state.permissions.menus.includes(permissionCode));
    },
    hasActionPermission: (state) => {
      /**
       * 判断当前用户是否拥有按钮级操作权限。
       */
      return (permissionCode: string): boolean =>
        Boolean(state.user?.roles?.some((role) => role.code === 'admin' && role.enabled) || state.permissions.actions.includes(permissionCode));
    },
    authorizedMenuTree: (state): SystemMenuNode[] => {
      /**
       * 后端菜单树 + 当前用户菜单权限 = 实际可注册路由和可见菜单。
       */
      const isAdmin = Boolean(state.user?.roles?.some((role) => role.code === 'admin' && role.enabled));
      const menuCodes = new Set(state.permissions.menus);
      return normalizeAuthorizedMenuTree(filterAuthorizedMenuTree(state.menuTree, (menuId) => isAdmin || menuCodes.has(menuId)));
    },
    firstAccessiblePath: (state): string | null => {
      /**
       * 当前用户登录后可进入的第一个页面。
       */
      const isAdmin = Boolean(state.user?.roles?.some((role) => role.code === 'admin' && role.enabled));
      const menuCodes = new Set(state.permissions.menus);
      const authorizedTree = normalizeAuthorizedMenuTree(filterAuthorizedMenuTree(state.menuTree, (menuId) => isAdmin || menuCodes.has(menuId)));
      return preferredFirstMenuPath(authorizedTree);
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
      this.permissions = result.user.permissions || { ...EMPTY_PERMISSIONS };
      setToken(result.access_token);
      await this.loadAccessContext();
      this.loaded = true;
    },
    async loadMe() {
      /**
       * 根据本地 Token 刷新当前用户。
       */
      if (!this.token) return;
      this.user = await meApi();
      this.permissions = this.user.permissions || { ...EMPTY_PERMISSIONS };
      await this.loadAccessContext();
      this.loaded = true;
    },
    async loadAccessContext() {
      /**
       * 登录态权限上下文：一次性加载用户菜单/按钮权限和后端菜单树。
       */
      if (!this.token) return;
      const [permissions, menuTree] = await Promise.all([currentPermissionsApi(), getSystemMenus()]);
      this.permissions = permissions;
      this.menuTree = menuTree;
    },
    async loadCurrentPermissions() {
      /**
       * 从后端加载当前用户的菜单和按钮权限。
       */
      if (!this.token) return;
      this.permissions = await currentPermissionsApi();
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
      this.permissions = { ...EMPTY_PERMISSIONS };
      this.menuTree = [];
      this.loaded = false;
      clearToken();
    },
  },
});
