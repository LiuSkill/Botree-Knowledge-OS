/**
 * Breadcrumb context helpers
 *
 * 负责在业务页面跳转时携带来源面包屑，目标页再追加自身标题，形成真实访问路径。
 */
import type { LocationQueryRaw, RouteLocationNormalizedLoaded, RouteLocationRaw } from 'vue-router';

export type BreadcrumbContextItem = {
  label: string;
  path?: string;
  query?: Record<string, string>;
};

type RouteBreadcrumbItem = {
  title?: string;
  label?: string;
  path?: string;
  query?: Record<string, string>;
};

type RouteBreadcrumbConfig = {
  items: RouteBreadcrumbItem[];
  replaceBase?: boolean;
};

type RouteBreadcrumbValue = RouteBreadcrumbItem[] | RouteBreadcrumbConfig;
type ResolvedRouteBreadcrumb = {
  items: RouteBreadcrumbItem[];
  replaceBase: boolean;
};
type RouteBreadcrumbQueryItems = Record<string, Record<string, RouteBreadcrumbValue>>;

export const BREADCRUMB_CONTEXT_QUERY_KEY = '_breadcrumb';

const MAX_CONTEXT_ITEMS = 8;
const MENU_ROOT_PATH_BY_ID: Record<string, string> = {
  dashboard: '/dashboard',
  knowledge: '/knowledge',
  project: '/projects',
  authorization: '/authorization',
  review: '/reviews',
  'ai:project-chat': '/ai/project-chat',
  'ai:base-chat': '/ai/base-chat',
  'system:user': '/system/users',
  'system:department:view': '/system/departments',
  'system:permission': '/system/permissions',
  'system:model-config': '/system/model-configs',
  'system:operation-log': '/system/logs',
  'system:qa-audit': '/system/qa-audits',
};

export function withBreadcrumbContext(route: RouteLocationNormalizedLoaded, target: RouteLocationRaw): RouteLocationRaw {
  const trail = resolveRouteBreadcrumbTrail(route);
  if (!trail.length) return target;
  return attachBreadcrumbContext(target, trail);
}

export function hasBreadcrumbContext(route: RouteLocationNormalizedLoaded): boolean {
  return decodeBreadcrumbContext(route.query[BREADCRUMB_CONTEXT_QUERY_KEY]).length > 0;
}

export function resolveRouteBreadcrumbTrail(route: RouteLocationNormalizedLoaded): BreadcrumbContextItem[] {
  const sourceItems = decodeBreadcrumbContext(route.query[BREADCRUMB_CONTEXT_QUERY_KEY]);
  if (sourceItems.length) {
    return appendBreadcrumbItem(sourceItems, currentRouteBreadcrumbContextItem(route));
  }
  return deriveRouteBreadcrumbTrail(route);
}

export function currentRouteBreadcrumbContextItem(route: RouteLocationNormalizedLoaded): BreadcrumbContextItem | null {
  const configured = resolveRouteBreadcrumb(route);
  const lastItem = configured.items[configured.items.length - 1];
  const label = normalizeTitle(lastItem?.title || lastItem?.label || route.meta.breadcrumbTitle || route.meta.title);
  if (!label) return null;
  return {
    label,
    path: route.path,
    query: cleanRouteQuery(route.query),
  };
}

export function previousBreadcrumbTarget(route: RouteLocationNormalizedLoaded): RouteLocationRaw | null {
  const sourceItems = decodeBreadcrumbContext(route.query[BREADCRUMB_CONTEXT_QUERY_KEY]);
  const previousItem = sourceItems[sourceItems.length - 1];
  return previousItem ? breadcrumbItemTarget(previousItem) : null;
}

export function breadcrumbItemTarget(item: BreadcrumbContextItem): RouteLocationRaw | null {
  if (!item.path) return null;
  return item.query && Object.keys(item.query).length ? { path: item.path, query: item.query } : item.path;
}

