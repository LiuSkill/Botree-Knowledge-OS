<script setup lang="ts">
import NodeRelationEditor from '@/views/process-config/node/components/NodeRelationEditor.vue';
import type { ProcessLibraryOptionItem, ProcessNodePublicServicePayload } from '@/views/process-config/node/types';

defineProps<{
  modelValue: ProcessNodePublicServicePayload[];
  options: ProcessLibraryOptionItem[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: ProcessNodePublicServicePayload[]];
}>();

function handleUpdate(value: Record<string, unknown>[]): void {
  emit('update:modelValue', value as unknown as ProcessNodePublicServicePayload[]);
}
</script>

<template>
  <NodeRelationEditor
    :model-value="modelValue as unknown as Record<string, unknown>[]"
    :options="options"
    id-key="public_service_id"
    amount-key="amount_per_ton_bm"
    resource-label="公共服务"
    amount-label="BM 吨耗系数"
    add-label="新增公共服务"
    select-placeholder="请选择公共服务"
    show-calculation-fields
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
