<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, ref, watch } from 'vue';
import { AddIcon, DeleteIcon } from 'tdesign-icons-vue-next';

import RegionPriceEditor from '@/views/process-config/components/RegionPriceEditor.vue';
import type {
  ProcessLibraryItem,
  ProcessLibraryPayload,
  ProcessLibraryStatus,
  ProcessLibraryTypeOption,
  ProcessConfigModuleKey,
  ProcessMaterialCompositionPayload,
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
    moduleKey: ProcessConfigModuleKey;
    compositions?: ProcessMaterialCompositionPayload[];
  }>(),
  {
    data: null,
    loading: false,
    typeOptions: () => [],
    compositions: () => [],
  },
);

const emit = defineEmits<{
  'update:visible': [value: boolean];
  submit: [payload: ProcessLibraryPayload, compositions: ProcessMaterialCompositionPayload[]];
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
const compositionRows = ref<Array<ProcessMaterialCompositionPayload & { percentage: number }>>([]);
const isMaterial = computed(() => props.moduleKey === 'materials');
const compositionColumns = [
  { colKey: 'element_code', title: '元素', width: 130 },
  { colKey: 'element_name', title: '名称', minWidth: 150 },
  { colKey: 'percentage', title: '含量（%）', width: 160 },
  { colKey: 'remark', title: '备注', minWidth: 160 },
  { colKey: 'operation', title: '操作', width: 70, align: 'center' as const },
];

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
  compositionRows.value = props.compositions.map((item) => ({
    ...item,
    percentage: Number(item.content_ratio || 0) * 100,
  }));
}

function addComposition(): void {
  compositionRows.value.push({ element_code: '', element_name: '', content_ratio: 0, percentage: 0, unit: '%', remark: '' });
}

function removeComposition(index: number): void { compositionRows.value.splice(index, 1); }

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

  const compositions = compositionRows.value.map((row) => ({
    element_code: row.element_code.trim(),
    element_name: row.element_name.trim() || row.element_code.trim(),
    content_ratio: String(Number(row.percentage) / 100),
    unit: '%',
    remark: row.remark?.trim() || null,
  }));
  if (isMaterial.value) {
    if (compositions.some((row) => !row.element_code || !Number.isFinite(Number(row.content_ratio)) || Number(row.content_ratio) < 0)) {
      MessagePlugin.warning('请完整填写元素及非负含量');
      return;
    }
    if (new Set(compositions.map((row) => row.element_code.toLowerCase())).size !== compositions.length) {
      MessagePlugin.warning('元素不能重复');
      return;
    }
  }
  emit('submit', payload, compositions);
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

      <section v-if="isMaterial" class="composition-section">
        <div class="composition-header"><strong>原料组成</strong><t-button size="small" variant="outline" @click="addComposition"><template #icon><AddIcon /></template>新增元素</t-button></div>
        <div class="composition-table"><t-table row-key="element_code" bordered size="small" :columns="compositionColumns" :data="compositionRows" empty="暂无元素组成">
          <template #element_code="{ row }"><t-input v-model="row.element_code" placeholder="如 Li" /></template>
          <template #element_name="{ row }"><t-input v-model="row.element_name" placeholder="如 锂" /></template>
          <template #percentage="{ row }"><t-input-number v-model="row.percentage" :min="0" :max="100" :decimal-places="4" theme="normal" suffix="%" /></template>
          <template #remark="{ row }"><t-input v-model="row.remark" placeholder="可选" /></template>
          <template #operation="{ rowIndex }"><t-button shape="square" theme="danger" variant="text" @click="removeComposition(rowIndex)"><DeleteIcon /></t-button></template>
        </t-table></div>
      </section>

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
.composition-section { display: grid; gap: 10px; margin-bottom: 16px; }
.composition-header { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.composition-table { overflow-x: auto; }
.composition-table :deep(.t-table) { min-width: 680px; }

@media (max-width: 720px) {
  .form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
