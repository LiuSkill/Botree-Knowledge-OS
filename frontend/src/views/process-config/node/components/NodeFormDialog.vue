<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, watch } from 'vue';

import NodeConsumableEditor from '@/views/process-config/node/components/NodeConsumableEditor.vue';
import NodeEquipmentEditor from '@/views/process-config/node/components/NodeEquipmentEditor.vue';
import NodeMaterialInputEditor from '@/views/process-config/node/components/NodeMaterialInputEditor.vue';
import NodeOutputEditor from '@/views/process-config/node/components/NodeOutputEditor.vue';
import NodePublicServiceEditor from '@/views/process-config/node/components/NodePublicServiceEditor.vue';
import type { ProcessLibraryStatus } from '@/views/process-config/types';
import type {
  ProcessLibraryOptionItem,
  ProcessNodeConsumablePayload,
  ProcessNodeDetail,
  ProcessNodeEquipmentPayload,
  ProcessNodeMaterialInputPayload,
  ProcessNodeOutputPayload,
  ProcessNodePayload,
  ProcessNodePublicServicePayload,
  ProcessNodeType,
} from '@/views/process-config/node/types';
import { PROCESS_NODE_TYPE_OPTIONS } from '@/views/process-config/node/types';

type FormMode = 'create' | 'edit';

const props = withDefaults(
  defineProps<{
    visible: boolean;
    mode: FormMode;
    node?: ProcessNodeDetail | null;
    saving?: boolean;
    optionsLoading?: boolean;
    materialOptions: ProcessLibraryOptionItem[];
    productOptions: ProcessLibraryOptionItem[];
    consumableOptions: ProcessLibraryOptionItem[];
    publicServiceOptions: ProcessLibraryOptionItem[];
  }>(),
  {
    node: null,
    saving: false,
    optionsLoading: false,
  },
);

const emit = defineEmits<{
  'update:visible': [value: boolean];
  submit: [payload: ProcessNodePayload];
}>();

const form = reactive<ProcessNodePayload>({
  code: '',
  name: '',
  node_type: 'pretreatment',
  staff: 0,
  area: 0,
  description: '',
  status: 'draft',
  version: 'v1.0',
  sort_order: 0,
  remark: '',
  material_inputs: [],
  consumables: [],
  public_services: [],
  equipment: [],
  outputs: [],
});

const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const drawerTitle = computed(() => (props.mode === 'create' ? '新增工艺节点' : '编辑工艺节点'));
const submitText = computed(() => (props.mode === 'create' ? '创建节点' : '保存修改'));

watch(
  () => [props.visible, props.mode, props.node] as const,
  ([visible]) => {
    if (!visible) return;
    resetForm();
  },
  { immediate: true },
);

function resetForm(): void {
  const node = props.mode === 'edit' ? props.node : null;
  Object.assign(form, {
    code: node?.code || '',
    name: node?.name || '',
    node_type: node?.node_type || 'pretreatment',
    staff: node?.staff ?? 0,
    area: node?.area ?? 0,
    description: node?.description || '',
    status: node?.status || 'draft',
    version: node?.version || 'v1.0',
    sort_order: node?.sort_order ?? 0,
    remark: node?.remark || '',
    material_inputs: (node?.material_inputs || []).map((item) => ({
      material_id: item.material_id,
      amount_per_ton: item.amount_per_ton,
      unit: item.unit,
      sort_order: item.sort_order,
      remark: item.remark || '',
    })),
    consumables: (node?.consumables || []).map((item) => ({
      consumable_id: item.consumable_id,
      amount_per_ton: item.amount_per_ton,
      unit: item.unit,
      sort_order: item.sort_order,
      remark: item.remark || '',
    })),
    public_services: (node?.public_services || []).map((item) => ({
      public_service_id: item.public_service_id,
      amount_per_ton: item.amount_per_ton,
      unit: item.unit,
      sort_order: item.sort_order,
      remark: item.remark || '',
    })),
    equipment: (node?.equipment || []).map((item) => ({
      equipment_name: item.equipment_name,
      equipment_type: item.equipment_type || '',
      quantity: item.quantity,
      investment_amount: item.investment_amount,
      currency: item.currency,
      sort_order: item.sort_order,
      remark: item.remark || '',
    })),
    outputs: (node?.outputs || []).map((item) => ({
      product_id: item.product_id,
      output_per_ton: item.output_per_ton,
      unit: item.unit,
      is_main_product: item.is_main_product,
      sort_order: item.sort_order,
      remark: item.remark || '',
    })),
  });
}

