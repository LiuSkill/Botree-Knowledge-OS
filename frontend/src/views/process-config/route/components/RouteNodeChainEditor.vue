<script setup lang="ts">
import { AddIcon, ArrowDownIcon, ArrowUpIcon, DeleteIcon } from 'tdesign-icons-vue-next';
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';

import type { ProcessNodeItem } from '@/views/process-config/node/types';
import { processNodeTypeLocaleKey, processStatusLocaleKey } from '@/views/process-config/i18n';
import type { RouteEditableNode } from '@/views/process-config/route/types';
import type { ProcessLibraryStatus } from '@/views/process-config/types';

interface EditableRouteNodeRow extends RouteEditableNode {
  local_key: string;
}

const props = withDefaults(
  defineProps<{
    modelValue: RouteEditableNode[];
    nodeOptions: ProcessNodeItem[];
    disabled?: boolean;
  }>(),
  {
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: RouteEditableNode[]];
}>();

const { t } = useI18n();
const rows = ref<EditableRouteNodeRow[]>([]);
let rowSeed = 0;

const columns = computed(() => [
  { colKey: 'node_id', title: t('process.entity.nodes'), minWidth: 240 },
  { colKey: 'node_type', title: t('process.node.field.nodeType'), width: 120 },
  { colKey: 'status', title: t('common.field.status'), width: 100, align: 'center' as const },
  { colKey: 'version', title: t('common.field.version'), width: 110 },
  { colKey: 'node_params_json', title: t('process.route.field.nodeParamsJson'), minWidth: 220 },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 180 },
  { colKey: 'operation', title: t('common.field.operation'), width: 122, align: 'center' as const },
]);

const optionMap = computed(() => {
  const map = new Map<number, ProcessNodeItem>();
  props.nodeOptions.forEach((item) => map.set(item.id, item));
  return map;
});

watch(
  () => props.modelValue,
  (value) => {
    rows.value = (value || []).map((item, index) => ({
      local_key: item.local_key || `route-node-${Date.now()}-${rowSeed++}`,
      route_node_id: item.route_node_id,
      node_id: item.node_id,
      sort_order: index + 1,
      node_params_json: item.node_params_json || '',
      remark: item.remark || '',
    }));
  },
  { immediate: true },
);

function createRow(): EditableRouteNodeRow {
  return {
    local_key: `route-node-${Date.now()}-${rowSeed++}`,
    node_id: null,
    sort_order: rows.value.length + 1,
    node_params_json: '',
    remark: '',
  };
}

function addRow(): void {
  rows.value = [...rows.value, createRow()];
  emitRows();
}

function removeRow(index: number): void {
  rows.value = rows.value.filter((_, currentIndex) => currentIndex !== index);
  reindexRows();
  emitRows();
}

function moveRowUp(index: number): void {
  if (index <= 0) return;
  const nextRows = [...rows.value];
  [nextRows[index - 1], nextRows[index]] = [nextRows[index], nextRows[index - 1]];
  rows.value = nextRows;
  reindexRows();
  emitRows();
}

function moveRowDown(index: number): void {
  if (index >= rows.value.length - 1) return;
  const nextRows = [...rows.value];
  [nextRows[index], nextRows[index + 1]] = [nextRows[index + 1], nextRows[index]];
  rows.value = nextRows;
  reindexRows();
  emitRows();
}

function updateField(row: EditableRouteNodeRow, key: keyof EditableRouteNodeRow, value: string | number | null | undefined): void {
  row[key] = value as never;
  emitRows();
}

function reindexRows(): void {
  rows.value = rows.value.map((row, index) => ({
    ...row,
    sort_order: index + 1,
  }));
}

function emitRows(): void {
  emit(
    'update:modelValue',
    rows.value.map((row, index) => ({
      local_key: row.local_key,
      route_node_id: row.route_node_id,
      node_id: row.node_id,
      sort_order: index + 1,
      node_params_json: normalizeOptionalText(row.node_params_json),
      remark: normalizeOptionalText(row.remark),
    })),
  );
}

function normalizeOptionalText(value?: string | null): string | null {
  const text = value?.trim();
  return text || null;
}

function nodeOptionLabel(option: ProcessNodeItem): string {
  const typeLabel = nodeTypeLabelByValue(option.node_type);
  return `${option.code} / ${option.name} / ${typeLabel}`;
}

