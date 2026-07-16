/**
 * Botree Knowledge OS Router
 *
 * 负责：
 * 1. 保留公共路由和登录后根布局
 * 2. 登录后根据后端菜单树动态注册授权路由
 * 3. 确保无权限页面不进入 Vue Router 路由表
 */

import { defineComponent } from 'vue';
import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

import { NOT_FOUND_ROUTE_NAME, ROOT_ROUTE_NAME, resetAuthorizedRoutes, syncAuthorizedRoutes } from '@/router/dynamicRoutes';
import { useAuthStore } from '@/stores/auth';
import { getToken } from '@/utils/auth';

const EmptyRouteView = defineComponent({
  name: 'EmptyRouteView',
  setup: () => () => null,
});

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'login',
    component: () => import('@/views/login/LoginPage.vue'),
    meta: { public: true },
  },
  {
    path: '/process-config/routes/:id/preview',
    name: 'process-route-preview',
    component: () => import('@/views/process-config/route/preview.vue'),
    meta: {
      permission: 'process_config:route',
      title: '线路预览',
    },
  },
  {
    path: '/process-config/calculator/standalone',
    name: 'process-calculator-standalone',
    component: () => import('@/views/process-config/FinancialCalculatorPage.vue'),
    meta: {
      permission: 'process_config:calculator',
      menuId: 'process_config:calculator',
      title: '快速财务计算器',
    },
  },
  {
    path: '/',
    name: ROOT_ROUTE_NAME,
    component: () => import('@/layouts/BasicLayout.vue'),
  },
  {
    path: '/:pathMatch(.*)*',
    name: NOT_FOUND_ROUTE_NAME,
    component: EmptyRouteView,
  },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  const token = getToken();
  if (to.meta.public) {
    if (!token) resetAuthorizedRoutes();
    return true;
  }
  if (!token) {
    resetAuthorizedRoutes();
    return `/login?redirect=${encodeURIComponent(to.fullPath)}`;
  }

  const authStore = useAuthStore();
  if (!authStore.user || !authStore.loaded) {
    await authStore.loadMe().catch(() => undefined);
  }
  if (!authStore.user) {
    resetAuthorizedRoutes();
    return `/login?redirect=${encodeURIComponent(to.fullPath)}`;
  }

  syncAuthorizedRoutes(router, authStore.authorizedMenuTree);

  if (to.path === '/') {
    return authStore.firstAccessiblePath || false;
  }

  if (to.name === NOT_FOUND_ROUTE_NAME && router.resolve(to.fullPath).name !== NOT_FOUND_ROUTE_NAME) {
    return to.fullPath;
  }

  const requiredPermission = [...to.matched].reverse().find((item) => item.meta.permission)?.meta.permission as string | undefined;
  if (requiredPermission && !authStore.hasMenuPermission(requiredPermission)) {
    return authStore.firstAccessiblePath || false;
  }

  if (to.name === NOT_FOUND_ROUTE_NAME) {
    const fallbackPath = authStore.firstAccessiblePath;
    if (fallbackPath && fallbackPath !== to.path) return fallbackPath;
    return false;
  }

  return true;
});

export default router;
