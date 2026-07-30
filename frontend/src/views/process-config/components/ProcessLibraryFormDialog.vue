<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
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
import { normalizeRegionPrices, PROCESS_UNIT_OPTIONS } from '@/views/process-config/types';

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

const { t } = useI18n();
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
  salary_period: 'year',
  welfare_factor: 1,
  asset_class: 'equipment',
});
const compositionRows = ref<Array<ProcessMaterialCompositionPayload & { percentage: number }>>([]);
const isMaterial = computed(() => props.moduleKey === 'materials');
const isLaborCost = computed(() => props.moduleKey === 'labor-costs');
const isAsset = computed(() => props.moduleKey === 'equipment-assets' || props.moduleKey === 'infrastructure-assets');
const compositionColumns = computed(() => [
  { colKey: 'element_code', title: t('process.field.element'), width: 130 },
  { colKey: 'element_name', title: t('process.field.name'), minWidth: 150 },
  { colKey: 'percentage', title: t('process.field.contentPercent'), width: 160 },
  { colKey: 'remark', title: t('process.field.remark'), minWidth: 160 },
  { colKey: 'operation', title: t('common.field.operation'), width: 70, align: 'center' as const },
]);

const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const dialogTitle = computed(() => (props.mode === 'create' ? t('process.title.create', { entity: props.entityName }) : t('process.title.edit', { entity: props.entityName })));
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
    salary_period: data?.salary_period || 'year',
    welfare_factor: data?.welfare_factor ?? 1,
    asset_class: data?.asset_class || (props.moduleKey === 'infrastructure-assets' ? 'infrastructure' : 'equipment'),
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
      MessagePlugin.warning(t('process.message.regionPriceRequired', { region: price.region_name }));
      return false;
    }
    const numberValue = Number(value);
    if (!Number.isFinite(numberValue) || numberValue < 0) {
      MessagePlugin.warning(t('process.message.regionPriceInvalid', { region: price.region_name }));
      return false;
    }
    if (!price.unit.trim()) {
      MessagePlugin.warning(t('process.message.regionUnitRequired', { region: price.region_name }));
      return false;
    }
    return true;
  });
}

