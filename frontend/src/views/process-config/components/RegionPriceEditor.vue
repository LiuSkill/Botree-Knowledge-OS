<script setup lang="ts">
import { ref, watch } from 'vue';

import type { ProcessRegionPrice } from '@/views/process-config/types';
import { normalizeRegionPrices } from '@/views/process-config/types';

const props = withDefaults(
  defineProps<{
    modelValue: ProcessRegionPrice[];
    unit?: string;
    disabled?: boolean;
  }>(),
  {
    unit: '',
    disabled: false,
  },
);

const emit = defineEmits<{
  'update:modelValue': [value: ProcessRegionPrice[]];
}>();

const rows = ref<ProcessRegionPrice[]>(normalizeRegionPrices(props.modelValue, props.unit));

watch(
  () => [props.modelValue, props.unit] as const,
  ([regionPrices, unit]) => {
    rows.value = normalizeRegionPrices(regionPrices, unit);
  },
  { deep: true, immediate: true },
);

function emitRows(): void {
  emit(
    'update:modelValue',
    normalizeRegionPrices(rows.value, props.unit).map((row) => ({
      ...row,
      unit_price: row.unit_price === '' ? 0 : row.unit_price,
      unit: row.unit || props.unit,
    })),
  );
}
</script>

<template>
  <div class="region-price-editor">
    <div class="region-price-row region-price-head">
      <span>区域</span>
      <span>币种</span>
      <span>单价</span>
      <span>单位</span>
      <span>状态</span>
    </div>
    <div v-for="row in rows" :key="row.region_code" class="region-price-row">
      <div class="region-cell">
        <strong>{{ row.region_name }}</strong>
        <small>{{ row.region_code }}</small>
      </div>
      <t-tag size="small" variant="light">{{ row.currency }}</t-tag>
      <t-input
        v-model="row.unit_price"
        :disabled="disabled"
        align="right"
        clearable
        placeholder="0.00"
        @change="emitRows"
        @blur="emitRows"
      />
      <t-input v-model="row.unit" :disabled="disabled" clearable placeholder="计价单位" @change="emitRows" @blur="emitRows" />
      <t-select v-model="row.status" :disabled="disabled" @change="emitRows">
        <t-option label="启用" value="enabled" />
        <t-option label="草稿" value="draft" />
        <t-option label="停用" value="disabled" />
      </t-select>
    </div>
  </div>
</template>

<style scoped>
.region-price-editor {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.region-price-row {
  display: grid;
  grid-template-columns: minmax(96px, 1.1fr) 76px minmax(120px, 1.2fr) minmax(112px, 1fr) 112px;
  align-items: center;
  gap: 10px;
}

.region-price-head {
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.region-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.region-cell strong {
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
}

.region-cell small {
  color: #94a3b8;
  font-size: 12px;
}

@media (max-width: 720px) {
  .region-price-row {
    grid-template-columns: 1fr;
  }

  .region-price-head {
    display: none;
  }
}
</style>