function closeDrawer(): void {
  if (props.saving) return;
  visibleProxy.value = false;
}

function normalizeDecimal(value: string | number | null | undefined): string {
  const rawValue = String(value ?? '').trim();
  return rawValue || '0';
}

function normalizeOptionalText(value?: string | null): string | null {
  const rawValue = value?.trim();
  return rawValue || null;
}

function isNonNegativeDecimal(value: string | number | null | undefined): boolean {
  const rawValue = String(value ?? '').trim();
  if (!rawValue) return false;
  const numberValue = Number(rawValue);
  return Number.isFinite(numberValue) && numberValue >= 0;
}

function validateRequired(value: string | undefined | null, message: string): boolean {
  if (value?.trim()) return true;
  MessagePlugin.warning(message);
  return false;
}

function validateDecimal(value: string | number | null | undefined, message: string): boolean {
  if (isNonNegativeDecimal(value)) return true;
  MessagePlugin.warning(message);
  return false;
}

function validateMaterialInputs(rows: ProcessNodeMaterialInputPayload[]): boolean {
  return rows.every((row, index) => {
    const label = `第 ${index + 1} 行输入原料`;
    if (!row.material_id) return warnInvalid(`${label}请选择原料`);
    if (!validateDecimal(row.amount_per_ton, `${label}吨耗必须为非负数`)) return false;
    if (!row.unit.trim()) return warnInvalid(`${label}请输入单位`);
    return true;
  });
}

function validateConsumables(rows: ProcessNodeConsumablePayload[]): boolean {
  return rows.every((row, index) => {
    const label = `第 ${index + 1} 行消耗品`;
    if (!row.consumable_id) return warnInvalid(`${label}请选择消耗品`);
    if (!validateDecimal(row.amount_per_ton, `${label}吨耗必须为非负数`)) return false;
    if (!row.unit.trim()) return warnInvalid(`${label}请输入单位`);
    return true;
  });
}

function validatePublicServices(rows: ProcessNodePublicServicePayload[]): boolean {
  return rows.every((row, index) => {
    const label = `第 ${index + 1} 行公共服务`;
    if (!row.public_service_id) return warnInvalid(`${label}请选择公共服务`);
    if (!validateDecimal(row.amount_per_ton, `${label}吨耗必须为非负数`)) return false;
    if (!row.unit.trim()) return warnInvalid(`${label}请输入单位`);
    return true;
  });
}

function validateEquipment(rows: ProcessNodeEquipmentPayload[]): boolean {
  return rows.every((row, index) => {
    const label = `第 ${index + 1} 行设备`;
    if (!row.equipment_name.trim()) return warnInvalid(`${label}请输入设备名称`);
    if (!validateDecimal(row.quantity, `${label}数量必须为非负数`)) return false;
    if (!validateDecimal(row.investment_amount, `${label}投资额必须为非负数`)) return false;
    if (!row.currency.trim()) return warnInvalid(`${label}请选择币种`);
    return true;
  });
}

function validateOutputs(rows: ProcessNodeOutputPayload[]): boolean {
  return rows.every((row, index) => {
    const label = `第 ${index + 1} 行输出产品`;
    if (!row.product_id) return warnInvalid(`${label}请选择产品`);
    if (!validateDecimal(row.output_per_ton, `${label}产出量必须为非负数`)) return false;
    if (!row.unit.trim()) return warnInvalid(`${label}请输入单位`);
    return true;
  });
}