function statusLabel(status: ProcessLibraryStatus): string {
  return t(processStatusLocaleKey(status));
}

function statusTheme(status: ProcessLibraryStatus): 'success' | 'warning' | 'default' {
  const themes: Record<ProcessLibraryStatus, 'success' | 'warning' | 'default'> = {
    enabled: 'success',
    draft: 'warning',
    disabled: 'default',
  };
  return themes[status] || 'default';
}

function nodeTypeLabel(nodeId: number | null): string {
  if (!nodeId) return '-';
  const option = optionMap.value.get(nodeId);
  return nodeTypeLabelByValue(option?.node_type);
}

function nodeTypeLabelByValue(value?: string | null): string {
  if (!value) return '-';
  const key = processNodeTypeLocaleKey(value);
  return key ? t(key) : value;
}

function nodeStatus(nodeId: number | null): ProcessLibraryStatus | null {
  if (!nodeId) return null;
  return optionMap.value.get(nodeId)?.status || null;
}

function nodeVersion(nodeId: number | null): string {
  if (!nodeId) return '-';
  return optionMap.value.get(nodeId)?.version || '-';
}
</script>

<template>
  <div class="route-chain-editor">
    <div class="route-chain-editor__toolbar">
      <t-button size="small" variant="outline" :disabled="disabled" @click="addRow">
        <template #icon><AddIcon /></template>
        {{ t('process.route.action.addNode') }}
      </t-button>
    </div>

    <div class="route-chain-editor__table">
      <t-table
        row-key="local_key"
        bordered
        table-layout="fixed"
        size="small"
        :columns="columns"
        :data="rows"
        :empty="t('process.route.empty.chain')"
      >
        <template #node_id="{ row }">
          <t-select
            filterable
            clearable
            :disabled="disabled"
            :model-value="row.node_id"
            :placeholder="t('process.route.placeholder.node')"
            @update:model-value="(value: number | null) => updateField(row, 'node_id', value ?? null)"
          >
            <t-option v-for="option in nodeOptions" :key="option.id" :label="nodeOptionLabel(option)" :value="option.id" />
          </t-select>
        </template>
        <template #node_type="{ row }">
          {{ nodeTypeLabel(row.node_id) }}
        </template>
        <template #status="{ row }">
          <t-tag v-if="nodeStatus(row.node_id)" size="small" variant="light" :theme="statusTheme(nodeStatus(row.node_id) as ProcessLibraryStatus)">
            {{ statusLabel(nodeStatus(row.node_id) as ProcessLibraryStatus) }}
          </t-tag>
          <span v-else>-</span>
        </template>
        <template #version="{ row }">
          {{ nodeVersion(row.node_id) }}
        </template>
        <template #node_params_json="{ row }">
          <t-input
            clearable
            :disabled="disabled"
            :model-value="String(row.node_params_json || '')"
            :placeholder="t('process.route.placeholder.nodeParamsJson')"
            @update:model-value="(value: string) => updateField(row, 'node_params_json', value)"
          />
        </template>
        <template #remark="{ row }">
          <t-input
            clearable
            :disabled="disabled"
            :model-value="String(row.remark || '')"
            :placeholder="t('process.node.placeholder.remark')"
            @update:model-value="(value: string) => updateField(row, 'remark', value)"
          />
        </template>
        <template #operation="{ rowIndex }">
          <t-space size="4px">
            <t-button shape="square" size="small" variant="text" :disabled="disabled || rowIndex === 0" @click="moveRowUp(rowIndex)">
              <template #icon><ArrowUpIcon /></template>
            </t-button>
            <t-button
              shape="square"
              size="small"
              variant="text"
              :disabled="disabled || rowIndex === rows.length - 1"
              @click="moveRowDown(rowIndex)"
            >
              <template #icon><ArrowDownIcon /></template>
            </t-button>
            <t-button shape="square" size="small" theme="danger" variant="text" :disabled="disabled" @click="removeRow(rowIndex)">
              <template #icon><DeleteIcon /></template>
            </t-button>
          </t-space>
        </template>
      </t-table>
    </div>
  </div>
</template>

<style scoped>
.route-chain-editor {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.route-chain-editor__toolbar {
  display: flex;
  justify-content: flex-end;
}

.route-chain-editor__table {
  min-width: 0;
  overflow-x: auto;
}

.route-chain-editor__table :deep(.t-table) {
  min-width: 980px;
}
</style>
