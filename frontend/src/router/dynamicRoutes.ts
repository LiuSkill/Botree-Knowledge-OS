/**
 * Dynamic RBAC Routes
 *
 * 负责：
 * 1. 根据后端授权菜单树动态注册前端路由
 * 2. 在权限变化时移除旧路由，确保无权限页面不进入路由表
 * 3. 维护菜单 path 与本地页面组件的最小映射
 */

import type { Router, RouteRecordRaw } from 'vue-router';

import type { SystemMenuNode } from '@/types/api';
import { firstMenuPath } from '@/utils/rbacMenus';

export const ROOT_ROUTE_NAME = 'authorized-root';
export const NOT_FOUND_ROUTE_NAME = 'authorized-not-found';

type RouteComponent = NonNullable<RouteRecordRaw['component']>;

const pageComponents: Record<string, RouteComponent> = {
  '/dashboard': () => import('@/views/dashboard/DashboardPage.vue'),
  '/knowledge': () => import('@/views/knowledge/KnowledgeBaseListPage.vue'),
  '/projects': () => import('@/views/project/ProjectListPage.vue'),
  '/authorization': () => import('@/views/auth-center/KnowledgeAuthPage.vue'),
  '/reviews': () => import('@/views/review/ReviewTaskPage.vue'),
  '/ai/project-chat': () => import('@/views/ai/ProjectChatPage.vue'),
  '/ai/base-chat': () => import('@/views/ai/BaseChatPage.vue'),
  '/system/users': () => import('@/views/system/UserManagePage.vue'),
  '/system/permissions': () => import('@/views/system/PermissionMatrixPage.vue'),
  '/system/model-configs': () => import('@/views/system/ModelConfigPage.vue'),
  '/system/logs': () => import('@/views/system/OperationLogPage.vue'),
  '/system/qa-audits': () => import('@/views/system/QAAuditPage.vue'),
};

const extraRoutesByMenuId: Record<string, Array<{ path: string; name: string; component: RouteComponent }>> = {
  knowledge: [
    { path: '/knowledge/bases/:id', name: 'knowledge-base-detail', component: () => import('@/views/knowledge/KnowledgeCollectionPage.vue') },
    { path: '/documents/:id', name: 'knowledge-document-detail', component: () => import('@/views/knowledge/DocumentDetailPage.vue') },
  ],
  project: [
    { path: '/projects/:id', name: 'project-detail', component: () => import('@/views/project/ProjectDetailPage.vue') },
    { path: '/projects/:id/documents', name: 'project-document-manage', component: () => import('@/views/project/ProjectDocumentManagePage.vue') },
  ],
  review: [
    { path: '/reviews/:id', name: 'review-detail', component: () => import('@/views/review/ReviewDetailPage.vue') },
  ],
};

let routeSignature = '';
let removeDynamicRoutes: Array<() => void> = [];

export function syncAuthorizedRoutes(router: Router, authorizedMenus: SystemMenuNode[]): boolean {
  const nextSignature = JSON.stringify(authorizedMenus);
  if (nextSignature === routeSignature) return false;

  resetAuthorizedRoutes();
  routeSignature = nextSignature;

  createAuthorizedRoutes(authorizedMenus).forEach((route) => {
    removeDynamicRoutes.push(router.addRoute(ROOT_ROUTE_NAME, route));
  });
  return true;
}

export function resetAuthorizedRoutes(): void {
  removeDynamicRoutes.forEach((removeRoute) => removeRoute());
  removeDynamicRoutes = [];
  routeSignature = '';
}

function createAuthorizedRoutes(menus: SystemMenuNode[]): RouteRecordRaw[] {
  const routes: RouteRecordRaw[] = [];
  menus.forEach((node) => {
    if (node.id === 'system' && node.children.length) {
      routes.push(createSystemRoute(node));
      return;
    }
    if (node.children.length) {
      node.children.forEach((child) => routes.push(...createLeafRoutes(child)));
      return;
    }
    routes.push(...createLeafRoutes(node));
  });
  return routes;
}

function createSystemRoute(node: SystemMenuNode): RouteRecordRaw {
  return {
    path: toChildPath(node.path || '/system'),
    name: routeName(node.id),
    component: () => import('@/views/system/SystemLayoutPage.vue'),
    redirect: firstMenuPath(node.children) || undefined,
    meta: { menuId: node.id, title: node.name },
    children: node.children.map((child) => createMenuRoute(child, node.path || '/system')).filter(isRoute),
  };
}

function createLeafRoutes(node: SystemMenuNode): RouteRecordRaw[] {
  const route = createMenuRoute(node);
  if (!route) return [];
  return [route, ...(extraRoutesByMenuId[node.id] || []).map((item) => createExtraRoute(node, item))];
}

function createMenuRoute(node: SystemMenuNode, parentPath = ''): RouteRecordRaw | null {
  if (!node.path) return null;
  const component = pageComponents[node.path];
  if (!component) return null;
  return {
    path: parentPath ? toRelativeChildPath(node.path, parentPath) : toChildPath(node.path),
    name: routeName(node.id),
    component,
    meta: { permission: node.id, menuId: node.id, title: node.name },
  };
}

function createExtraRoute(
  node: SystemMenuNode,
  item: { path: string; name: string; component: RouteComponent },
): RouteRecordRaw {
  return {
    path: toChildPath(item.path),
    name: routeName(`${node.id}:${item.name}`),
    component: item.component,
    meta: { permission: node.id, menuId: node.id, title: node.name },
  };
}

function toChildPath(path: string): string {
  return path.replace(/^\//, '');
}

function toRelativeChildPath(path: string, parentPath: string): string {
  const normalizedParent = parentPath.replace(/\/$/, '');
  return path.replace(`${normalizedParent}/`, '');
}

function routeName(menuId: string): string {
  return `authorized:${menuId}`;
}

function isRoute(route: RouteRecordRaw | null): route is RouteRecordRaw {
  return Boolean(route);
}
