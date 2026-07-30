<script setup lang="ts">
import { useI18n } from 'vue-i18n';

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

const { t } = useI18n();

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
    :resource-label="t('process.node.field.publicService')"
    :amount-label="t('process.node.field.bmAmountFactor')"
    :add-label="t('process.node.action.addPublicService')"
    :select-placeholder="t('process.node.placeholder.publicService')"
    show-calculation-fields
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
