<script setup lang="ts">
import { computed } from 'vue';

import type { ProcessLibraryStatus } from '@/views/process-config/types';
import type { ProcessLibraryOptionItem, ProcessNodeDetail, ProcessNodeType } from '@/views/process-config/node/types';
import { PROCESS_NODE_TYPE_OPTIONS } from '@/views/process-config/node/types';
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
  }>(),
  {
    node: null,
    loading: false,
  },
);

const emit = defineEmits<{
  'update:visible': [value: boolean];
}>();

const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const materialColumns = [
  { colKey: 'material', title: '原料', minWidth: 220 },
  { colKey: 'amount_per_ton', title: '吨耗', width: 120 },
  { colKey: 'unit', title: '单位', width: 100 },
  { colKey: 'remark', title: '备注', minWidth: 160 },
];

const consumableColumns = [
  { colKey: 'consumable', title: '消耗品', minWidth: 220 },
  { colKey: 'amount_per_ton_bm', title: 'BM 吨耗系数', width: 140 },
  { colKey: 'unit', title: '单位', width: 100 },
  { colKey: 'formula_type', title: '系数类型', width: 110 },
  { colKey: 'expression', title: '来源表达式', minWidth: 160 },
  { colKey: 'remark', title: '备注', minWidth: 160 },
];

const publicServiceColumns = [
  { colKey: 'public_service', title: '公共服务', minWidth: 220 },
  { colKey: 'amount_per_ton_bm', title: 'BM 吨耗系数', width: 140 },
  { colKey: 'unit', title: '单位', width: 100 },
  { colKey: 'formula_type', title: '系数类型', width: 110 },
  { colKey: 'expression', title: '来源表达式', minWidth: 160 },
  { colKey: 'remark', title: '备注', minWidth: 160 },
];

const equipmentColumns = [
  { colKey: 'equipment_name', title: '设备名称', minWidth: 180 },
  { colKey: 'equipment_type', title: '设备类型', width: 140 },
  { colKey: 'quantity', title: '数量', width: 110 },
  { colKey: 'investment_amount', title: '投资额', width: 130 },
  { colKey: 'currency', title: '币种', width: 90 },
  { colKey: 'remark', title: '备注', minWidth: 160 },
];

const outputColumns = [
  { colKey: 'product', title: '产品', minWidth: 220 },
  { colKey: 'output_per_ton', title: '产出量', width: 120 },
  { colKey: 'output_type', title: '产出类型', width: 110 },
  { colKey: 'unit', title: '单位', width: 100 },
  { colKey: 'formula_type', title: '系数类型', width: 110 },
  { colKey: 'expression', title: '来源表达式', minWidth: 160 },
  { colKey: 'treatment_cost', title: '处理单价', width: 120 },
  { colKey: 'is_main_product', title: '主产品', width: 90, align: 'center' },
  { colKey: 'remark', title: '备注', minWidth: 160 },
];

function statusLabel(status: ProcessLibraryStatus): string {
  const labels: Record<ProcessLibraryStatus, string> = {
    enabled: '启用',
    draft: '草稿',
    disabled: '停用',
  };
  return labels[status] || status;
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
  return PROCESS_NODE_TYPE_OPTIONS.find((item) => item.value === value)?.label || value;
}

function optionLabel(options: ProcessLibraryOptionItem[], id: number): string {
  const option = options.find((item) => item.id === id);
  return option ? `${option.code} / ${option.name}` : `#${id}`;
}
</script>

<template>
  <t-drawer
    v-model:visible="visibleProxy"
    class="node-detail-drawer drawer-scroll"
    destroy-on-close
    header="工艺节点详情"
    placement="right"
    size="min(960px, 96vw)"
    :footer="false"
  >
    <t-loading :loading="loading">
      <div v-if="node" class="node-detail">
        <section class="node-detail-section">
          <div class="node-detail-section-title">基础信息</div>
          <t-descriptions bordered :column="2" size="small">
            <t-descriptions-item label="节点编码">{{ node.code }}</t-descriptions-item>
            <t-descriptions-item label="节点名称">{{ node.name }}</t-descriptions-item>
            <t-descriptions-item label="节点类型">{{ nodeTypeLabel(node.node_type) }}</t-descriptions-item>
            <t-descriptions-item label="版本号">{{ node.version }}</t-descriptions-item>
            <t-descriptions-item label="人员">{{ node.staff }}</t-descriptions-item>
            <t-descriptions-item label="占地面积">{{ node.area }}</t-descriptions-item>
            <t-descriptions-item label="状态">
              <t-tag size="small" variant="light" :theme="statusTheme(node.status)">{{ statusLabel(node.status) }}</t-tag>
            </t-descriptions-item>
            <t-descriptions-item label="排序">{{ node.sort_order }}</t-descriptions-item>
            <t-descriptions-item label="创建时间">{{ formatDateTime(node.created_at) }}</t-descriptions-item>
            <t-descriptions-item label="更新时间">{{ formatDateTime(node.updated_at) }}</t-descriptions-item>
            <t-descriptions-item label="描述">{{ node.description || '-' }}</t-descriptions-item>
            <t-descriptions-item label="备注">{{ node.remark || '-' }}</t-descriptions-item>
          </t-descriptions>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">输入原料</div>
          <div class="node-detail-table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="materialColumns" :data="node.material_inputs" empty="暂无输入原料">
              <template #material="{ row }">{{ optionLabel(materialOptions, row.material_id) }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">消耗品</div>
          <div class="node-detail-table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="consumableColumns" :data="node.consumables" empty="暂无消耗品">
              <template #consumable="{ row }">{{ optionLabel(consumableOptions, row.consumable_id) }}</template>
              <template #formula_type="{ row }">{{ row.formula_type === 'expression' ? '导入表达式' : '固定系数' }}</template>
              <template #expression="{ row }">{{ row.expression || '-' }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">公共服务</div>
          <div class="node-detail-table">
            <t-table
              row-key="id"
              size="small"
              bordered
              table-layout="fixed"
              :columns="publicServiceColumns"
              :data="node.public_services"
              empty="暂无公共服务"
            >
              <template #public_service="{ row }">{{ optionLabel(publicServiceOptions, row.public_service_id) }}</template>
              <template #formula_type="{ row }">{{ row.formula_type === 'expression' ? '导入表达式' : '固定系数' }}</template>
              <template #expression="{ row }">{{ row.expression || '-' }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">设备/投资</div>
          <div class="node-detail-table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="equipmentColumns" :data="node.equipment" empty="暂无设备/投资">
              <template #equipment_type="{ row }">{{ row.equipment_type || '-' }}</template>
              <template #investment_amount="{ row }">{{ row.currency }} {{ row.investment_amount }}</template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>

        <section class="node-detail-section">
          <div class="node-detail-section-title">输出产品</div>
          <div class="node-detail-table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="outputColumns" :data="node.outputs" empty="暂无输出产品">
              <template #product="{ row }">{{ optionLabel(productOptions, row.product_id) }}</template>
              <template #formula_type="{ row }">{{ row.formula_type === 'expression' ? '导入表达式' : '固定系数' }}</template>
              <template #expression="{ row }">{{ row.expression || '-' }}</template>
              <template #is_main_product="{ row }">
                <t-tag v-if="row.is_main_product" size="small" theme="success" variant="light">主产品</t-tag>
                <span v-else>-</span>
              </template>
              <template #remark="{ row }">{{ row.remark || '-' }}</template>
            </t-table>
          </div>
        </section>
      </div>
      <t-empty v-else description="暂无节点详情" />
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
