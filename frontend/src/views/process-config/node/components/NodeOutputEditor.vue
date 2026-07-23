<script setup lang="ts">
import NodeRelationEditor from '@/views/process-config/node/components/NodeRelationEditor.vue';
import type { ProcessLibraryOptionItem, ProcessNodeOutputPayload } from '@/views/process-config/node/types';

defineProps<{
  modelValue: ProcessNodeOutputPayload[];
  options: ProcessLibraryOptionItem[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  'update:modelValue': [value: ProcessNodeOutputPayload[]];
}>();

function handleUpdate(value: Record<string, unknown>[]): void {
  emit('update:modelValue', value as unknown as ProcessNodeOutputPayload[]);
}
</script>

<template>
  <NodeRelationEditor
    :model-value="modelValue as unknown as Record<string, unknown>[]"
    :options="options"
    id-key="product_id"
    amount-key="output_per_ton"
    resource-label="输出产品"
    amount-label="产出量"
    add-label="新增产品"
    select-placeholder="请选择产品"
    show-main-product
    show-output-fields
    show-calculation-fields
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
