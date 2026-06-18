/**
 * RBAC Menu Helpers
 *
 * 负责：
 * 1. 根据当前用户菜单权限过滤后端菜单树
 * 2. 从授权菜单树中提取首个可访问路径
 * 3. 为动态路由和导航菜单提供同一份树形数据
 */

import type { SystemMenuNode } from '@/types/api';

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

export function findMenuNode(nodes: SystemMenuNode[], menuId: string): SystemMenuNode | null {
  for (const node of nodes) {
    if (node.id === menuId) return node;
    const child = findMenuNode(node.children || [], menuId);
    if (child) return child;
  }
  return null;
}