function warnInvalid(message: string): false {
  MessagePlugin.warning(message);
  return false;
}

function buildPayload(): ProcessNodePayload {
  return {
    code: form.code.trim(),
    name: form.name.trim(),
    node_type: form.node_type as ProcessNodeType,
    staff: normalizeDecimal(form.staff),
    area: normalizeDecimal(form.area),
    description: normalizeOptionalText(form.description),
    status: form.status as ProcessLibraryStatus,
    version: form.version.trim(),
    sort_order: Number(form.sort_order || 0),
    remark: normalizeOptionalText(form.remark),
    material_inputs: form.material_inputs.map((row, index) => ({
      material_id: Number(row.material_id),
      amount_per_ton: normalizeDecimal(row.amount_per_ton),
      unit: row.unit.trim(),
      sort_order: Number(row.sort_order ?? index + 1),
      remark: normalizeOptionalText(row.remark),
    })),
    consumables: form.consumables.map((row, index) => ({
      consumable_id: Number(row.consumable_id),
      amount_per_ton: normalizeDecimal(row.amount_per_ton),
      unit: row.unit.trim(),
      sort_order: Number(row.sort_order ?? index + 1),
      remark: normalizeOptionalText(row.remark),
    })),
    public_services: form.public_services.map((row, index) => ({
      public_service_id: Number(row.public_service_id),
      amount_per_ton: normalizeDecimal(row.amount_per_ton),
      unit: row.unit.trim(),
      sort_order: Number(row.sort_order ?? index + 1),
      remark: normalizeOptionalText(row.remark),
    })),
    equipment: form.equipment.map((row, index) => ({
      equipment_name: row.equipment_name.trim(),
      equipment_type: normalizeOptionalText(row.equipment_type),
      quantity: normalizeDecimal(row.quantity),
      investment_amount: normalizeDecimal(row.investment_amount),
      currency: row.currency.trim(),
      sort_order: Number(row.sort_order ?? index + 1),
      remark: normalizeOptionalText(row.remark),
    })),
    outputs: form.outputs.map((row, index) => ({
      product_id: Number(row.product_id),
      output_per_ton: normalizeDecimal(row.output_per_ton),
      unit: row.unit.trim(),
      is_main_product: Boolean(row.is_main_product),
      sort_order: Number(row.sort_order ?? index + 1),
      remark: normalizeOptionalText(row.remark),
    })),
  };
}

function handleSubmit(): void {
  if (!validateRequired(form.code, '请输入节点编码')) return;
  if (!validateRequired(form.name, '请输入节点名称')) return;
  if (!validateRequired(form.version, '请输入版本号')) return;
  if (!validateDecimal(form.staff, '人员数量必须为非负数')) return;
  if (!validateDecimal(form.area, '占地面积必须为非负数')) return;
  if (form.status === 'enabled' && form.outputs.length === 0) {
    MessagePlugin.warning('启用节点至少需要配置一个输出产品');
    return;
  }
  if (!validateMaterialInputs(form.material_inputs)) return;
  if (!validateConsumables(form.consumables)) return;
  if (!validatePublicServices(form.public_services)) return;
  if (!validateEquipment(form.equipment)) return;
  if (!validateOutputs(form.outputs)) return;

  emit('submit', buildPayload());
}
</script>

