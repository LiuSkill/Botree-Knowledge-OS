<script setup lang="ts">
import { useI18n } from 'vue-i18n';

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

const { t } = useI18n();

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
    :resource-label="t('process.node.field.inputMaterial')"
    :amount-label="t('process.node.field.amountPerTon')"
    :add-label="t('process.node.action.addMaterial')"
    :select-placeholder="t('process.node.placeholder.material')"
    :disabled="disabled"
    @update:model-value="handleUpdate"
  />
</template>
