<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';

import type { ProcessLibraryOptionItem } from '@/views/process-config/node/types';
import { createEmptyRoutePayload, PROCESS_ROUTE_STATUS_OPTIONS, type ProcessCalculationOutputPayload, type ProcessRouteDetail, type ProcessRoutePayload, type RouteEditableNode, type RouteNodeOption } from '@/views/process-config/route/types';
import RouteNodeChainEditor from '@/views/process-config/route/components/RouteNodeChainEditor.vue';
import { processFormulaTypeLocaleKey, processOutputTypeLocaleKey, processStatusLocaleKey } from '@/views/process-config/i18n';

type FormMode = 'create' | 'edit';

const props = withDefaults(
  defineProps<{
    visible: boolean;
    mode: FormMode;
    route?: ProcessRouteDetail | null;
    nodeOptions: RouteNodeOption[];
    materialOptions: ProcessLibraryOptionItem[];
    productOptions: ProcessLibraryOptionItem[];
    saving?: boolean;
    optionsLoading?: boolean;
    calculationOutputs?: ProcessCalculationOutputPayload[];
  }>(),
  {
    route: null,
    saving: false,
    optionsLoading: false,
    calculationOutputs: () => [],
  },
);

const emit = defineEmits<{
  'update:visible': [value: boolean];
  submit: [payload: ProcessRoutePayload, calculationOutputs: ProcessCalculationOutputPayload[]];
}>();

const { t } = useI18n();
const form = reactive<ProcessRoutePayload>(createEmptyRoutePayload());
const outputRows = ref<ProcessCalculationOutputPayload[]>([]);
const outputColumns = computed(() => [
  { colKey: 'product_id', title: t('process.route.field.outputItem'), minWidth: 180 },
  { colKey: 'output_type', title: t('process.field.type'), width: 110 },
  { colKey: 'output_ratio', title: t('process.route.field.outputRatio'), width: 150 },
  { colKey: 'unit', title: t('process.field.unit'), width: 120 },
  { colKey: 'recovery_rate', title: t('process.route.field.recoveryRate'), width: 130 },
  { colKey: 'formula_type', title: t('process.node.field.formulaType'), width: 110 },
  { colKey: 'expression', title: t('process.node.field.sourceExpression'), minWidth: 170 },
  { colKey: 'operation', title: t('common.field.operation'), width: 70 },
]);

const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const drawerTitle = computed(() => (props.mode === 'create' ? t('process.route.title.create') : t('process.route.title.edit')));
const submitText = computed(() => (props.mode === 'create' ? t('process.route.action.createSubmit') : t('process.route.action.updateSubmit')));
const statusOptions = computed(() =>
  PROCESS_ROUTE_STATUS_OPTIONS.map((item) => ({ ...item, label: t(processStatusLocaleKey(item.value)) })),
);

watch(
  () => [props.visible, props.mode, props.route] as const,
  ([visible]) => {
    if (!visible) return;
    resetForm();
  },
  { immediate: true },
);

function resetForm(): void {
  const routeDetail = props.mode === 'edit' ? props.route : null;
  Object.assign(form, createEmptyRoutePayload(), {
    code: routeDetail?.route.code || '',
    name: routeDetail?.route.name || '',
    input_material_id: routeDetail?.route.input_material_id ?? null,
    final_product_id: routeDetail?.route.final_product_id ?? null,
    version: routeDetail?.route.version || 'V1',
    description: routeDetail?.route.description || '',
    status: routeDetail?.route.status || 'enabled',
    sort_order: routeDetail?.route.sort_order ?? 0,
    remark: routeDetail?.route.remark || '',
    nodes: (routeDetail?.nodes || [])
      .slice()
      .sort((left, right) => left.sort_order - right.sort_order || left.id - right.id)
      .map<RouteEditableNode>((item, index) => ({
        local_key: `route-node-${item.id}`,
        route_node_id: item.id,
        node_id: item.node_id,
        sort_order: index + 1,
        node_params_json: item.node_params_json || '',
        remark: item.remark || '',
      })),
  });
  outputRows.value = props.calculationOutputs.map((item) => ({ ...item }));
}

function addOutput(): void {
  outputRows.value.push({ output_type: 'product', product_id: form.final_product_id, output_name: '', formula_type: 'fixed', recovery_rate: 1, balance_weight: 0, unit: 't/t-BM', output_ratio: 0, treatment_cost: 0, sort_order: outputRows.value.length + 1 });
}

