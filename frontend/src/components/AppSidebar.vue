<!--
  AppSidebar

  负责根据后端授权菜单树渲染左侧导航，并与 Vue Router 保持选中状态一致。
-->
<script setup lang="ts">
import { computed, ref, watch, type Component } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  BookOpenIcon,
  ChatBubbleIcon,
  ChatBubbleHelpIcon,
  ChatIcon,
  CheckCircleIcon,
  ChevronDownSIcon,
  ChevronRightSIcon,
  FileSearchIcon,
  FolderOpenIcon,
  HomeIcon,
  HistoryIcon,
  SecuredIcon,
  ServerIcon,
  Setting1Icon,
  SettingIcon,
  TableIcon,
  UserIcon,
} from 'tdesign-icons-vue-next';

import { useAuthStore } from '@/stores/auth';
import type { SystemMenuNode } from '@/types/api';
import { firstMenuPath } from '@/utils/rbacMenus';

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

type MenuItem = {
  id: string;
  path: string;
  label: string;
  icon: Component;
  menuIds: string[];
  children: MenuItem[];
};

const iconByMenuId: Record<string, Component> = {
  dashboard: HomeIcon,
  knowledge: BookOpenIcon,
  project: FolderOpenIcon,
  authorization: SecuredIcon,
  review: CheckCircleIcon,
  ai: ChatBubbleHelpIcon,
  'ai:project-chat': ChatBubbleIcon,
  'ai:base-chat': ChatIcon,
  system: Setting1Icon,
  'system:user': UserIcon,
  'system:permission': TableIcon,
  'system:model-config': ServerIcon,
  'system:operation-log': HistoryIcon,
  'system:qa-audit': FileSearchIcon,
};

const expandedMenuIds = ref<string[]>([]);

const visibleMenuItems = computed(() => {
  return authStore.authorizedMenuTree
    .map((node) => toMenuItem(node))
    .filter((item): item is MenuItem => Boolean(item));
});

const activePath = computed(() => {
  const matched = findActiveMenuItem(visibleMenuItems.value);
  return matched?.path || visibleMenuItems.value[0]?.path || '/';
});

watch(
  () => menuTreeSignature(visibleMenuItems.value),
  () => {
    expandedMenuIds.value = collectExpandableMenuIds(visibleMenuItems.value);
  },
  { immediate: true },
);

watch(
  () => route.meta.menuId,
  () => {
    const activeParentIds = collectActiveParentIds(visibleMenuItems.value);
    if (!activeParentIds.length) return;
    expandedMenuIds.value = Array.from(new Set([...expandedMenuIds.value, ...activeParentIds]));
  },
  { immediate: true },
);

function navigate(path: string): void {
  router.push(path);
}

function handleMenuClick(item: MenuItem): void {
  if (item.children.length) {
    expandMenu(item.id);
  }
  navigate(item.path);
}

function toggleMenu(item: MenuItem): void {
  if (isExpanded(item) && !isActiveBranch(item)) {
    expandedMenuIds.value = expandedMenuIds.value.filter((id) => id !== item.id);
    return;
  }
  expandMenu(item.id);
}

function expandMenu(menuId: string): void {
  if (!expandedMenuIds.value.includes(menuId)) {
    expandedMenuIds.value = [...expandedMenuIds.value, menuId];
  }
}

function toMenuItem(node: SystemMenuNode): MenuItem | null {
  const children = (node.children || [])
    .map((child) => toMenuItem(child))
    .filter((item): item is MenuItem => Boolean(item));
  const path = children.length ? firstMenuPath(node.children || []) : node.path || firstMenuPath([node]);
  if (!path) return null;
  return {
    id: node.id,
    path,
    label: node.name,
    icon: iconByMenuId[node.id] || SettingIcon,
    menuIds: collectMenuIds(node),
    children,
  };
}

function collectMenuIds(node: SystemMenuNode): string[] {
  return [node.id, ...(node.children || []).flatMap((child) => collectMenuIds(child))];
}

function collectExpandableMenuIds(items: MenuItem[]): string[] {
  return items.flatMap((item) => (item.children.length ? [item.id, ...collectExpandableMenuIds(item.children)] : []));
}

function menuTreeSignature(items: MenuItem[]): string {
  return items.map((item) => `${item.id}[${menuTreeSignature(item.children)}]`).join('|');
}