function attachBreadcrumbContext(target: RouteLocationRaw, trail: BreadcrumbContextItem[]): RouteLocationRaw {
  const encodedContext = encodeBreadcrumbContext(trail);
  if (typeof target === 'string') {
    return attachBreadcrumbContextToStringTarget(target, encodedContext);
  }
  return {
    ...target,
    query: {
      ...((target.query || {}) as LocationQueryRaw),
      [BREADCRUMB_CONTEXT_QUERY_KEY]: encodedContext,
    },
  } as RouteLocationRaw;
}

function attachBreadcrumbContextToStringTarget(target: string, encodedContext: string): RouteLocationRaw {
  const [pathAndQuery, hash = ''] = target.split('#');
  const [path, search = ''] = pathAndQuery.split('?');
  const query: LocationQueryRaw = {};
  new URLSearchParams(search).forEach((value, key) => {
    query[key] = value;
  });
  query[BREADCRUMB_CONTEXT_QUERY_KEY] = encodedContext;
  return {
    path: path || '/',
    query,
    ...(hash ? { hash: `#${hash}` } : {}),
  };
}

function deriveRouteBreadcrumbTrail(route: RouteLocationNormalizedLoaded): BreadcrumbContextItem[] {
  const configured = resolveRouteBreadcrumb(route);
  const configuredItems = configured.items
    .map((item, index) => toContextItem(item, route, index === configured.items.length - 1))
    .filter((item): item is BreadcrumbContextItem => Boolean(item));

  if (configured.replaceBase) {
    return compactBreadcrumbItems(configuredItems);
  }

  const menuTitle = normalizeTitle(route.meta.title);
  const menuItem = menuTitle
    ? {
        label: menuTitle,
        path: menuRootPath(route) || route.path,
      }
    : null;

  if (configuredItems.length) {
    return compactBreadcrumbItems([menuItem, ...configuredItems]);
  }

  return compactBreadcrumbItems([currentRouteBreadcrumbContextItem(route) || menuItem]);
}

function resolveRouteBreadcrumb(route: RouteLocationNormalizedLoaded): ResolvedRouteBreadcrumb {
  return queryBreadcrumb(route.meta.breadcrumbQueryItems, route) || normalizeRouteBreadcrumb(route.meta.breadcrumbItems);
}

function normalizeRouteBreadcrumb(value: unknown): ResolvedRouteBreadcrumb {
  if (Array.isArray(value)) {
    return { items: value as RouteBreadcrumbItem[], replaceBase: false };
  }
  if (!value || typeof value !== 'object') {
    return { items: [], replaceBase: false };
  }
  const config = value as RouteBreadcrumbConfig;
  return {
    items: Array.isArray(config.items) ? config.items : [],
    replaceBase: Boolean(config.replaceBase),
  };
}

function queryBreadcrumb(value: unknown, route: RouteLocationNormalizedLoaded): ResolvedRouteBreadcrumb | null {
  if (!value || typeof value !== 'object') return null;
  const queryItems = value as RouteBreadcrumbQueryItems;
  for (const [queryKey, itemsByValue] of Object.entries(queryItems)) {
    const queryValue = routeQueryText(route.query[queryKey]);
    const configuredItems = queryValue ? itemsByValue[queryValue] : undefined;
    if (configuredItems) {
      return normalizeRouteBreadcrumb(configuredItems);
    }
  }
  return null;
}

function toContextItem(
  item: RouteBreadcrumbItem,
  route: RouteLocationNormalizedLoaded,
  isCurrent: boolean,
): BreadcrumbContextItem | null {
  const label = normalizeTitle(item.title || item.label);
  if (!label) return null;
  const path = item.path ? fillPathParams(item.path, route) : isCurrent ? route.path : undefined;
  return {
    label,
    ...(path ? { path } : {}),
    query: item.query || (isCurrent ? cleanRouteQuery(route.query) : undefined),
  };
}