function removeOutput(index: number): void { outputRows.value.splice(index, 1); }

function closeDrawer(): void {
  if (props.saving) return;
  visibleProxy.value = false;
}

function normalizeOptionalText(value?: string | null): string | null {
  const text = value?.trim();
  return text || null;
}

function validateRequired(value: string | undefined | null, message: string): boolean {
  if (value?.trim()) return true;
  MessagePlugin.warning(message);
  return false;
}

function validateNodeRows(rows: RouteEditableNode[]): boolean {
  return rows.every((row, index) => {
    if (row.node_id) return true;
    MessagePlugin.warning(t('process.route.message.nodeRowRequired', { row: index + 1 }));
    return false;
  });
}

function buildPayload(): ProcessRoutePayload {
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    input_material_id: Number(form.input_material_id),
    final_product_id: Number(form.final_product_id),
    version: form.version.trim(),
    description: normalizeOptionalText(form.description),
    status: form.status,
    sort_order: Number(form.sort_order || 0),
    remark: normalizeOptionalText(form.remark),
    nodes: form.nodes.map((row, index) => ({
      node_id: Number(row.node_id),
      sort_order: index + 1,
      node_params_json: normalizeOptionalText(row.node_params_json),
      remark: normalizeOptionalText(row.remark),
    })),
  };
}

function handleSubmit(): void {
  if (!validateRequired(form.code, t('process.route.message.codeRequired'))) return;
  if (!validateRequired(form.name, t('process.route.message.nameRequired'))) return;
  if (!form.input_material_id) {
    MessagePlugin.warning(t('process.route.message.inputMaterialRequired'));
    return;
  }
  if (!form.final_product_id) {
    MessagePlugin.warning(t('process.route.message.finalProductRequired'));
    return;
  }
  if (!validateRequired(form.version, t('process.route.message.versionRequired'))) return;
  if (form.status === 'enabled' && form.nodes.length === 0) {
    MessagePlugin.warning(t('process.route.message.nodeRequired'));
    return;
  }
  if (!validateNodeRows(form.nodes as RouteEditableNode[])) return;
  const outputs = outputRows.value.map((row, index) => {
    const product = props.productOptions.find((item) => item.id === row.product_id);
    return { ...row, output_name: row.output_name.trim() || product?.name || '', sort_order: index + 1 };
  });
  if (outputs.some((row) => !row.product_id || !row.output_name || Number(row.output_ratio) < 0 || !row.unit.trim())) {
    MessagePlugin.warning(t('process.route.message.outputConfigRequired'));
    return;
  }
  emit('submit', buildPayload(), outputs);
}

function outputTypeLabel(value: string): string {
  const key = processOutputTypeLocaleKey(value);
  return key ? t(key) : value;
}

function formulaTypeLabel(value: string): string {
  const key = processFormulaTypeLocaleKey(value);
  return key ? t(key) : value;
}
</script>

