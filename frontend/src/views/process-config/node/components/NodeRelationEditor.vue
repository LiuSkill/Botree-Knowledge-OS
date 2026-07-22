<script setup lang="ts">
import { AddIcon, DeleteIcon } from 'tdesign-icons-vue-next';
import { computed, ref, watch } from 'vue';

import type { ProcessLibraryOptionItem } from '@/views/process-config/node/types';

type RelationFieldValue = string | number | boolean | null | undefined;

interface EditableRelationRow {
  _rowKey: string;
  unit: string;
  sort_order: number;
  remark?: string | null;
  is_main_product?: boolean;
  [key: string]: RelationFieldValue;
}

const props = withDefaults(
  defineProps<{
    modelValue: Record<string, unknown>[];
    options: ProcessLibraryOptionItem[];
    idKey: string;
    amountKey: string;
    resourceLabel: string;
    amountLabel: string;
    addLabel: string;
    selectPlaceholder: string;
    showMainProduct?: boolean;
    disabled?: boolean;
  }>(),
  {
    showMainProduct: false,
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>[]];
}>();

const rows = ref<EditableRelationRow[]>([]);
let rowSeed = 0;

const columns = computed(() => {
  const baseColumns = [
    { colKey: 'resource', title: props.resourceLabel, minWidth: 220 },
    { colKey: 'amount', title: props.amountLabel, width: 140 },
    { colKey: 'unit', title: '单位', width: 110 },
  ];
  if (props.showMainProduct) {
    baseColumns.push({ colKey: 'is_main_product', title: '主产品', width: 96 });
  }
  baseColumns.push(
    { colKey: 'remark', title: '备注', minWidth: 160 },
    { colKey: 'operation', title: '操作', width: 72, align: 'center' },
  );
  return baseColumns;
});

watch(
  () => props.modelValue,
  (value) => {
    rows.value = toEditableRows(value);
  },
  { immediate: true },
);

function toEditableRows(value: Record<string, unknown>[] = []): EditableRelationRow[] {
  return value.map((item, index) => ({
    _rowKey: `relation-${Date.now()}-${rowSeed++}`,
    unit: '',
    sort_order: index + 1,
    remark: '',
    is_main_product: false,
    ...item,
  })) as EditableRelationRow[];
}

function createRow(): EditableRelationRow {
  return {
    _rowKey: `relation-${Date.now()}-${rowSeed++}`,
    [props.idKey]: null,
    [props.amountKey]: 0,
    unit: '',
    sort_order: rows.value.length + 1,
    remark: '',
    is_main_product: false,
  };
}

function addRow(): void {
  rows.value = [...rows.value, createRow()];
  emitRows();
}

function removeRow(rowIndex: number): void {
  rows.value = rows.value.filter((_, index) => index !== rowIndex).map((row, index) => ({ ...row, sort_order: index + 1 }));
  emitRows();
}

function getField(row: EditableRelationRow, key: string): RelationFieldValue {
  return row[key];
}

function updateField(row: EditableRelationRow, key: string, value: RelationFieldValue): void {
  row[key] = value;
  if (key === props.idKey) syncUnit(row);
  emitRows();
}

function syncUnit(row: EditableRelationRow): void {
  const optionId = Number(row[props.idKey]);
  const option = props.options.find((item) => item.id === optionId);
  if (option?.unit) row.unit = option.unit;
}

function optionLabel(option: ProcessLibraryOptionItem): string {
  return `${option.code} / ${option.name}${option.unit ? `（${option.unit}）` : ''}`;
}

function emitRows(): void {
  const payload = rows.value.map(({ _rowKey, ...row }) => {
    const result: Record<string, unknown> = { ...row };
    if (!props.showMainProduct) delete result.is_main_product;
    return result;
  });
  emit('update:modelValue', payload);
}
</script>

<template>
  <div class="relation-editor">
    <div class="relation-editor-toolbar">
      <t-button size="small" variant="outline" :disabled="disabled" @click="addRow">
        <template #icon><AddIcon /></template>
        {{ addLabel }}
      </t-button>
    </div>

    <div class="relation-editor-table">
      <t-table
        row-key="_rowKey"
        bordered
        table-layout="fixed"
        size="small"
        :columns="columns"
        :data="rows"
        :empty="`暂无${resourceLabel}配置`"
      >
        <template #resource="{ row }">
          <t-select
            filterable
            clearable
            :disabled="disabled"
            :model-value="getField(row, idKey)"
            :placeholder="selectPlaceholder"
            @update:model-value="(value) => updateField(row, idKey, value as RelationFieldValue)"
          >
            <t-option v-for="option in options" :key="option.id" :label="optionLabel(option)" :value="option.id" />
          </t-select>
        </template>
        <template #amount="{ row }">
          <t-input-number
            :disabled="disabled"
            :min="0"
            :step="0.0001"
            theme="normal"
            :model-value="getField(row, amountKey) as number | string"
            @update:model-value="(value) => updateField(row, amountKey, value as RelationFieldValue)"
          />
        </template>
        <template #unit="{ row }">
          <t-input
            clearable
            :disabled="disabled"
            :model-value="String(row.unit || '')"
            placeholder="单位"
            @update:model-value="(value) => updateField(row, 'unit', value as RelationFieldValue)"
          />
        </template>
        <template #is_main_product="{ row }">
          <t-switch
            :disabled="disabled"
            :model-value="Boolean(row.is_main_product)"
            @update:model-value="(value) => updateField(row, 'is_main_product', value as RelationFieldValue)"
          />
        </template>
        <template #remark="{ row }">
          <t-input
            clearable
            :disabled="disabled"
            :model-value="String(row.remark || '')"
            placeholder="备注"
            @update:model-value="(value) => updateField(row, 'remark', value as RelationFieldValue)"
          />
        </template>
        <template #operation="{ rowIndex }">
          <t-button shape="square" size="small" theme="danger" variant="text" :disabled="disabled" @click="removeRow(rowIndex)">
            <template #icon><DeleteIcon /></template>
          </t-button>
        </template>
      </t-table>
    </div>
  </div>
</template>

<style scoped>
.relation-editor {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.relation-editor-toolbar {
  display: flex;
  justify-content: flex-end;
}

.relation-editor-table {
  min-width: 0;
  overflow-x: auto;
}

.relation-editor-table :deep(.t-table) {
  min-width: 760px;
}
</style>
