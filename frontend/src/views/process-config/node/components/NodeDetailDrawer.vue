<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';

import { processFormulaTypeLocaleKey, processNodeTypeLocaleKey, processStatusLocaleKey } from '@/views/process-config/i18n';
import { processUnitLabel, type ProcessLibraryStatus } from '@/views/process-config/types';
import type { ProcessLibraryOptionItem, ProcessNodeDetail, ProcessNodeType } from '@/views/process-config/node/types';
import { formatDateTime } from '@/utils/format';

type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

const props = withDefaults(
  defineProps<{
    visible: boolean;
    node?: ProcessNodeDetail | null;
    loading?: boolean;
    materialOptions: ProcessLibraryOptionItem[];
    productOptions: ProcessLibraryOptionItem[];
    consumableOptions: ProcessLibraryOptionItem[];
    publicServiceOptions: ProcessLibraryOptionItem[];
    assetOptions: ProcessLibraryOptionItem[];
  }>(),
  {
    node: null,
    loading: false,
  },
);

const emit = defineEmits<{
  'update:visible': [value: boolean];
}>();

const { t } = useI18n();
const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const materialColumns = computed(() => [
  { colKey: 'material', title: t('process.node.field.material'), minWidth: 220 },
  { colKey: 'amount_per_ton', title: t('process.node.field.amountPerTon'), width: 120 },
  { colKey: 'unit', title: t('process.field.unit'), width: 100 },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
]);

const consumableColumns = computed(() => [
  { colKey: 'consumable', title: t('process.node.field.consumable'), minWidth: 220 },
  { colKey: 'amount_per_ton_bm', title: t('process.node.field.bmAmountFactor'), width: 140 },
  { colKey: 'unit', title: t('process.field.unit'), width: 100 },
  { colKey: 'formula_type', title: t('process.node.field.formulaType'), width: 110 },
  { colKey: 'expression', title: t('process.node.field.sourceExpression'), minWidth: 160 },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
]);

const publicServiceColumns = computed(() => [
  { colKey: 'public_service', title: t('process.node.field.publicService'), minWidth: 220 },
  { colKey: 'amount_per_ton_bm', title: t('process.node.field.bmAmountFactor'), width: 140 },
  { colKey: 'unit', title: t('process.field.unit'), width: 100 },
  { colKey: 'formula_type', title: t('process.node.field.formulaType'), width: 110 },
  { colKey: 'expression', title: t('process.node.field.sourceExpression'), minWidth: 160 },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
]);

const equipmentColumns = computed(() => [
  { colKey: 'asset', title: t('process.node.field.equipmentFacility'), minWidth: 220 },
  { colKey: 'quantity', title: t('process.node.field.quantity'), width: 120 },
  { colKey: 'installation_factor', title: t('process.node.field.installationSupportFactor'), width: 120 },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
]);

const outputColumns = computed(() => [
  { colKey: 'product', title: t('process.node.field.product'), minWidth: 220 },
  { colKey: 'output_per_ton', title: t('process.node.field.outputAmount'), width: 120 },
  { colKey: 'output_type', title: t('process.node.field.outputKind'), width: 110 },
  { colKey: 'unit', title: t('process.field.unit'), width: 100 },
  { colKey: 'formula_type', title: t('process.node.field.formulaType'), width: 110 },
  { colKey: 'expression', title: t('process.node.field.sourceExpression'), minWidth: 160 },
  { colKey: 'treatment_cost', title: t('process.node.field.treatmentPrice'), width: 120 },
  { colKey: 'is_main_product', title: t('process.node.field.mainProduct'), width: 90, align: 'center' as const },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
]);

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

function formulaTypeLabel(value: string): string {
  const key = processFormulaTypeLocaleKey(value);
  return key ? t(key) : value;
}

</script>

<template>
  <t-drawer
    v-model:visible="visibleProxy"
    class="node-detail-drawer drawer-scroll"
    destroy-on-close
    :header="t('process.node.title.detail')"
    placement="right"
    size="min(960px, 96vw)"
    :footer="false"
  >
    <t-loading :loading="loading">
      <div v-if="node" class="node-detail">
        <section class="node-detail-section">
          <div class="node-detail-section-title">{{ t('process.node.section.baseInfo') }}</div>
          <t-descriptions bordered :column="2" size="small">
            <t-descriptions-item :label="t('process.node.field.nodeCode')">{{ node.code }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.nodeName')">{{ node.name }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.nodeType')">{{ nodeTypeLabel(node.node_type) }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.node.field.version')">{{ node.version }}</t-descriptions-item>
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

        <section class="node-detail-section">
          <div class="node-detail-section-title">{{ t('process.node.section.inputMaterials') }}</div>
          <div class="node-detail-table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="materialColumns" :data="node.material_inputs" :empty="t('process.node.empty.material')">
              <template #material="{ row }">{{ optionLabel(materialOptions, row.material_id) }}</template>
              <template #unit="{ row }">{{ processUnitLabel(row.unit) }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">{{ t('process.node.section.consumables') }}</div>
          <div class="node-detail-table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="consumableColumns" :data="node.consumables" :empty="t('process.node.empty.consumables')">
              <template #consumable="{ row }">{{ optionLabel(consumableOptions, row.consumable_id) }}</template>
              <template #unit="{ row }">{{ processUnitLabel(row.unit) }}</template>
              <template #formula_type="{ row }">{{ formulaTypeLabel(row.formula_type) }}</template>
              <template #expression="{ row }">{{ row.expression || '-' }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">{{ t('process.node.section.publicServices') }}</div>
          <div class="node-detail-table">
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
              <template #formula_type="{ row }">{{ formulaTypeLabel(row.formula_type) }}</template>
              <template #expression="{ row }">{{ row.expression || '-' }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">{{ t('process.node.section.equipment') }}</div>
          <div class="node-detail-table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="equipmentColumns" :data="node.equipment" :empty="t('process.node.empty.equipment')">
              <template #asset="{ row }">{{ row.asset_id ? optionLabel(assetOptions, row.asset_id) : '-' }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>
      </div>
      <t-empty v-else :description="t('process.node.empty.detail')" />
    </t-loading>
  </t-drawer>
</template>

<style scoped>
.node-detail-drawer :deep(.t-drawer__body) {
  background: #f8fafc;
  padding: 18px;
}

.node-detail {
  display: grid;
  gap: 16px;
}

.node-detail-section {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
}

.node-detail-section-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
}

.node-detail-table {
  min-width: 0;
  overflow-x: auto;
}

.node-detail-table :deep(.t-table) {
  min-width: 720px;
}
</style>
