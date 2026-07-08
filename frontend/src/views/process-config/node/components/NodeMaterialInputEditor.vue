<script setup lang="ts">
import NodeRelationEditor from '@/views/process-config/node/components/NodeRelationEditor.vue';
import type { ProcessLibraryOptionItem, ProcessNodeMaterialInputPayload } from '@/views/process-config/node/types';

defineProps<{
  modelValue: ProcessNodeMaterialInputPayload[];
  options: ProcessLibraryOptionItem[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: ProcessNodeMaterialInputPayload[]];
}>();

function handleUpdate(value: Record<string, unknown>[]): void {
  emit('update:modelValue', value as unknown as ProcessNodeMaterialInputPayload[]);
}
</script>

<template>
  <NodeRelationEditor
    :model-value="modelValue as unknown as Record<string, unknown>[]"
    :options="options"
    id-key="material_id"
    amount-key="amount_per_ton"
    resource-label="输入原料"
    amount-label="吨耗"
    add-label="新增原料"
    select-placeholder="请选择原料"
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
