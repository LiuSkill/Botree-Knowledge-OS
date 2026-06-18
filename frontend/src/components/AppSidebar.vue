<!--
  AppSidebar

  负责：
  1. 展示左侧主菜单
  2. 与 Vue Router 保持选中状态
  3. 还原原型后台导航结构
-->
<script setup lang="ts">
import { computed, type Component } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  BookIcon,
  ChatBubbleIcon,
  ChatIcon,
  CheckCircleIcon,
  FolderIcon,
  HomeIcon,
  LockOnIcon,
  SettingIcon,
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
};

const iconByMenuId: Record<string, Component> = {
  dashboard: HomeIcon,
  knowledge: BookIcon,
  project: FolderIcon,
  authorization: LockOnIcon,
  review: CheckCircleIcon,
  'ai:project-chat': ChatBubbleIcon,
  'ai:base-chat': ChatIcon,
  system: SettingIcon,
};

const visibleMenuItems = computed(() => {
  /**
   * 左侧菜单完全由后端菜单树和登录态权限生成。
   */
  return authStore.authorizedMenuTree
    .map((node) => toMenuItem(node))
    .filter((item): item is MenuItem => Boolean(item));
});

const activePath = computed(() => {
  /**
   * 根据当前路由高亮主菜单。
   */
  const menuId = route.meta.menuId as string | undefined;
  const matched = visibleMenuItems.value.find((item) => (menuId ? item.menuIds.includes(menuId) : route.path.startsWith(item.path)));
  return matched?.path || visibleMenuItems.value[0]?.path || '/';
});

function navigate(path: string): void {
  /**
   * 跳转主菜单路径。
   */
  router.push(path);
}

function toMenuItem(node: SystemMenuNode): MenuItem | null {
  const path = node.path || firstMenuPath([node]);
  if (!path) return null;
  return {
    id: node.id,
    path,
    label: node.name,
    icon: iconByMenuId[node.id] || SettingIcon,
    menuIds: collectMenuIds(node),
  };
}

function collectMenuIds(node: SystemMenuNode): string[] {
  return [node.id, ...(node.children || []).flatMap((child) => collectMenuIds(child))];
}
</script>

<template>
  <aside class="app-sidebar">
    <nav class="menu">
      <t-button
        v-for="item in visibleMenuItems"
        :key="item.path"
        class="menu-item"
        :class="{ active: activePath === item.path }"
        block
        variant="text"
        @click="navigate(item.path)"
      >
        <span class="menu-icon">
          <component :is="item.icon" />
        </span>
        <span>{{ item.label }}</span>
      </t-button>
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

.menu-icon {
  display: grid;
  width: 24px;
  height: 24px;
  flex: 0 0 24px;
  place-items: center;
  border-radius: 6px;
  background: #eef2ff;
  color: #2563eb;
  font-size: 16px;
}

.menu-icon :deep(svg) {
  width: 16px;
  height: 16px;
}

.menu-item.active .menu-icon {
  background: #dbeafe;
  color: #1d4ed8;
}

.sidebar-bottom {
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 8px;
  background: #f3f7ff;
  color: #2563eb;
  padding: 10px;
  font-size: 12px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: #10b981;
}
</style>
