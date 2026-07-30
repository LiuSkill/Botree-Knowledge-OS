<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';

import { formatDateTime } from '@/utils/format';
import { type ProcessLibraryOptionItem, type ProcessNodeDetail, type ProcessNodeType } from '@/views/process-config/node/types';
import { processNodeTypeLocaleKey, processStatusLocaleKey } from '@/views/process-config/i18n';
import { processUnitLabel, type ProcessLibraryStatus } from '@/views/process-config/types';

type TagTheme = 'default' | 'success' | 'warning';

const props = withDefaults(
  defineProps<{
    node?: ProcessNodeDetail | null;
    loading?: boolean;
    materialOptions: ProcessLibraryOptionItem[];
    productOptions: ProcessLibraryOptionItem[];
    consumableOptions: ProcessLibraryOptionItem[];
    publicServiceOptions: ProcessLibraryOptionItem[];
  }>(),
  {
    node: null,
    loading: false,
  },
);

const { t } = useI18n();
const materialColumns = computed(() => [
  { colKey: 'material', title: t('process.node.field.inputMaterial'), minWidth: 200 },
  { colKey: 'amount_per_ton', title: t('process.node.field.amountPerTon'), width: 110 },
  { colKey: 'unit', title: t('process.field.unit'), width: 90 },
]);

const consumableColumns = computed(() => [
  { colKey: 'consumable', title: t('process.node.field.consumable'), minWidth: 200 },
  { colKey: 'amount_per_ton', title: t('process.node.field.amountPerTon'), width: 110 },
  { colKey: 'unit', title: t('process.field.unit'), width: 90 },
]);

const publicServiceColumns = computed(() => [
  { colKey: 'public_service', title: t('process.node.field.publicService'), minWidth: 200 },
  { colKey: 'amount_per_ton', title: t('process.node.field.amountPerTon'), width: 110 },
  { colKey: 'unit', title: t('process.field.unit'), width: 90 },
]);

const equipmentColumns = computed(() => [
  { colKey: 'equipment_name', title: t('process.node.field.equipmentFacility'), minWidth: 160 },
]);

const outputColumns = computed(() => [
  { colKey: 'product', title: t('process.node.field.outputProduct'), minWidth: 200 },
  { colKey: 'output_per_ton', title: t('process.node.field.outputAmount'), width: 110 },
  { colKey: 'unit', title: t('process.field.unit'), width: 90 },
  { colKey: 'is_main_product', title: t('process.node.field.mainProduct'), width: 80, align: 'center' as const },
]);

const nodeTypeText = computed(() => (props.node ? nodeTypeLabel(props.node.node_type) : '-'));

function statusLabel(status: ProcessLibraryStatus): string {
  return t(processStatusLocaleKey(status));
}

function statusTheme(status: ProcessLibraryStatus): TagTheme {
  const themes: Record<ProcessLibraryStatus, TagTheme> = {
    enabled: 'success',
    draft: 'warning',
    disabled: 'default',
  };
  return themes[status] || 'default';
}

function nodeTypeLabel(value: ProcessNodeType): string {
  const key = processNodeTypeLocaleKey(value);
  return key ? t(key) : value;
}

function optionLabel(options: ProcessLibraryOptionItem[], id: number): string {
  const option = options.find((item) => item.id === id);
  return option ? `${option.code} / ${option.name}` : `#${id}`;
}
</script>

<template>
  <div class="route-node-detail-panel">
    <t-loading :loading="loading">
      <t-empty v-if="!node" :description="t('process.route.empty.nodeDetail')" />
      <div v-else class="route-node-detail-panel__content">
        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">{{ t('process.node.section.baseInfo') }}</div>
          <t-descriptions bordered :column="2" size="small">
            <t-descriptions-item :label="t('process.node.field.nodeCode')">{{ node.code }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.nodeName')">{{ node.name }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.nodeType')">{{ nodeTypeText }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.version')">{{ node.version }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.staff')">{{ node.staff }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.area')">{{ node.area }}</t-descriptions-item>
            <t-descriptions-item :label="t('common.field.status')">
              <t-tag size="small" variant="light" :theme="statusTheme(node.status)">{{ statusLabel(node.status) }}</t-tag>
            </t-descriptions-item>
            <t-descriptions-item :label="t('process.field.sort')">{{ node.sort_order }}</t-descriptions-item>
            <t-descriptions-item :label="t('common.field.createdAt')">{{ formatDateTime(node.created_at) }}</t-descriptions-item>
            <t-descriptions-item :label="t('common.field.updatedAt')">{{ formatDateTime(node.updated_at) }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.field.description')">{{ node.description || '-' }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.field.remark')">{{ node.remark || '-' }}</t-descriptions-item>
          </t-descriptions>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">{{ t('process.node.section.inputMaterials') }}</div>
          <div class="route-node-detail-panel__table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="materialColumns" :data="node.material_inputs" :empty="t('process.node.empty.material')">
              <template #material="{ row }">{{ optionLabel(materialOptions, row.material_id) }}</template>
              <template #unit="{ row }">{{ processUnitLabel(row.unit) }}</template>
            </t-table>
          </div>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">{{ t('process.node.section.consumables') }}</div>
          <div class="route-node-detail-panel__table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="consumableColumns" :data="node.consumables" :empty="t('process.node.empty.consumables')">
              <template #consumable="{ row }">{{ optionLabel(consumableOptions, row.consumable_id) }}</template>
              <template #unit="{ row }">{{ processUnitLabel(row.unit) }}</template>
            </t-table>
          </div>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">{{ t('process.node.section.publicServices') }}</div>
          <div class="route-node-detail-panel__table">
            <t-table
              row-key="id"
              size="small"
              bordered
              table-layout="fixed"
              :columns="publicServiceColumns"
              :data="node.public_services"
              :empty="t('process.node.empty.publicServices')"
            >
              <template #public_service="{ row }">{{ optionLabel(publicServiceOptions, row.public_service_id) }}</template>
              <template #unit="{ row }">{{ processUnitLabel(row.unit) }}</template>
            </t-table>
          </div>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">{{ t('process.node.section.equipment') }}</div>
          <div class="route-node-detail-panel__table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="equipmentColumns" :data="node.equipment" :empty="t('process.node.empty.equipment')">
              <template #equipment_type="{ row }">{{ row.equipment_type || '-' }}</template>
            </t-table>
          </div>
        </section>
      </div>
    </t-loading>
  </div>
</template>

<style scoped>
.route-node-detail-panel {
  min-width: 0;
}

.route-node-detail-panel__content {
  display: grid;
  gap: 16px;
}

.route-node-detail-panel__section {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
}

.route-node-detail-panel__section-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
}

.route-node-detail-panel__table {
  min-width: 0;
  overflow-x: auto;
}

.route-node-detail-panel__table :deep(.t-table) {
  min-width: 680px;
}
</style>