<template>
  <t-drawer
    v-model:visible="visibleProxy"
    class="node-form-drawer drawer-scroll"
    :close-on-esc-keydown="!saving"
    :close-on-overlay-click="!saving"
    destroy-on-close
    :header="drawerTitle"
    placement="right"
    size="min(1080px, 96vw)"
  >
    <t-loading :loading="optionsLoading">
      <t-form :data="form" label-align="top" class="node-form">
        <section class="node-form-section">
          <div class="node-form-section-title">基础信息</div>
          <div class="node-form-grid">
            <t-form-item label="节点编码" required-mark>
              <t-input v-model="form.code" clearable maxlength="80" placeholder="请输入唯一节点编码" />
            </t-form-item>
            <t-form-item label="节点名称" required-mark>
              <t-input v-model="form.name" clearable maxlength="200" placeholder="请输入节点名称" />
            </t-form-item>
            <t-form-item label="节点类型" required-mark>
              <t-select v-model="form.node_type" placeholder="请选择节点类型">
                <t-option v-for="item in PROCESS_NODE_TYPE_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
              </t-select>
            </t-form-item>
            <t-form-item label="版本号" required-mark>
              <t-input v-model="form.version" clearable maxlength="50" placeholder="例如 v1.0" />
            </t-form-item>
            <t-form-item label="人员" required-mark>
              <t-input-number v-model="form.staff" :min="0" :step="1" theme="normal" />
            </t-form-item>
            <t-form-item label="占地面积" required-mark>
              <t-input-number v-model="form.area" :min="0" :step="1" theme="normal" />
            </t-form-item>
            <t-form-item label="状态" required-mark>
              <t-radio-group v-model="form.status">
                <t-radio-button value="enabled">启用</t-radio-button>
                <t-radio-button value="draft">草稿</t-radio-button>
                <t-radio-button value="disabled">停用</t-radio-button>
              </t-radio-group>
            </t-form-item>
            <t-form-item label="排序" required-mark>
              <t-input-number v-model="form.sort_order" :min="0" :max="999999" :step="1" theme="normal" />
            </t-form-item>
          </div>
          <t-form-item label="描述">
            <t-textarea v-model="form.description" maxlength="1000" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="请输入节点描述" />
          </t-form-item>
          <t-form-item label="备注">
            <t-textarea v-model="form.remark" maxlength="500" :autosize="{ minRows: 2, maxRows: 4 }" placeholder="请输入备注" />
          </t-form-item>
        </section>

        <section class="node-form-section">
          <div class="node-form-section-title">输入原料</div>
          <NodeMaterialInputEditor v-model="form.material_inputs" :options="materialOptions" :disabled="saving" />
        </section>

        <section class="node-form-section">
          <div class="node-form-section-title">消耗品</div>
          <NodeConsumableEditor v-model="form.consumables" :options="consumableOptions" :disabled="saving" />
        </section>

        <section class="node-form-section">
          <div class="node-form-section-title">公共服务</div>
          <NodePublicServiceEditor v-model="form.public_services" :options="publicServiceOptions" :disabled="saving" />
        </section>

        <section class="node-form-section">
          <div class="node-form-section-title">设备/投资</div>
          <NodeEquipmentEditor v-model="form.equipment" :disabled="saving" />
        </section>

        <section class="node-form-section">
          <div class="node-form-section-title">输出产品</div>
          <NodeOutputEditor v-model="form.outputs" :options="productOptions" :disabled="saving" />
        </section>
      </t-form>
    </t-loading>

    <template #footer>
      <div class="node-form-footer">
        <t-button variant="outline" :disabled="saving" @click="closeDrawer">取消</t-button>
        <t-button theme="primary" :loading="saving" @click="handleSubmit">{{ submitText }}</t-button>
      </div>
    </template>
  </t-drawer>
</template>

<style scoped>
.node-form-drawer :deep(.t-drawer__body) {
  background: #f8fafc;
  padding: 18px;
}

.node-form {
  display: grid;
  gap: 16px;
}

.node-form-section {
  display: grid;
  gap: 12px;
  min-width: 0;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
}

.node-form-section-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
  line-height: 1.4;
}

.node-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 18px;
}

.node-form-footer {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  width: 100%;
}

@media (max-width: 760px) {
  .node-form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
