<script setup lang="ts">
import NodeRelationEditor from '@/views/process-config/node/components/NodeRelationEditor.vue';
import type { ProcessLibraryOptionItem, ProcessNodeConsumablePayload } from '@/views/process-config/node/types';

defineProps<{
  modelValue: ProcessNodeConsumablePayload[];
  options: ProcessLibraryOptionItem[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: ProcessNodeConsumablePayload[]];
}>();

function handleUpdate(value: Record<string, unknown>[]): void {
  emit('update:modelValue', value as unknown as ProcessNodeConsumablePayload[]);
}
</script>

<template>
  <NodeRelationEditor
    :model-value="modelValue as unknown as Record<string, unknown>[]"
    :options="options"
    id-key="consumable_id"
    amount-key="amount_per_ton"
    resource-label="消耗品"
    amount-label="吨耗"
    add-label="新增消耗品"
    select-placeholder="请选择消耗品"
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
