<script setup lang="ts">
import { AddIcon, DeleteIcon } from 'tdesign-icons-vue-next';
import { ref, watch } from 'vue';

import type { ProcessLibraryOptionItem, ProcessNodeLaborPayload } from '@/views/process-config/node/types';

type EditableLaborRow = ProcessNodeLaborPayload & {
  _rowKey: string;
};

const props = withDefaults(
  defineProps<{
    modelValue: ProcessNodeLaborPayload[];
    options: ProcessLibraryOptionItem[];
    disabled?: boolean;
  }>(),
  {
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: ProcessNodeLaborPayload[]];
}>();

const columns = [
  { colKey: 'labor_cost_id', title: '岗位/人员', minWidth: 180 },
  { colKey: 'headcount', title: '人数', width: 120 },
  { colKey: 'load_factor', title: '负荷系数', width: 120 },
  { colKey: 'include_in_opex', title: '计入OPEX', width: 120 },
  { colKey: 'remark', title: '备注', minWidth: 160 },
  { colKey: 'operation', title: '操作', width: 72, align: 'center' as const },
];

const rows = ref<EditableLaborRow[]>([]);
let rowSeed = 0;

watch(
  () => props.modelValue,
  (value) => {
    rows.value = (value || []).map((item, index) => ({
      _rowKey: `labor-${Date.now()}-${rowSeed++}`,
      labor_cost_id: item.labor_cost_id ?? null,
      headcount: item.headcount ?? 0,
      load_factor: item.load_factor ?? 1,
      include_in_opex: item.include_in_opex ?? true,
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
      _rowKey: `labor-${Date.now()}-${rowSeed++}`,
      labor_cost_id: null,
      headcount: 1,
      load_factor: 1,
      include_in_opex: true,
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
  <div class="labor-editor">
    <div class="labor-editor-toolbar">
      <t-button size="small" variant="outline" :disabled="disabled" @click="addRow">
        <template #icon><AddIcon /></template>
        新增人员
      </t-button>
    </div>

    <div class="labor-editor-table">
      <t-table row-key="_rowKey" bordered table-layout="fixed" size="small" :columns="columns" :data="rows" empty="暂无人员成本配置">
        <template #labor_cost_id="{ row }">
          <t-select v-model="row.labor_cost_id" filterable clearable :disabled="disabled" placeholder="选择人员成本" @change="emitRows">
            <t-option v-for="item in options" :key="item.id" :label="`${item.name}（${item.code}）`" :value="item.id" />
          </t-select>
        </template>
        <template #headcount="{ row }">
          <t-input-number v-model="row.headcount" :disabled="disabled" :min="0" :step="1" theme="normal" @update:model-value="emitRows" />
        </template>
        <template #load_factor="{ row }">
          <t-input-number v-model="row.load_factor" :disabled="disabled" :min="0" :step="0.1" :decimal-places="4" theme="normal" @update:model-value="emitRows" />
        </template>
        <template #include_in_opex="{ row }">
          <t-switch v-model="row.include_in_opex" :disabled="disabled" @change="emitRows" />
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
.labor-editor {
  display: grid;
  gap: 10px;
  min-width: 0;
}

.labor-editor-toolbar {
  display: flex;
  justify-content: flex-end;
}

.labor-editor-table {
  min-width: 0;
  overflow-x: auto;
}

.labor-editor-table :deep(.t-table) {
  min-width: 820px;
}
</style>