function buildPayload(): ProcessLibraryPayload {
  const unit = form.unit.trim();
  const payload: ProcessLibraryPayload = {
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
  if (isLaborCost.value) {
    payload.salary_period = form.salary_period || 'year';
    payload.welfare_factor = String(form.welfare_factor ?? 1).trim() || '1';
  }
  if (isAsset.value) {
    payload.asset_class = props.moduleKey === 'infrastructure-assets' ? 'infrastructure' : 'equipment';
  }
  return payload;
}

function handleConfirm(): void {
  if (!validateRequired(form.code, t('process.message.codeRequired', { entity: props.entityName }))) return;
  if (!validateRequired(form.name, t('process.message.nameRequired', { entity: props.entityName }))) return;
  if (!validateRequired(form.type, t('process.message.typeRequired', { entity: props.entityName }))) return;
  if (!validateRequired(form.unit, t('process.message.unitRequired', { entity: props.entityName }))) return;

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
      MessagePlugin.warning(t('process.message.compositionRequired'));
      return;
    }
    if (new Set(compositions.map((row) => row.element_code.toLowerCase())).size !== compositions.length) {
      MessagePlugin.warning(t('process.message.compositionDuplicate'));
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
        <t-form-item :label="t('process.field.code')" required-mark>
          <t-input v-model="form.code" clearable maxlength="80" :placeholder="t('process.placeholder.code')" />
        </t-form-item>
        <t-form-item :label="t('process.field.name')" required-mark>
          <t-input v-model="form.name" clearable maxlength="200" :placeholder="t('process.placeholder.name')" />
        </t-form-item>
        <t-form-item :label="t('process.field.type')" required-mark>
          <t-select v-if="hasTypeOptions" v-model="form.type" clearable :placeholder="t('process.placeholder.type')">
            <t-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </t-select>
          <t-input v-else v-model="form.type" clearable maxlength="100" :placeholder="t('process.placeholder.typeInput')" />
        </t-form-item>
        <t-form-item :label="t('process.field.unit')" required-mark>
          <t-select v-model="form.unit" filterable creatable clearable :placeholder="t('process.placeholder.unit')">
            <t-option v-for="option in PROCESS_UNIT_OPTIONS" :key="option.value" :label="option.label" :value="option.value" />
          </t-select>
        </t-form-item>
        <t-form-item :label="t('common.field.status')" required-mark>
          <t-radio-group v-model="form.status">
            <t-radio-button value="enabled">{{ t('process.status.enabled') }}</t-radio-button>
            <t-radio-button value="draft">{{ t('process.status.draft') }}</t-radio-button>
            <t-radio-button value="disabled">{{ t('process.status.disabled') }}</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <t-form-item :label="t('process.field.sort')" required-mark>
          <t-input-number v-model="form.sort_order" :min="0" :max="999999" :step="1" />
        </t-form-item>
      </div>

      <t-form-item :label="t('process.field.description')">
        <t-textarea v-model="form.description" maxlength="1000" autosize :placeholder="t('process.placeholder.description')" />
      </t-form-item>

      <section v-if="isLaborCost" class="composition-section">
        <div class="composition-header"><strong>{{ t('process.field.salaryParams') }}</strong></div>
        <div class="form-grid">
          <t-form-item :label="t('process.field.salaryPeriod')" required-mark>
            <t-radio-group v-model="form.salary_period">
              <t-radio-button value="year">{{ t('process.salaryPeriod.year') }}</t-radio-button>
              <t-radio-button value="month">{{ t('process.salaryPeriod.month') }}</t-radio-button>
            </t-radio-group>
          </t-form-item>
          <t-form-item :label="t('process.field.welfareFactor')" required-mark>
            <t-input-number v-model="form.welfare_factor" :min="0" :step="0.1" :decimal-places="4" theme="normal" />
          </t-form-item>
        </div>
        <t-form-item :label="t('process.field.regionalSalary')">
          <RegionPriceEditor v-model="form.region_prices" :unit="form.unit" />
        </t-form-item>
      </section>

      <section v-else-if="isAsset" class="composition-section">
        <div class="composition-header"><strong>{{ t('process.field.assetParams') }}</strong></div>
        <div class="form-grid">
          <t-form-item :label="t('process.field.assetClass')" required-mark>
            <t-radio-group v-model="form.asset_class" disabled>
              <t-radio-button value="equipment">{{ t('process.assetClass.equipment') }}</t-radio-button>
              <t-radio-button value="infrastructure">{{ t('process.assetClass.infrastructure') }}</t-radio-button>
            </t-radio-group>
          </t-form-item>
        </div>
        <t-form-item :label="t('process.field.regionalAssetPrice')">
          <RegionPriceEditor v-model="form.region_prices" :unit="form.unit" />
        </t-form-item>
      </section>

      <t-form-item v-else :label="t('process.field.regionPrice')">
        <RegionPriceEditor v-model="form.region_prices" :unit="form.unit" />
      </t-form-item>

      <section v-if="isMaterial" class="composition-section">
        <div class="composition-header"><strong>{{ t('process.field.materialComposition') }}</strong><t-button size="small" variant="outline" @click="addComposition"><template #icon><AddIcon /></template>{{ t('process.action.addElement') }}</t-button></div>
        <div class="composition-table"><t-table row-key="element_code" bordered size="small" :columns="compositionColumns" :data="compositionRows" :empty="t('process.empty.composition')">
          <template #element_code="{ row }"><t-input v-model="row.element_code" :placeholder="t('process.placeholder.elementCode')" /></template>
          <template #element_name="{ row }"><t-input v-model="row.element_name" :placeholder="t('process.placeholder.elementName')" /></template>
          <template #percentage="{ row }"><t-input-number v-model="row.percentage" :min="0" :max="100" :decimal-places="4" theme="normal" suffix="%" /></template>
          <template #remark="{ row }"><t-input v-model="row.remark" :placeholder="t('process.placeholder.optional')" /></template>
          <template #operation="{ rowIndex }"><t-button shape="square" theme="danger" variant="text" @click="removeComposition(rowIndex)"><DeleteIcon /></t-button></template>
        </t-table></div>
      </section>

      <t-form-item :label="t('process.field.remark')">
        <t-textarea v-model="form.remark" maxlength="500" autosize :placeholder="t('process.placeholder.remark')" />
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
