<script setup lang="ts">
import { AddIcon, DeleteIcon } from 'tdesign-icons-vue-next';
import { ref, watch } from 'vue';

import type { ProcessNodeEquipmentPayload } from '@/views/process-config/node/types';

type EditableEquipmentRow = ProcessNodeEquipmentPayload & {
  _rowKey: string;
};

const props = withDefaults(
  defineProps<{
    modelValue: ProcessNodeEquipmentPayload[];
    disabled?: boolean;
  }>(),
  {
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: ProcessNodeEquipmentPayload[]];
}>();

const CURRENCY_OPTIONS = ['CNY', 'EUR', 'USD'];

const columns = [
  { colKey: 'equipment_name', title: '设备名称', minWidth: 180 },
  { colKey: 'equipment_type', title: '设备类型', width: 140 },
  { colKey: 'quantity', title: '数量', width: 120 },
  { colKey: 'investment_amount', title: '投资额', width: 140 },
  { colKey: 'currency', title: '币种', width: 100 },
  { colKey: 'remark', title: '备注', minWidth: 160 },
  { colKey: 'operation', title: '操作', width: 72, align: 'center' },
];

const rows = ref<EditableEquipmentRow[]>([]);
let rowSeed = 0;

watch(
  () => props.modelValue,
  (value) => {
    rows.value = (value || []).map((item, index) => ({
      _rowKey: `equipment-${Date.now()}-${rowSeed++}`,
      equipment_name: item.equipment_name || '',
      equipment_type: item.equipment_type || '',
      quantity: item.quantity ?? 0,
      investment_amount: item.investment_amount ?? 0,
      currency: item.currency || 'CNY',
      sort_order: item.sort_order ?? index + 1,
      remark: item.remark || '',
    }));
  },
  { immediate: true },
);

function addRow(): void {
  rows.value = [
    ...rows.value,
    {
      _rowKey: `equipment-${Date.now()}-${rowSeed++}`,
      equipment_name: '',
      equipment_type: '',
      quantity: 1,
      investment_amount: 0,
      currency: 'CNY',
      sort_order: rows.value.length + 1,
      remark: '',
    },
  ];
  emitRows();
}

function removeRow(rowIndex: number): void {
  rows.value = rows.value.filter((_, index) => index !== rowIndex).map((row, index) => ({ ...row, sort_order: index + 1 }));
  emitRows();
}

function emitRows(): void {
  emit(
    'update:modelValue',
    rows.value.map(({ _rowKey, ...row }) => ({ ...row })),
  );
}
</script>

<template>
  <div class="equipment-editor">
    <div class="equipment-editor-toolbar">
      <t-button size="small" variant="outline" :disabled="disabled" @click="addRow">
        <template #icon><AddIcon /></template>
        新增设备
      </t-button>
    </div>

    <div class="equipment-editor-table">
      <t-table row-key="_rowKey" bordered table-layout="fixed" size="small" :columns="columns" :data="rows" empty="暂无设备/投资配置">
        <template #equipment_name="{ row }">
          <t-input v-model="row.equipment_name" clearable :disabled="disabled" placeholder="设备名称" @update:model-value="emitRows" />
        </template>
        <template #equipment_type="{ row }">
          <t-input v-model="row.equipment_type" clearable :disabled="disabled" placeholder="设备类型" @update:model-value="emitRows" />
        </template>
        <template #quantity="{ row }">
          <t-input-number v-model="row.quantity" :disabled="disabled" :min="0" :step="1" theme="normal" @update:model-value="emitRows" />
        </template>
        <template #investment_amount="{ row }">
          <t-input-number v-model="row.investment_amount" :disabled="disabled" :min="0" :step="1000" theme="normal" @update:model-value="emitRows" />
        </template>
        <template #currency="{ row }">
          <t-select v-model="row.currency" :disabled="disabled" @change="emitRows">
            <t-option v-for="currency in CURRENCY_OPTIONS" :key="currency" :label="currency" :value="currency" />
          </t-select>
        </template>
        <template #remark="{ row }">
          <t-input v-model="row.remark" clearable :disabled="disabled" placeholder="备注" @update:model-value="emitRows" />
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
.equipment-editor {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.equipment-editor-toolbar {
  display: flex;
  justify-content: flex-end;
}

.equipment-editor-table {
  min-width: 0;
  overflow-x: auto;
}

.equipment-editor-table :deep(.t-table) {
  min-width: 920px;
}
</style>
