<!--
  System Layout Page

  负责：
  1. 组织系统管理子页面导航
  2. 承载用户管理、权限矩阵、模型配置、操作日志和问答审计
  3. 保持后台管理区域的统一工作台样式
-->
<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router';
import { computed } from 'vue';

import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const visibleTabs = computed(() => {
  /**
   * 系统管理 Tab 来源于后端授权菜单树，不再维护前端静态 Tab。
   */
  const systemMenu = authStore.authorizedMenuTree.find((item) => item.id === 'system');
  return (systemMenu?.children || [])
    .filter((item) => item.path)
    .map((item) => ({ value: item.path as string, label: item.name }));
});
</script>

<template>
  <div class="page system-page">
    <t-card class="system-workspace">
      <div class="system-workspace-header">
        <div>
          <h1>系统管理</h1>
          <p>维护用户、角色、权限矩阵、模型配置、操作日志与问答审计</p>
        </div>
      </div>
      <t-tabs class="system-top-tabs" :value="route.path" @change="(value) => router.push(String(value))">
        <t-tab-panel v-for="tab in visibleTabs" :key="tab.value" :value="tab.value" :label="tab.label" />
      </t-tabs>
      <div class="system-content">
        <router-view />
      </div>
    </t-card>
  </div>
</template>

<style scoped>
.system-page {
  height: 100%;
  min-height: 0;
  padding: 22px 24px;
}

.system-workspace {
  display: flex;
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  border-color: #dbe3ef;
  border-radius: 6px;
  overflow: hidden;
  box-shadow: 0 14px 32px rgba(15, 23, 42, 0.06);
}

.system-workspace :deep(.t-card__body) {
  display: flex;
  flex: 1 1 0;
  height: auto;
  min-height: 0;
  flex-direction: column;
  padding: 24px;
  overflow: hidden;
}

.system-workspace :deep(> .t-loading__parent) {
  display: flex;
  flex: 1 1 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.system-workspace-header {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.system-workspace-header h1 {
  margin: 0;
  color: #0f172a;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.35;
}

.system-workspace-header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.system-top-tabs {
  flex: 0 0 auto;
  margin-top: 22px;
}

.system-top-tabs :deep(.t-tabs__nav-container) {
  min-height: 40px;
}

.system-top-tabs :deep(.t-tabs__nav-item) {
  min-width: 86px;
  padding: 0 10px;
  color: #475569;
  font-size: 14px;
}

.system-top-tabs :deep(.t-tabs__nav-item.t-is-active) {
  color: #0052d9;
  font-weight: 600;
}

.system-content {
  display: flex;
  flex: 1 1 0;
  height: 0;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  padding-top: 18px;
}

.system-content :deep(.system-card) {
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  min-width: 0;
}
</style>
