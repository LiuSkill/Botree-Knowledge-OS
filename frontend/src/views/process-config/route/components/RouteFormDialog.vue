<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, ref, watch } from 'vue';

import type { ProcessLibraryOptionItem } from '@/views/process-config/node/types';
import { createEmptyRoutePayload, PROCESS_ROUTE_STATUS_OPTIONS, type ProcessCalculationOutputPayload, type ProcessRouteDetail, type ProcessRoutePayload, type RouteEditableNode, type RouteNodeOption } from '@/views/process-config/route/types';
import RouteNodeChainEditor from '@/views/process-config/route/components/RouteNodeChainEditor.vue';

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

const form = reactive<ProcessRoutePayload>(createEmptyRoutePayload());
const outputRows = ref<ProcessCalculationOutputPayload[]>([]);
const outputColumns = [
  { colKey: 'product_id', title: '产出物', minWidth: 180 }, { colKey: 'output_type', title: '类型', width: 110 },
  { colKey: 'output_ratio', title: '最终产出系数', width: 150 }, { colKey: 'unit', title: '单位', width: 120 },
  { colKey: 'recovery_rate', title: '收率（追溯）', width: 130 }, { colKey: 'formula_type', title: '系数类型', width: 110 },
  { colKey: 'expression', title: '来源表达式', minWidth: 170 }, { colKey: 'operation', title: '操作', width: 70 },
];

const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const drawerTitle = computed(() => (props.mode === 'create' ? '新增工艺路线' : '编辑工艺路线'));
const submitText = computed(() => (props.mode === 'create' ? '创建路线' : '保存修改'));

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
    MessagePlugin.warning(`请为第 ${index + 1} 个路线节点选择工艺节点`);
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
  if (!validateRequired(form.code, '请输入路线编码')) return;
  if (!validateRequired(form.name, '请输入路线名称')) return;
  if (!form.input_material_id) {
    MessagePlugin.warning('请选择输入原料');
    return;
  }
  if (!form.final_product_id) {
    MessagePlugin.warning('请选择最终产品');
    return;
  }
  if (!validateRequired(form.version, '请输入版本号')) return;
  if (form.status === 'enabled' && form.nodes.length === 0) {
    MessagePlugin.warning('启用路线至少需要配置一个节点');
    return;
  }
  if (!validateNodeRows(form.nodes as RouteEditableNode[])) return;
  const outputs = outputRows.value.map((row, index) => {
    const product = props.productOptions.find((item) => item.id === row.product_id);
    return { ...row, output_name: row.output_name.trim() || product?.name || '', sort_order: index + 1 };
  });
  if (outputs.some((row) => !row.product_id || !row.output_name || Number(row.output_ratio) < 0 || !row.unit.trim())) {
    MessagePlugin.warning('请完整填写路线测算产出配置');
    return;
  }
  emit('submit', buildPayload(), outputs);
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
          <div class="route-form__section-title">基础信息</div>
          <div class="route-form__grid">
            <t-form-item label="路线编码" required-mark>
              <t-input v-model="form.code" clearable maxlength="100" placeholder="请输入唯一路线编码" />
            </t-form-item>
            <t-form-item label="路线名称" required-mark>
              <t-input v-model="form.name" clearable maxlength="150" placeholder="请输入路线名称" />
            </t-form-item>
            <t-form-item label="输入原料" required-mark>
              <t-select v-model="form.input_material_id" filterable clearable placeholder="请选择输入原料">
                <t-option
                  v-for="item in materialOptions"
                  :key="item.id"
                  :label="`${item.code} / ${item.name}`"
                  :value="item.id"
                />
              </t-select>
            </t-form-item>
            <t-form-item label="最终产品" required-mark>
              <t-select v-model="form.final_product_id" filterable clearable placeholder="请选择最终产品">
                <t-option
                  v-for="item in productOptions"
                  :key="item.id"
                  :label="`${item.code} / ${item.name}`"
                  :value="item.id"
                />
              </t-select>
            </t-form-item>
            <t-form-item label="版本号" required-mark>
              <t-input v-model="form.version" clearable maxlength="50" placeholder="例如 V1" />
            </t-form-item>
            <t-form-item label="状态" required-mark>
              <t-radio-group v-model="form.status">
                <t-radio-button v-for="item in PROCESS_ROUTE_STATUS_OPTIONS" :key="item.value" :value="item.value">{{ item.label }}</t-radio-button>
              </t-radio-group>
            </t-form-item>
            <t-form-item label="排序">
              <t-input-number v-model="form.sort_order" :min="0" :max="999999" :step="1" theme="normal" />
            </t-form-item>
          </div>
          <t-form-item label="描述">
            <t-textarea v-model="form.description" maxlength="1000" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="请输入路线描述" />
          </t-form-item>
          <t-form-item label="备注">
            <t-textarea v-model="form.remark" maxlength="500" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="请输入备注" />
          </t-form-item>
        </section>

        <section class="route-form__section">
          <div class="route-form__section-head"><div class="route-form__section-title">测算产出配置</div><t-button size="small" variant="outline" @click="addOutput">新增产出</t-button></div>
          <div class="route-output-table"><t-table row-key="sort_order" bordered size="small" table-layout="fixed" :columns="outputColumns" :data="outputRows">
            <template #product_id="{ row }"><t-select v-model="row.product_id" filterable><t-option v-for="item in productOptions" :key="item.id" :label="`${item.code} / ${item.name}`" :value="item.id" /></t-select></template>
            <template #output_type="{ row }"><t-select v-model="row.output_type"><t-option label="产品" value="product" /><t-option label="副产品" value="byproduct" /></t-select></template>
            <template #output_ratio="{ row }"><t-input-number v-model="row.output_ratio" :min="0" :decimal-places="6" theme="normal" /></template>
            <template #unit="{ row }"><t-input v-model="row.unit" /></template>
            <template #recovery_rate="{ row }"><t-input-number v-model="row.recovery_rate" :min="0" :decimal-places="6" theme="normal" /></template>
            <template #formula_type="{ row }"><t-select v-model="row.formula_type"><t-option label="固定系数" value="fixed" /><t-option label="导入表达式" value="expression" /></t-select></template>
            <template #expression="{ row }"><t-input v-model="row.expression" placeholder="可选" /></template>
            <template #operation="{ rowIndex }"><t-button shape="square" theme="danger" variant="text" @click="removeOutput(rowIndex)">×</t-button></template>
          </t-table></div>
        </section>

        <section class="route-form__section">
          <div class="route-form__section-title">节点链路配置</div>
          <RouteNodeChainEditor v-model="form.nodes as RouteEditableNode[]" :node-options="nodeOptions" :disabled="saving" />
        </section>
      </t-form>
    </t-loading>

    <template #footer>
      <div class="route-form__footer">
        <t-button variant="outline" :disabled="saving" @click="closeDrawer">取消</t-button>
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