<template>
  <t-drawer
    v-model:visible="visibleProxy"
    class="route-form-drawer drawer-scroll"
    destroy-on-close
    :close-on-esc-keydown="!saving"
    :close-on-overlay-click="!saving"
    :header="drawerTitle"
    placement="right"
    size="min(1080px, 96vw)"
  >
    <t-loading :loading="optionsLoading">
      <t-form :data="form" class="route-form" label-align="top">
        <section class="route-form__section">
          <div class="route-form__section-title">{{ t('process.route.section.baseInfo') }}</div>
          <div class="route-form__grid">
            <t-form-item :label="t('process.route.field.routeCode')" required-mark>
              <t-input v-model="form.code" clearable maxlength="100" :placeholder="t('process.route.placeholder.code')" />
            </t-form-item>
            <t-form-item :label="t('process.route.field.routeName')" required-mark>
              <t-input v-model="form.name" clearable maxlength="150" :placeholder="t('process.route.placeholder.name')" />
            </t-form-item>
            <t-form-item :label="t('process.route.field.inputMaterial')" required-mark>
              <t-select v-model="form.input_material_id" filterable clearable :placeholder="t('process.route.placeholder.inputMaterial')">
                <t-option
                  v-for="item in materialOptions"
                  :key="item.id"
                  :label="`${item.code} / ${item.name}`"
                  :value="item.id"
                />
              </t-select>
            </t-form-item>
            <t-form-item :label="t('process.route.field.finalProduct')" required-mark>
              <t-select v-model="form.final_product_id" filterable clearable :placeholder="t('process.route.placeholder.finalProduct')">
                <t-option
                  v-for="item in productOptions"
                  :key="item.id"
                  :label="`${item.code} / ${item.name}`"
                  :value="item.id"
                />
              </t-select>
            </t-form-item>
            <t-form-item :label="t('process.route.field.version')" required-mark>
              <t-input v-model="form.version" clearable maxlength="50" :placeholder="t('process.route.placeholder.version')" />
            </t-form-item>
            <t-form-item :label="t('common.field.status')" required-mark>
              <t-radio-group v-model="form.status">
                <t-radio-button v-for="item in statusOptions" :key="item.value" :value="item.value">{{ item.label }}</t-radio-button>
              </t-radio-group>
            </t-form-item>
            <t-form-item :label="t('process.field.sort')">
              <t-input-number v-model="form.sort_order" :min="0" :max="999999" :step="1" theme="normal" />
            </t-form-item>
          </div>
          <t-form-item :label="t('process.field.description')">
            <t-textarea v-model="form.description" maxlength="1000" :autosize="{ minRows: 2, maxRows: 4 }" :placeholder="t('process.route.placeholder.description')" />
          </t-form-item>
          <t-form-item :label="t('process.field.remark')">
            <t-textarea v-model="form.remark" maxlength="500" :autosize="{ minRows: 2, maxRows: 4 }" :placeholder="t('process.placeholder.remark')" />
          </t-form-item>
        </section>

        <section class="route-form__section">
          <div class="route-form__section-head"><div class="route-form__section-title">{{ t('process.route.section.calculationOutputs') }}</div><t-button size="small" variant="outline" @click="addOutput">{{ t('process.route.action.addOutput') }}</t-button></div>
          <div class="route-output-table"><t-table row-key="sort_order" bordered size="small" table-layout="fixed" :columns="outputColumns" :data="outputRows">
            <template #product_id="{ row }"><t-select v-model="row.product_id" filterable><t-option v-for="item in productOptions" :key="item.id" :label="`${item.code} / ${item.name}`" :value="item.id" /></t-select></template>
            <template #output_type="{ row }"><t-select v-model="row.output_type"><t-option :label="outputTypeLabel('product')" value="product" /><t-option :label="outputTypeLabel('byproduct')" value="byproduct" /></t-select></template>
            <template #output_ratio="{ row }"><t-input-number v-model="row.output_ratio" :min="0" :decimal-places="6" theme="normal" /></template>
            <template #unit="{ row }"><t-input v-model="row.unit" /></template>
            <template #recovery_rate="{ row }"><t-input-number v-model="row.recovery_rate" :min="0" :decimal-places="6" theme="normal" /></template>
            <template #formula_type="{ row }"><t-select v-model="row.formula_type"><t-option :label="formulaTypeLabel('fixed')" value="fixed" /><t-option :label="formulaTypeLabel('expression')" value="expression" /></t-select></template>
            <template #expression="{ row }"><t-input v-model="row.expression" :placeholder="t('process.placeholder.optional')" /></template>
            <template #operation="{ rowIndex }"><t-button shape="square" theme="danger" variant="text" @click="removeOutput(rowIndex)">×</t-button></template>
          </t-table></div>
        </section>

        <section class="route-form__section">
          <div class="route-form__section-title">{{ t('process.route.section.nodeChain') }}</div>
          <RouteNodeChainEditor v-model="form.nodes as RouteEditableNode[]" :node-options="nodeOptions" :disabled="saving" />
        </section>
      </t-form>
    </t-loading>

    <template #footer>
      <div class="route-form__footer">
        <t-button variant="outline" :disabled="saving" @click="closeDrawer">{{ t('common.action.cancel') }}</t-button>
        <t-button theme="primary" :loading="saving" @click="handleSubmit">{{ submitText }}</t-button>
      </div>
    </template>
  </t-drawer>
</template>

<style scoped>
.route-form-drawer :deep(.t-drawer__body) {
  background: #f8fafc;
  padding: 18px;
}

.route-form {
  display: grid;
  gap: 16px;
}

.route-form__section {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
}

.route-form__section-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
  line-height: 1.4;
}
.route-form__section-head { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.route-output-table { overflow-x: auto; }
.route-output-table :deep(.t-table) { min-width: 1120px; }

.route-form__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}

.route-form__footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  width: 100%;
}

@media (max-width: 760px) {
  .route-form__grid {
    grid-template-columns: 1fr;
  }
}
</style>