function findActiveMenuItem(items: MenuItem[]): MenuItem | null {
  const menuId = route.meta.menuId as string | undefined;
  for (const item of items) {
    if (menuId ? item.menuIds.includes(menuId) : route.path.startsWith(item.path)) {
      return findActiveMenuItem(item.children) || item;
    }
  }
  return null;
}

function collectActiveParentIds(items: MenuItem[]): string[] {
  return items.flatMap((item) => {
    if (!item.children.length || !isActiveBranch(item)) return [];
    return [item.id, ...collectActiveParentIds(item.children)];
  });
}

function isExpanded(item: MenuItem): boolean {
  return item.children.length > 0 && expandedMenuIds.value.includes(item.id);
}

function isActive(item: MenuItem): boolean {
  return activePath.value === item.path;
}

function isActiveBranch(item: MenuItem): boolean {
  const menuId = route.meta.menuId as string | undefined;
  return menuId ? item.menuIds.includes(menuId) : route.path.startsWith(item.path);
}
</script>

<template>
  <aside class="app-sidebar">
    <nav class="menu">
      <template v-for="item in visibleMenuItems" :key="item.id">
        <t-button
          class="menu-item menu-item-level-1"
          :class="{ active: isActive(item) && !item.children.length, 'active-branch': isActiveBranch(item), expanded: isExpanded(item) }"
          block
          variant="text"
          @click="handleMenuClick(item)"
        >
          <span class="menu-icon">
            <component :is="item.icon" />
          </span>
          <span class="menu-label">{{ item.label }}</span>
          <span v-if="item.children.length" class="menu-arrow" @click.stop="toggleMenu(item)">
            <ChevronDownSIcon v-if="isExpanded(item)" />
            <ChevronRightSIcon v-else />
          </span>
        </t-button>

        <div v-if="item.children.length && isExpanded(item)" class="submenu">
          <t-button
            v-for="child in item.children"
            :key="child.id"
            class="menu-item menu-item-level-2"
            :class="{ active: isActive(child), 'active-branch': isActiveBranch(child) }"
            block
            variant="text"
            @click="navigate(child.path)"
          >
            <span class="menu-icon">
              <component :is="child.icon" />
            </span>
            <span class="menu-label">{{ child.label }}</span>
          </t-button>
        </div>
      </template>
    </nav>
  </aside>
</template>

<style scoped>
.app-sidebar {
  position: fixed;
  top: 64px;
  bottom: 0;
  left: 0;
  z-index: 10;
  display: flex;
  width: 240px;
  flex-direction: column;
  justify-content: space-between;
  border-right: 1px solid #e5e7eb;
  background: #fff;
  padding: 16px 12px;
}

.menu {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 6px;
  overflow: auto;
}

.menu-item {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  gap: 10px;
  width: 100%;
  height: 42px;
  border-radius: 8px;
  color: #4b5563;
  font-size: 14px;
  text-align: left;
}

.menu-item :deep(.t-button__text) {
  display: flex;
  width: 100%;
  align-items: center;
  gap: 10px;
}

.menu-item.active {
  background: #eaf2ff;
  color: #1d4ed8;
  font-weight: 700;
}

.menu-item.active-branch:not(.active) {
  background: #f8fbff;
  color: #1d4ed8;
  font-weight: 600;
}

.menu-label {
  min-width: 0;
  flex: 1 1 auto;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.menu-arrow {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  place-items: center;
  border-radius: 4px;
  color: #94a3b8;
}

.menu-arrow:hover {
  background: #edf4ff;
  color: #1d4ed8;
}

.submenu {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin: 0 0 4px 12px;
  border-left: 1px solid #e5edf8;
  padding-left: 10px;
}

.menu-item-level-2 {
  height: 36px;
  border-radius: 7px;
  font-size: 13px;
}

.menu-icon {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  place-items: center;
  color: #64748b;
  font-size: 16px;
}

.menu-icon :deep(svg) {
  width: 16px;
  height: 16px;
}

.menu-item.active .menu-icon {
  color: #1d4ed8;
}

.menu-item.active-branch:not(.active) .menu-icon {
  color: #1d4ed8;
}

.menu-item-level-2 .menu-icon {
  width: 16px;
  height: 16px;
  flex-basis: 16px;
  color: #94a3b8;
  font-size: 14px;
}

.menu-item-level-2 .menu-icon :deep(svg) {
  width: 14px;
  height: 14px;
}
</style>
