<!--
  AppBreadcrumb

  负责根据当前授权菜单树和路由元信息生成全局面包屑，避免各业务页面重复维护访问路径。
-->
<script setup lang="ts">
import { computed } from 'vue';
import { useRoute, useRouter, type RouteLocationRaw } from 'vue-router';
import { HomeIcon } from 'tdesign-icons-vue-next';
import { useI18n } from 'vue-i18n';

import { useAuthStore } from '@/stores/auth';
import type { SystemMenuNode } from '@/types/api';
import { breadcrumbItemTarget, hasBreadcrumbContext, resolveRouteBreadcrumbTrail } from '@/utils/breadcrumbContext';
import { findMenuNode, findMenuNodePath, firstMenuPath } from '@/utils/rbacMenus';
import { menuLabel } from '@/utils/localizedNavigation';

type BreadcrumbItem = {
  key: string;
  label: string;
  to: RouteLocationRaw | null;
  current: boolean;
};

type RouteBreadcrumbItem = {
  title?: string;
  titleKey?: string;
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
  items: BreadcrumbItem[];
  replaceBase: boolean;
};

type RouteBreadcrumbQueryItems = Record<string, Record<string, RouteBreadcrumbValue>>;

const DASHBOARD_MENU_ID = 'dashboard';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const { t } = useI18n();

const breadcrumbItems = computed<BreadcrumbItem[]>(() => {
  if (hasBreadcrumbContext(route)) {
    return resolveRouteBreadcrumbTrail(route).map((item, index, items) => ({
      key: `context:${index}:${item.label}`,
      label: translatedContextLabel(item),
      to: index === items.length - 1 ? null : breadcrumbItemTarget(item),
      current: index === items.length - 1,
    }));
  }

  const menuId = route.meta.menuId as string | undefined;
  const menuPath = menuId ? findMenuNodePath(authStore.authorizedMenuTree, menuId) : [];
  const items = menuPath.map((node) => toBreadcrumbItem(node)).filter((item): item is BreadcrumbItem => Boolean(item));

  const dashboardNode = findMenuNode(authStore.authorizedMenuTree, DASHBOARD_MENU_ID);
  const hasDashboardItem = items.some((item) => item.key === DASHBOARD_MENU_ID);
  const dashboardItem = dashboardNode && !hasDashboardItem ? toBreadcrumbItem(dashboardNode) : null;
  if (dashboardItem) {
    items.unshift(dashboardItem);
  }

  const routeBreadcrumb = queryBreadcrumb(route.meta.breadcrumbQueryItems) || normalizeRouteBreadcrumb(route.meta.breadcrumbItems);
  if (routeBreadcrumb.items.length) {
    return routeBreadcrumb.replaceBase ? routeBreadcrumb.items : [...items, ...routeBreadcrumb.items];
  }

  const breadcrumbTitle = translatedRouteTitle(route.meta.breadcrumbTitleKey, route.meta.breadcrumbTitle);
  if (breadcrumbTitle && (!items.length || items[items.length - 1].label !== breadcrumbTitle)) {
    return [
      ...items,
      {
        key: `${String(route.name || route.path)}:current`,
        label: breadcrumbTitle,
        to: null,
        current: true,
      },
    ];
  }

  if (items.length) {
    const lastIndex = items.length - 1;
    items[lastIndex] = { ...items[lastIndex], to: null, current: true };
    return items;
  }

  const routeTitle = translatedRouteTitle(route.meta.titleKey, route.meta.title);
  return routeTitle
    ? [
        {
          key: String(route.name || route.path),
          label: routeTitle,
          to: null,
          current: true,
        },
      ]
    : [];
});

function translatedContextLabel(item: { label: string; titleKey?: string; path?: string; query?: Record<string, string> }): string {
  if (item.titleKey) return t(item.titleKey);
  const target = breadcrumbItemTarget(item);
  if (!target) return item.label;
  const resolved = router.resolve(target);
  const configured = normalizeRouteBreadcrumb(resolved.meta.breadcrumbItems);
  const configuredKey = configured.items[configured.items.length - 1]?.key;
  if (configuredKey) return configured.items[configured.items.length - 1].label;
  return translatedRouteTitle(resolved.meta.breadcrumbTitleKey || resolved.meta.titleKey, item.label);
}