function menuRootPath(route: RouteLocationNormalizedLoaded): string | undefined {
  const menuId = normalizeTitle(route.meta.menuId);
  return menuId ? MENU_ROOT_PATH_BY_ID[menuId] : undefined;
}

function appendBreadcrumbItem(
  items: BreadcrumbContextItem[],
  item: BreadcrumbContextItem | null,
): BreadcrumbContextItem[] {
  if (!item) return compactBreadcrumbItems(items);
  return compactBreadcrumbItems([...items, item]);
}

function compactBreadcrumbItems(items: Array<BreadcrumbContextItem | null>): BreadcrumbContextItem[] {
  const compacted: BreadcrumbContextItem[] = [];
  items.forEach((item) => {
    if (!item?.label) return;
    const normalizedItem = normalizeContextItem(item);
    const previous = compacted[compacted.length - 1];
    if (previous && isSameBreadcrumbItem(previous, normalizedItem)) {
      compacted[compacted.length - 1] = normalizedItem;
      return;
    }
    compacted.push(normalizedItem);
  });
  return compacted.slice(-MAX_CONTEXT_ITEMS);
}

function normalizeContextItem(item: BreadcrumbContextItem): BreadcrumbContextItem {
  return {
    label: item.label.trim(),
    ...(item.path ? { path: item.path } : {}),
    ...(item.query && Object.keys(item.query).length ? { query: item.query } : {}),
  };
}

function isSameBreadcrumbItem(left: BreadcrumbContextItem, right: BreadcrumbContextItem): boolean {
  return left.label === right.label && (left.path || '') === (right.path || '');
}

function encodeBreadcrumbContext(items: BreadcrumbContextItem[]): string {
  return JSON.stringify(compactBreadcrumbItems(items));
}

function decodeBreadcrumbContext(value: unknown): BreadcrumbContextItem[] {
  const rawValue = routeQueryText(value);
  if (!rawValue) return [];
  try {
    const parsed = JSON.parse(rawValue) as unknown;
    if (!Array.isArray(parsed)) return [];
    return compactBreadcrumbItems(
      parsed.map((item) => {
        if (!item || typeof item !== 'object') return null;
        const candidate = item as BreadcrumbContextItem;
        const label = normalizeTitle(candidate.label);
        if (!label) return null;
        return {
          label,
          ...(typeof candidate.path === 'string' && candidate.path ? { path: candidate.path } : {}),
          ...(candidate.query && typeof candidate.query === 'object' ? { query: stringRecord(candidate.query) } : {}),
        };
      }),
    );
  } catch {
    return [];
  }
}

function stringRecord(value: Record<string, unknown>): Record<string, string> {
  const result: Record<string, string> = {};
  Object.entries(value).forEach(([key, item]) => {
    if (typeof item === 'string') {
      result[key] = item;
    }
  });
  return result;
}

function cleanRouteQuery(query: RouteLocationNormalizedLoaded['query']): Record<string, string> | undefined {
  const result: Record<string, string> = {};
  Object.entries(query).forEach(([key, value]) => {
    if (key === BREADCRUMB_CONTEXT_QUERY_KEY) return;
    const normalized = routeQueryText(value);
    if (normalized) result[key] = normalized;
  });
  return Object.keys(result).length ? result : undefined;
}

function fillPathParams(path: string, route: RouteLocationNormalizedLoaded): string | null {
  let missingParam = false;
  const filledPath = path.replace(/:([^/]+)/g, (_, key: string) => {
    const value = route.params[key] ?? route.query[key];
    const normalized = Array.isArray(value) ? value[0] : value;
    if (!normalized) {
      missingParam = true;
      return '';
    }
    return encodeURIComponent(String(normalized));
  });
  return missingParam ? null : filledPath;
}

function routeQueryText(value: unknown): string {
  const normalized = Array.isArray(value) ? value[0] : value;
  return typeof normalized === 'string' ? normalized.trim() : '';
}

function normalizeTitle(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
