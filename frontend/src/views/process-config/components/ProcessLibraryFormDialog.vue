<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, watch } from 'vue';

import RegionPriceEditor from '@/views/process-config/components/RegionPriceEditor.vue';
import type {
  ProcessLibraryItem,
  ProcessLibraryPayload,
  ProcessLibraryStatus,
  ProcessLibraryTypeOption,
  ProcessRegionPrice,
} from '@/views/process-config/types';
import { normalizeRegionPrices } from '@/views/process-config/types';

type DialogMode = 'create' | 'edit';

const props = withDefaults(
  defineProps<{
    visible: boolean;
    mode: DialogMode;
    entityName: string;
    data?: ProcessLibraryItem | null;
    loading?: boolean;
    typeOptions?: readonly ProcessLibraryTypeOption[];
  }>(),
  {
    data: null,
    loading: false,
    typeOptions: () => [],
  },
);

const emit = defineEmits<{
  'update:visible': [value: boolean];
  submit: [payload: ProcessLibraryPayload];
}>();

const form = reactive<ProcessLibraryPayload>({
  code: '',
  name: '',
  type: '',
  description: '',
  unit: '',
  status: 'enabled',
  sort_order: 0,
  remark: '',
  region_prices: normalizeRegionPrices(),
});

const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const dialogTitle = computed(() => (props.mode === 'create' ? `新增${props.entityName}` : `编辑${props.entityName}`));
const hasTypeOptions = computed(() => props.typeOptions.length > 0);

watch(
  () => [props.visible, props.data, props.mode] as const,
  ([visible]) => {
    if (!visible) return;
    resetForm(props.data);
  },
  { immediate: true },
);

watch(
  () => form.unit,
  (unit) => {
    form.region_prices = normalizeRegionPrices(form.region_prices, unit.trim());
  },
);

function resetForm(data?: ProcessLibraryItem | null): void {
  Object.assign(form, {
    code: data?.code || '',
    name: data?.name || '',
    type: data?.type || '',
    description: data?.description || '',
    unit: data?.unit || '',
    status: data?.status || 'enabled',
    sort_order: data?.sort_order ?? 0,
    remark: data?.remark || '',
    region_prices: normalizeRegionPrices(data?.region_prices || [], data?.unit || ''),
  });
}

function validateRequired(value: string, message: string): boolean {
  if (value.trim()) return true;
  MessagePlugin.warning(message);
  return false;
}

function validatePrices(regionPrices: ProcessRegionPrice[]): boolean {
  return regionPrices.every((price) => {
    const value = String(price.unit_price ?? '').trim();
    if (!value) {
      MessagePlugin.warning(`请输入${price.region_name}区域单价`);
      return false;
    }
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue) || numberValue < 0) {
      MessagePlugin.warning(`${price.region_name}区域单价必须为非负数字`);
      return false;
    }
    if (!price.unit.trim()) {
      MessagePlugin.warning(`请输入${price.region_name}计价单位`);
      return false;
    }
    return true;
  });
}

function buildPayload(): ProcessLibraryPayload {
  const unit = form.unit.trim();
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    type: form.type.trim(),
    description: form.description?.trim() || null,
    unit,
    status: form.status as ProcessLibraryStatus,
    sort_order: Number(form.sort_order || 0),
    remark: form.remark?.trim() || null,
    region_prices: normalizeRegionPrices(form.region_prices, unit).map((price) => ({
      region_code: price.region_code,
      region_name: price.region_name,
      currency: price.currency,
      unit_price: String(price.unit_price ?? 0).trim() || '0',
      unit: price.unit.trim() || unit,
      status: price.status,
    })),
  };
}

function handleConfirm(): void {
  if (!validateRequired(form.code, `请输入${props.entityName}编码`)) return;
  if (!validateRequired(form.name, `请输入${props.entityName}名称`)) return;
  if (!validateRequired(form.type, `请输入${props.entityName}类型`)) return;
  if (!validateRequired(form.unit, `请输入${props.entityName}单位`)) return;

  const payload = buildPayload();
  if (!validatePrices(payload.region_prices)) return;

  emit('submit', payload);
}
</script>

<template>
  <t-dialog v-model:visible="visibleProxy" :header="dialogTitle" width="760px" :confirm-loading="loading" @confirm="handleConfirm">
    <t-form :data="form" label-align="top">
      <div class="form-grid">
        <t-form-item label="编码" required-mark>
          <t-input v-model="form.code" clearable maxlength="80" placeholder="请输入唯一编码" />
        </t-form-item>
        <t-form-item label="名称" required-mark>
          <t-input v-model="form.name" clearable maxlength="200" placeholder="请输入名称" />
        </t-form-item>
        <t-form-item label="类型" required-mark>
          <t-select v-if="hasTypeOptions" v-model="form.type" clearable placeholder="请选择类型">
            <t-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </t-select>
          <t-input v-else v-model="form.type" clearable maxlength="100" placeholder="请输入类型" />
        </t-form-item>
        <t-form-item label="单位" required-mark>
          <t-input v-model="form.unit" clearable maxlength="50" placeholder="请输入主单位" />
        </t-form-item>
        <t-form-item label="状态" required-mark>
          <t-radio-group v-model="form.status">
            <t-radio-button value="enabled">启用</t-radio-button>
            <t-radio-button value="draft">草稿</t-radio-button>
            <t-radio-button value="disabled">停用</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="排序" required-mark>
          <t-input-number v-model="form.sort_order" :min="0" :max="999999" :step="1" />
        </t-form-item>
      </div>

      <t-form-item label="描述">
        <t-textarea v-model="form.description" maxlength="1000" autosize placeholder="请输入描述" />
      </t-form-item>

      <t-form-item label="区域单价">
        <RegionPriceEditor v-model="form.region_prices" :unit="form.unit" />
      </t-form-item>

      <t-form-item label="备注">
        <t-textarea v-model="form.remark" maxlength="500" autosize placeholder="请输入备注" />
      </t-form-item>
    </t-form>
  </t-dialog>
</template>

<style scoped>
.form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}

@media (max-width: 720px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
