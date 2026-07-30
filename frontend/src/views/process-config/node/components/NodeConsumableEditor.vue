<script setup lang="ts">
import { useI18n } from 'vue-i18n';

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

const { t } = useI18n();

function handleUpdate(value: Record<string, unknown>[]): void {
  emit('update:modelValue', value as unknown as ProcessNodeConsumablePayload[]);
}
</script>

<template>
  <NodeRelationEditor
    :model-value="modelValue as unknown as Record<string, unknown>[]"
    :options="options"
    id-key="consumable_id"
    amount-key="amount_per_ton_bm"
    :resource-label="t('process.node.field.consumable')"
    :amount-label="t('process.node.field.bmAmountFactor')"
    :add-label="t('process.node.action.addConsumable')"
    :select-placeholder="t('process.node.placeholder.consumable')"
    show-calculation-fields
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
