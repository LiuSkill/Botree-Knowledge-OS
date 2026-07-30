<script setup lang="ts">
import { useI18n } from 'vue-i18n';

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

const { t } = useI18n();

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
    :resource-label="t('process.node.field.outputProduct')"
    :amount-label="t('process.node.field.outputAmount')"
    :add-label="t('process.node.action.addProduct')"
    :select-placeholder="t('process.node.placeholder.product')"
    show-main-product
    show-output-fields
    show-calculation-fields
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
