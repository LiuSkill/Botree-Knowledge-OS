<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute } from 'vue-router';

import { MENU_PERMISSIONS } from '@/constants/permissions';

const route = useRoute();
const { t } = useI18n();

const descriptionByMenuId: Record<string, string> = {
  [MENU_PERMISSIONS.PROCESS_CONFIG_MATERIAL]: 'process.layout.description.materials',
  [MENU_PERMISSIONS.PROCESS_CONFIG_PRODUCT]: 'process.layout.description.products',
  [MENU_PERMISSIONS.PROCESS_CONFIG_CONSUMABLE]: 'process.layout.description.consumables',
  [MENU_PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE]: 'process.layout.description.publicServices',
  [MENU_PERMISSIONS.PROCESS_CONFIG_NODE]: 'process.layout.description.nodes',
  [MENU_PERMISSIONS.PROCESS_CONFIG_ROUTE]: 'process.layout.description.routes',
  [MENU_PERMISSIONS.PROCESS_CONFIG_CALCULATOR]: 'process.layout.description.calculator',
};

const pageTitle = computed(() => {
  const titleKey = route.meta.titleKey as string | undefined;
  return titleKey ? t(titleKey) : t('process.module.config');
});
const pageDescription = computed(() => {
  const menuId = route.meta.menuId as string | undefined;
  const descriptionKey = menuId && descriptionByMenuId[menuId];
  return descriptionKey ? t(descriptionKey) : t('process.layout.fallbackDescription');
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
