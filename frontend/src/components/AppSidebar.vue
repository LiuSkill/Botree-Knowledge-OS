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

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

type MenuItem = {
  path: string;
  label: string;
  icon: Component;
  permission: string;
};

const menuItems: MenuItem[] = [
  { path: '/dashboard', label: '首页', icon: HomeIcon, permission: 'dashboard:view' },
  { path: '/knowledge', label: '知识中心', icon: BookIcon, permission: 'knowledge:view' },
  { path: '/projects', label: '项目中心', icon: FolderIcon, permission: 'project:view' },
  { path: '/authorization', label: '知识授权中心', icon: LockOnIcon, permission: 'authorization:view' },
  { path: '/reviews', label: '审核中心', icon: CheckCircleIcon, permission: 'review:view' },
  { path: '/ai/project-chat', label: '项目问答', icon: ChatBubbleIcon, permission: 'ai:view' },
  { path: '/ai/base-chat', label: '基础问答', icon: ChatIcon, permission: 'ai:view' },
  { path: '/system', label: '系统管理', icon: SettingIcon, permission: 'system:view' },
];

const visibleMenuItems = computed(() => {
  /**
   * 根据 RBAC 权限过滤左侧菜单。
   */
  return menuItems.filter((item) => authStore.hasPermission(item.permission));
});

const activePath = computed(() => {
  /**
   * 根据当前路由高亮主菜单。
   */
  const matched = visibleMenuItems.value.find((item) => route.path.startsWith(item.path));
  return matched?.path || '/dashboard';
});

function navigate(path: string): void {
  /**
   * 跳转主菜单路径。
   */
  router.push(path);
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
