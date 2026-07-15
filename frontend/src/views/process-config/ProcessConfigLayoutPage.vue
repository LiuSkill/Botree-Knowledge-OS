<script setup lang="ts">
import { computed } from 'vue';
import { useRoute } from 'vue-router';

import { MENU_PERMISSIONS } from '@/constants/permissions';

const route = useRoute();

const descriptionByMenuId: Record<string, string> = {
  [MENU_PERMISSIONS.PROCESS_CONFIG_MATERIAL]: '维护原料编码、分类、单位、区域单价和启停状态。',
  [MENU_PERMISSIONS.PROCESS_CONFIG_PRODUCT]: '维护产品编码、分类、单位、区域单价和状态配置。',
  [MENU_PERMISSIONS.PROCESS_CONFIG_CONSUMABLE]: '维护消耗品基础信息、区域单价及业务状态。',
  [MENU_PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE]: '维护公共服务项、计量单位、区域价格与使用状态。',
  [MENU_PERMISSIONS.PROCESS_CONFIG_NODE]: '维护工艺节点、物料关系、设备投资和输出产品配置。',
  [MENU_PERMISSIONS.PROCESS_CONFIG_ROUTE]: '维护工艺路线、节点链路、版本快照和路线详情。',
  [MENU_PERMISSIONS.PROCESS_CONFIG_CALCULATOR]: '按原料、目标产品和区域价格匹配路线并完成快速财务测算。',
};

const pageTitle = computed(() => (route.meta.title as string | undefined) || '工艺配置');
const pageDescription = computed(() => {
  const menuId = route.meta.menuId as string | undefined;
  return (menuId && descriptionByMenuId[menuId]) || '维护基础库、工艺节点和工艺路线等工艺配置数据。';
});
</script>

<template>
  <div class="page process-config-page">
    <t-card class="process-config-workspace">
      <div class="process-config-workspace-header">
        <div>
          <h1>{{ pageTitle }}</h1>
          <p>{{ pageDescription }}</p>
        </div>
      </div>
      <div class="process-config-content">
        <router-view />
      </div>
    </t-card>
  </div>
</template>

<style scoped>
.process-config-page {
  height: 100%;
  min-height: 0;
  padding: 22px 24px;
}

.process-config-workspace {
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

.process-config-workspace :deep(.t-card__body) {
  display: flex;
  flex: 1 1 0;
  height: auto;
  min-height: 0;
  flex-direction: column;
  padding: 24px;
  overflow: hidden;
}

.process-config-workspace :deep(> .t-loading__parent) {
  display: flex;
  flex: 1 1 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.process-config-workspace-header {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.process-config-workspace-header h1 {
  margin: 0;
  color: #0f172a;
  font-size: 22px;
  font-weight: 700;
  letter-spacing: 0;
  line-height: 1.35;
}

.process-config-workspace-header p {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 13px;
  line-height: 1.5;
}

.process-config-content {
  display: flex;
  flex: 1 1 0;
  height: 0;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  padding-top: 18px;
}

.process-config-content :deep(.system-card) {
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  min-width: 0;
}
</style>
