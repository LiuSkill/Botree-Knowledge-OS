<script setup lang="ts">
import { AddIcon, DeleteIcon } from 'tdesign-icons-vue-next';
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';

import type { ProcessLibraryOptionItem } from '@/views/process-config/node/types';
import { processFormulaTypeLocaleKey, processOutputTypeLocaleKey } from '@/views/process-config/i18n';
import { PROCESS_UNIT_OPTIONS } from '@/views/process-config/types';

type RelationFieldValue = string | number | boolean | null | undefined;
type RelationColumn = {
  colKey: string;
  title: string;
  width?: number;
  minWidth?: number;
  align?: 'center';
};

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
    showCalculationFields?: boolean;
    showOutputFields?: boolean;
    disabled?: boolean;
  }>(),
  {
    showMainProduct: false,
    showCalculationFields: false,
    showOutputFields: false,
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: Record<string, unknown>[]];
}>();

const { t } = useI18n();
const rows = ref<EditableRelationRow[]>([]);
let rowSeed = 0;

const columns = computed<RelationColumn[]>(() => {
  const baseColumns: RelationColumn[] = [
    { colKey: 'resource', title: props.resourceLabel, minWidth: 220 },
    { colKey: 'amount', title: props.amountLabel, width: 140 },
    { colKey: 'unit', title: t('process.field.unit'), width: 110 },
  ];
  if (props.showMainProduct) {
    baseColumns.push({ colKey: 'is_main_product', title: t('process.node.field.mainProduct'), width: 96 });
  }
  if (props.showOutputFields) {
    baseColumns.push({ colKey: 'output_type', title: t('process.node.field.outputKind'), width: 120 });
    baseColumns.push({ colKey: 'treatment_cost', title: t('process.node.field.treatmentPrice'), width: 130 });
  }
  if (props.showCalculationFields) {
    baseColumns.push({ colKey: 'formula_type', title: t('process.node.field.formulaType'), width: 110 });
    baseColumns.push({ colKey: 'expression', title: t('process.node.field.sourceExpression'), minWidth: 180 });
  }
  baseColumns.push(
    { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
    { colKey: 'operation', title: t('common.field.operation'), width: 72, align: 'center' },
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
    formula_type: 'fixed',
    expression: '',
    treatment_cost: 0,
    output_type: 'product',
    balance_weight: 0,
    amount_per_ton: 0,
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
  return `${option.code} / ${option.name}${option.unit ? ` (${option.unit})` : ''}`;
}

function formulaTypeLabel(value: string): string {
  const key = processFormulaTypeLocaleKey(value);
  return key ? t(key) : value;
}

function outputTypeLabel(value: string): string {
  const key = processOutputTypeLocaleKey(value);
  return key ? t(key) : value;
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
        :empty="t('process.node.empty.relation', { resource: resourceLabel })"
      >
        <template #resource="{ row }">
          <t-select
            filterable
            clearable
            :disabled="disabled"
            :model-value="getField(row, idKey)"
            :placeholder="selectPlaceholder"
            @update:model-value="(value: RelationFieldValue) => updateField(row, idKey, value)"
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
            @update:model-value="(value: RelationFieldValue) => updateField(row, amountKey, value)"
          />
        </template>
        <template #unit="{ row }">
          <t-select
            filterable
            creatable
            clearable
            :disabled="disabled"
            :model-value="String(row.unit || '')"
            :placeholder="t('process.node.placeholder.unit')"
            @update:model-value="(value: RelationFieldValue) => updateField(row, 'unit', value)"
          >
            <t-option v-for="option in PROCESS_UNIT_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
          </t-select>
        </template>
        <template #is_main_product="{ row }">
          <t-switch
            :disabled="disabled"
            :model-value="Boolean(row.is_main_product)"
            @update:model-value="(value: RelationFieldValue) => updateField(row, 'is_main_product', value)"
          />
        </template>
        <template #output_type="{ row }">
          <t-select :model-value="getField(row, 'output_type')" @update:model-value="(value: RelationFieldValue) => updateField(row, 'output_type', value)">
            <t-option :label="outputTypeLabel('product')" value="product" /><t-option :label="outputTypeLabel('byproduct')" value="byproduct" />
            <t-option :label="outputTypeLabel('solid_waste')" value="solid_waste" /><t-option :label="outputTypeLabel('wastewater')" value="wastewater" />
          </t-select>
        </template>
        <template #treatment_cost="{ row }">
          <t-input-number :min="0" theme="normal" :model-value="getField(row, 'treatment_cost') as number | string" @update:model-value="(value: RelationFieldValue) => updateField(row, 'treatment_cost', value)" />
        </template>
        <template #formula_type="{ row }">
          <t-select :model-value="getField(row, 'formula_type')" @update:model-value="(value: RelationFieldValue) => updateField(row, 'formula_type', value)">
            <t-option :label="formulaTypeLabel('fixed')" value="fixed" /><t-option :label="formulaTypeLabel('expression')" value="expression" />
          </t-select>
        </template>
        <template #expression="{ row }">
          <t-input :model-value="String(row.expression || '')" :placeholder="t('process.node.placeholder.optional')" @update:model-value="(value: RelationFieldValue) => updateField(row, 'expression', value)" />
        </template>
        <template #remark="{ row }">
          <t-input
            clearable
            :disabled="disabled"
            :model-value="String(row.remark || '')"
            :placeholder="t('process.node.placeholder.remark')"
            @update:model-value="(value: RelationFieldValue) => updateField(row, 'remark', value)"
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
  min-width: 1120px;
}
</style>