function normalizeRouteTitle(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function translatedRouteTitle(key: unknown, fallback: unknown): string {
  return typeof key === 'string' && key.trim() ? t(key) : normalizeRouteTitle(fallback);
}

function normalizeRouteBreadcrumb(value: unknown): ResolvedRouteBreadcrumb {
  if (Array.isArray(value)) {
    return { items: normalizeRouteBreadcrumbItems(value), replaceBase: false };
  }
  if (!value || typeof value !== 'object') {
    return { items: [], replaceBase: false };
  }
  const config = value as RouteBreadcrumbConfig;
  return {
    items: Array.isArray(config.items) ? normalizeRouteBreadcrumbItems(config.items) : [],
    replaceBase: Boolean(config.replaceBase),
  };
}

function normalizeRouteBreadcrumbItems(value: unknown[]): BreadcrumbItem[] {
  return value
    .map((item, index) => toConfiguredBreadcrumbItem(item, index === value.length - 1))
    .filter((item): item is BreadcrumbItem => Boolean(item));
}

function queryBreadcrumb(value: unknown): ResolvedRouteBreadcrumb | null {
  if (!value || typeof value !== 'object') return null;
  const queryItems = value as RouteBreadcrumbQueryItems;
  for (const [queryKey, titleByValue] of Object.entries(queryItems)) {
    const queryValue = routeQueryText(route.query[queryKey]);
    const configuredItems = queryValue ? titleByValue[queryValue] : undefined;
    if (configuredItems) {
      return normalizeRouteBreadcrumb(configuredItems);
    }
  }
  return null;
}

function toConfiguredBreadcrumbItem(value: unknown, current: boolean): BreadcrumbItem | null {
  if (!value || typeof value !== 'object') return null;
  const item = value as RouteBreadcrumbItem;
  const label = translatedRouteTitle(item.titleKey, item.title || item.label);
  if (!label) return null;
  return {
    key: `${String(route.name || route.path)}:${label}`,
    label,
    to: current ? null : resolveBreadcrumbTarget(item),
    current,
  };
}

function toBreadcrumbItem(node: SystemMenuNode): BreadcrumbItem | null {
  const path = node.path || firstMenuPath(node.children || []);
  if (!node.name) return null;
  return {
    key: node.id,
    label: menuLabel(node.id, node.name, t),
    to: path,
    current: false,
  };
}

function resolveBreadcrumbTarget(item: RouteBreadcrumbItem): RouteLocationRaw | null {
  if (!item.path) return null;
  const path = fillPathParams(item.path);
  if (!path) return null;
  return item.query ? { path, query: item.query } : path;
}

function fillPathParams(path: string): string | null {
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

function handleBreadcrumbClick(item: BreadcrumbItem): void {
  if (item.current || !item.to) return;
  router.push(item.to);
}
</script>

<template>
  <nav v-if="breadcrumbItems.length" class="app-breadcrumb" :aria-label="t('common.navigation.breadcrumb')">
    <span class="app-breadcrumb__home-icon" aria-hidden="true">
      <HomeIcon />
    </span>
    <t-breadcrumb class="app-breadcrumb__trail" separator="/">
      <t-breadcrumb-item v-for="item in breadcrumbItems" :key="item.key" @click="handleBreadcrumbClick(item)">
        <span
          class="app-breadcrumb__label"
          :class="{ 'app-breadcrumb__label--link': item.to && !item.current, 'app-breadcrumb__label--current': item.current }"
          :aria-current="item.current ? 'page' : undefined"
        >
          {{ item.label }}
        </span>
      </t-breadcrumb-item>
    </t-breadcrumb>
  </nav>
</template>

<style scoped>
.app-breadcrumb {
  display: flex;
  height: 42px;
  flex: 0 0 42px;
  align-items: center;
  gap: 10px;
  border-bottom: 1px solid #e6edf6;
  background: #fff;
  padding: 0 24px;
}

.app-breadcrumb__home-icon {
  display: grid;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  place-items: center;
  border-radius: 6px;
  background: #eaf2ff;
  color: #1d4ed8;
  font-size: 14px;
}

.app-breadcrumb__home-icon :deep(svg) {
  width: 14px;
  height: 14px;
}

.app-breadcrumb__trail {
  min-width: 0;
}

.app-breadcrumb__label {
  display: inline-block;
  max-width: 180px;
  overflow: hidden;
  color: #64748b;
  font-size: 13px;
  line-height: 20px;
  text-overflow: ellipsis;
  vertical-align: top;
  white-space: nowrap;
}

.app-breadcrumb__label--link {
  color: #2563eb;
  cursor: pointer;
}

.app-breadcrumb__label--link:hover {
  color: #1d4ed8;
}

.app-breadcrumb__label--current {
  color: #0f172a;
  cursor: default;
  font-weight: 600;
}
</style>
