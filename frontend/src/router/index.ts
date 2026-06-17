/**
 * Botree Knowledge OS Router
 *
 * 负责：
 * 1. 维护 Vue Router 路由表
 * 2. 登录态守卫
 * 3. 系统管理子路由组织
 */

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router';

import { useAuthStore } from '@/stores/auth';
import { getToken } from '@/utils/auth';

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    component: () => import('@/views/login/LoginPage.vue'),
    meta: { public: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/BasicLayout.vue'),
    children: [
      { path: '', redirect: '/dashboard' },
      { path: 'dashboard', component: () => import('@/views/dashboard/DashboardPage.vue'), meta: { permission: 'dashboard:view' } },
      { path: 'knowledge', component: () => import('@/views/knowledge/KnowledgeBaseListPage.vue'), meta: { permission: 'knowledge:view' } },
      { path: 'knowledge/bases/:id', component: () => import('@/views/knowledge/KnowledgeCollectionPage.vue'), meta: { permission: 'knowledge:view' } },
      { path: 'documents/:id', component: () => import('@/views/knowledge/DocumentDetailPage.vue'), meta: { permission: 'knowledge:view' } },
      { path: 'projects', component: () => import('@/views/project/ProjectListPage.vue'), meta: { permission: 'project:view' } },
      { path: 'projects/:id', component: () => import('@/views/project/ProjectDetailPage.vue'), meta: { permission: 'project:view' } },
      { path: 'authorization', component: () => import('@/views/auth-center/KnowledgeAuthPage.vue'), meta: { permission: 'authorization:view' } },
      { path: 'reviews', component: () => import('@/views/review/ReviewTaskPage.vue'), meta: { permission: 'review:view' } },
      { path: 'reviews/:id', component: () => import('@/views/review/ReviewDetailPage.vue'), meta: { permission: 'review:view' } },
      { path: 'ai', redirect: '/ai/project-chat' },
      { path: 'ai/project-chat', component: () => import('@/views/ai/ProjectChatPage.vue'), meta: { permission: 'ai:view' } },
      { path: 'ai/base-chat', component: () => import('@/views/ai/BaseChatPage.vue'), meta: { permission: 'ai:view' } },
      {
        path: 'system',
        component: () => import('@/views/system/SystemLayoutPage.vue'),
        meta: { permission: 'system:view' },
        children: [
          { path: '', redirect: '/system/users' },
          { path: 'users', component: () => import('@/views/system/UserManagePage.vue'), meta: { permission: 'system:view' } },
          { path: 'roles', component: () => import('@/views/system/RoleManagePage.vue'), meta: { permission: 'system:view' } },
          { path: 'permissions', component: () => import('@/views/system/PermissionMatrixPage.vue'), meta: { permission: 'system:view' } },
          { path: 'logs', component: () => import('@/views/system/OperationLogPage.vue'), meta: { permission: 'system:view' } },
          { path: 'qa-audits', component: () => import('@/views/system/QAAuditPage.vue'), meta: { permission: 'system:view' } },
          { path: 'model-configs', component: () => import('@/views/system/ModelConfigPage.vue'), meta: { permission: 'system:view' } },
        ],
      },
    ],
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
];

const router = createRouter({
  history: createWebHistory(),
  routes,
});

router.beforeEach(async (to) => {
  /**
   * 认证守卫：
   * - 登录页公开
   * - 未登录跳转登录
   * - 有 Token 但未加载用户时自动刷新用户信息
   */
  if (to.meta.public) return true;
  const token = getToken();
  if (!token) return `/login?redirect=${encodeURIComponent(to.fullPath)}`;
  const authStore = useAuthStore();
  if (!authStore.user) {
    await authStore.loadMe().catch(() => undefined);
  }
  const requiredPermission = to.matched.find((item) => item.meta.permission)?.meta.permission as string | undefined;
  if (requiredPermission && !authStore.hasPermission(requiredPermission) && to.path !== '/dashboard') {
    return '/dashboard';
  }
  return true;
});

export default router;
