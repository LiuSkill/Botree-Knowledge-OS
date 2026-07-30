<script setup lang="ts">
import { AddIcon, DeleteIcon } from 'tdesign-icons-vue-next';
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';

import type { ProcessLibraryOptionItem, ProcessNodeEquipmentPayload } from '@/views/process-config/node/types';

type EditableEquipmentRow = ProcessNodeEquipmentPayload & {
  _rowKey: string;
};

const props = withDefaults(
  defineProps<{
    modelValue: ProcessNodeEquipmentPayload[];
    assetOptions?: ProcessLibraryOptionItem[];
    disabled?: boolean;
  }>(),
  {
    assetOptions: () => [],
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: ProcessNodeEquipmentPayload[]];
}>();

const { t } = useI18n();
const columns = computed(() => [
  { colKey: 'asset_id', title: t('process.node.field.asset'), minWidth: 180 },
  { colKey: 'quantity', title: t('process.node.field.quantity'), width: 120 },
  { colKey: 'installation_factor', title: t('process.node.field.installationFactor'), width: 120 },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
  { colKey: 'operation', title: t('common.field.operation'), width: 72, align: 'center' as const },
]);

const rows = ref<EditableEquipmentRow[]>([]);
let rowSeed = 0;

watch(
  () => props.modelValue,
  (value) => {
    rows.value = (value || []).map((item, index) => ({
      _rowKey: `equipment-${Date.now()}-${rowSeed++}`,
      asset_id: item.asset_id || null,
      asset_class: item.asset_class || 'equipment',
      equipment_name: item.equipment_name || '',
      equipment_type: item.equipment_type || '',
      quantity: item.quantity ?? 0,
      installation_factor: item.installation_factor ?? 1,
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
      asset_id: null,
      asset_class: 'equipment',
      equipment_name: '',
      equipment_type: '',
      quantity: 1,
      installation_factor: 1,
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

function handleAssetChange(row: EditableEquipmentRow): void {
  const asset = props.assetOptions.find((item) => item.id === row.asset_id);
  if (asset) {
    row.asset_class = asset.asset_class || 'equipment';
    row.equipment_name = asset.name;
    row.equipment_type = asset.type;
  }
  emitRows();
}
</script>

<template>
  <div class="equipment-editor">
    <div class="equipment-editor-toolbar">
      <t-button size="small" variant="outline" :disabled="disabled" @click="addRow">
        <template #icon><AddIcon /></template>
        {{ t('process.node.action.addEquipment') }}
      </t-button>
    </div>

    <div class="equipment-editor-table">
      <t-table row-key="_rowKey" bordered table-layout="fixed" size="small" :columns="columns" :data="rows" :empty="t('process.node.empty.equipmentConfig')">
        <template #asset_id="{ row }">
          <t-select v-model="row.asset_id" filterable clearable :disabled="disabled" :placeholder="t('process.node.placeholder.asset')" @change="() => handleAssetChange(row)">
            <t-option v-for="asset in assetOptions" :key="asset.id" :label="`${asset.code} ${asset.name}`" :value="asset.id" />
          </t-select>
        </template>
        <template #quantity="{ row }">
          <t-input-number v-model="row.quantity" :disabled="disabled" :min="0" :step="1" theme="normal" @update:model-value="emitRows" />
        </template>
        <template #installation_factor="{ row }">
          <t-input-number v-model="row.installation_factor" :disabled="disabled" :min="0" :step="0.1" :decimal-places="4" theme="normal" @update:model-value="emitRows" />
        </template>
        <template #remark="{ row }">
          <t-input v-model="row.remark" clearable :disabled="disabled" :placeholder="t('process.node.placeholder.remark')" @update:model-value="emitRows" />
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
  min-width: 720px;
}
</style>
