/**
 * RBAC Menu Helpers
 *
 * 负责：
 * 1. 根据当前用户菜单权限过滤后端菜单树
 * 2. 从授权菜单树中提取首个可访问路径
 * 3. 为动态路由和导航菜单提供同一份树形数据
 */

import type { SystemMenuNode } from '@/types/api';

const KNOWLEDGE_QA_MENU_ID = 'ai';
const KNOWLEDGE_QA_CHILD_IDS = new Set(['ai:project-chat', 'ai:base-chat']);
const DASHBOARD_PATH = '/dashboard';

export function filterAuthorizedMenuTree(
  nodes: SystemMenuNode[],
  hasMenuPermission: (menuId: string) => boolean,
): SystemMenuNode[] {
  return nodes
    .map((node) => {
      const children = filterAuthorizedMenuTree(node.children || [], hasMenuPermission);
      const allowedLeaf = Boolean(node.path && !node.children?.length && hasMenuPermission(node.id));
      if (!allowedLeaf && children.length === 0) return null;
      return { ...node, children };
    })
    .filter((node): node is SystemMenuNode => Boolean(node));
}

export function normalizeAuthorizedMenuTree(nodes: SystemMenuNode[]): SystemMenuNode[] {
  const result: SystemMenuNode[] = [];
  const qaChildren: SystemMenuNode[] = [];
  let existingQaMenu: SystemMenuNode | null = null;

  for (const node of nodes) {
    if (node.id === KNOWLEDGE_QA_MENU_ID) {
      existingQaMenu = node;
      continue;
    }
    if (KNOWLEDGE_QA_CHILD_IDS.has(node.id)) {
      qaChildren.push(node);
      continue;
    }
    result.push(node);
  }

  const mergedQaChildren = [
    ...(existingQaMenu?.children || []),
    ...qaChildren.filter((child) => !(existingQaMenu?.children || []).some((item) => item.id === child.id)),
  ];
  if (!existingQaMenu && mergedQaChildren.length === 0) {
    return result;
  }

  const qaMenu: SystemMenuNode = existingQaMenu
    ? { ...existingQaMenu, path: null, children: mergedQaChildren }
    : {
        id: KNOWLEDGE_QA_MENU_ID,
        name: '知识问答',
        path: null,
        permission_id: null,
        children: mergedQaChildren,
      };

  const insertIndex = result.findIndex((node) => node.id === 'system');
  if (insertIndex >= 0) {
    result.splice(insertIndex, 0, qaMenu);
    return result;
  }
  return [...result, qaMenu];
}

export function preferredFirstMenuPath(nodes: SystemMenuNode[]): string | null {
  return hasMenuPath(nodes, DASHBOARD_PATH) ? DASHBOARD_PATH : firstMenuPath(nodes);
}

export function firstMenuPath(nodes: SystemMenuNode[]): string | null {
  for (const node of nodes) {
    if (node.children?.length) {
      const childPath = firstMenuPath(node.children);
      if (childPath) return childPath;
    }
    if (node.path) return node.path;
  }
  return null;
}

export function collectMenuPaths(node: SystemMenuNode): string[] {
  const paths = node.path ? [node.path] : [];
  return paths.concat((node.children || []).flatMap((child) => collectMenuPaths(child)));
}

export function hasMenuPath(nodes: SystemMenuNode[], path: string): boolean {
  return nodes.some((node) => node.path === path || hasMenuPath(node.children || [], path));
}

export function findMenuNode(nodes: SystemMenuNode[], menuId: string): SystemMenuNode | null {
  for (const node of nodes) {
    if (node.id === menuId) return node;
    const child = findMenuNode(node.children || [], menuId);
    if (child) return child;
  }
  return null;
}

export function findMenuNodePath(nodes: SystemMenuNode[], menuId: string): SystemMenuNode[] {
  for (const node of nodes) {
    if (node.id === menuId) return [node];
    const childPath = findMenuNodePath(node.children || [], menuId);
    if (childPath.length) return [node, ...childPath];
  }
  return [];
}
