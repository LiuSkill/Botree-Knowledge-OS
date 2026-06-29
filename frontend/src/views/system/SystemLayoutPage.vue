<!--
  System Layout Page

  系统管理二级页面承载布局；具体功能由动态子路由页面提供。
-->
<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

const route = useRoute();

const pageTitle = computed(() => (route.meta.title as string | undefined) || '系统管理');
</script>

<template>
  <div class="page system-page">
    <t-card class="system-workspace">
      <div class="system-workspace-header">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>维护用户、角色权限、模型配置、操作日志与问答审计。</p>
        </div>
      </div>
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
