<script setup lang="ts">
import { computed } from 'vue';

import { formatDateTime } from '@/utils/format';
import { PROCESS_NODE_TYPE_OPTIONS, type ProcessLibraryOptionItem, type ProcessNodeDetail, type ProcessNodeType } from '@/views/process-config/node/types';
import type { ProcessLibraryStatus } from '@/views/process-config/types';

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

const materialColumns = [
  { colKey: 'material', title: '输入原料', minWidth: 200 },
  { colKey: 'amount_per_ton', title: '吨耗', width: 110 },
  { colKey: 'unit', title: '单位', width: 90 },
];

const consumableColumns = [
  { colKey: 'consumable', title: '消耗品', minWidth: 200 },
  { colKey: 'amount_per_ton', title: '吨耗', width: 110 },
  { colKey: 'unit', title: '单位', width: 90 },
];

const publicServiceColumns = [
  { colKey: 'public_service', title: '公共服务', minWidth: 200 },
  { colKey: 'amount_per_ton', title: '吨耗', width: 110 },
  { colKey: 'unit', title: '单位', width: 90 },
];

const equipmentColumns = [
  { colKey: 'equipment_name', title: '设备名称', minWidth: 160 },
  { colKey: 'equipment_type', title: '设备类型', width: 120 },
  { colKey: 'quantity', title: '数量', width: 90 },
  { colKey: 'investment_amount', title: '投资额', width: 120 },
  { colKey: 'currency', title: '币种', width: 80 },
];

const outputColumns = [
  { colKey: 'product', title: '输出产品', minWidth: 200 },
  { colKey: 'output_per_ton', title: '产出量', width: 110 },
  { colKey: 'unit', title: '单位', width: 90 },
  { colKey: 'is_main_product', title: '主产品', width: 80, align: 'center' },
];

const nodeTypeText = computed(() => (props.node ? nodeTypeLabel(props.node.node_type) : '-'));

function statusLabel(status: ProcessLibraryStatus): string {
  return (
    {
      enabled: '启用',
      draft: '草稿',
      disabled: '停用',
    }[status] || status
  );
}

function statusTheme(status: ProcessLibraryStatus): TagTheme {
  return (
    {
      enabled: 'success',
      draft: 'warning',
      disabled: 'default',
    }[status] || 'default'
  );
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
  <div class="route-node-detail-panel">
    <t-loading :loading="loading">
      <t-empty v-if="!node" description="请选择链路中的节点查看详情" />
      <div v-else class="route-node-detail-panel__content">
        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">基础信息</div>
          <t-descriptions bordered :column="2" size="small">
            <t-descriptions-item label="节点编码">{{ node.code }}</t-descriptions-item>
            <t-descriptions-item label="节点名称">{{ node.name }}</t-descriptions-item>
            <t-descriptions-item label="节点类型">{{ nodeTypeText }}</t-descriptions-item>
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

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">输入原料</div>
          <div class="route-node-detail-panel__table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="materialColumns" :data="node.material_inputs" empty="暂无输入原料">
              <template #material="{ row }">{{ optionLabel(materialOptions, row.material_id) }}</template>
            </t-table>
          </div>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">消耗品</div>
          <div class="route-node-detail-panel__table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="consumableColumns" :data="node.consumables" empty="暂无消耗品">
              <template #consumable="{ row }">{{ optionLabel(consumableOptions, row.consumable_id) }}</template>
            </t-table>
          </div>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">公共服务</div>
          <div class="route-node-detail-panel__table">
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
            </t-table>
          </div>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">设备/投资</div>
          <div class="route-node-detail-panel__table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="equipmentColumns" :data="node.equipment" empty="暂无设备/投资">
              <template #equipment_type="{ row }">{{ row.equipment_type || '-' }}</template>
              <template #investment_amount="{ row }">{{ row.currency }} {{ row.investment_amount }}</template>
            </t-table>
          </div>
        </section>

        <section class="route-node-detail-panel__section">
          <div class="route-node-detail-panel__section-title">输出产品</div>
          <div class="route-node-detail-panel__table">
            <t-table row-key="id" size="small" bordered table-layout="fixed" :columns="outputColumns" :data="node.outputs" empty="暂无输出产品">
              <template #product="{ row }">{{ optionLabel(productOptions, row.product_id) }}</template>
              <template #is_main_product="{ row }">
                <t-tag v-if="row.is_main_product" size="small" theme="success" variant="light">主产品</t-tag>
                <span v-else>-</span>
              </template>
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
