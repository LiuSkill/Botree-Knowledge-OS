<!--
  Model Config Page

  负责：
  1. 展示模型配置分页表格
  2. 支持模型配置筛选、新增、编辑、启停、设默认、测试和删除
  3. 对接后端模型配置 API，避免前端硬编码模型参数
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { CheckCircleIcon, DeleteIcon, EditIcon, PlayCircleIcon, PoweroffIcon, RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import {
  createModelConfig,
  deleteModelConfig,
  listModelConfigs,
  setDefaultModelConfig,
  testModelConfig,
  updateModelConfig,
} from '@/api/modelConfigs';
import type { ModelConfigListParams } from '@/api/modelConfigs';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import type { ModelConfig, PageResult } from '@/types/api';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

type ModelDialogMode = 'create' | 'edit';
type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const MODEL_TYPE_LABEL_KEYS: Record<string, string> = {
  llm: 'system.model.type.llm',
  intent: 'system.model.type.intent',
  planner: 'system.model.type.planner',
  evidence_judge_fast: 'system.model.type.evidenceJudgeFast',
  evidence_judge: 'system.model.type.evidenceJudge',
  answer_llm: 'system.model.type.answerLlm',
  vision_llm: 'system.model.type.visionLlm',
  analysis_llm: 'system.model.type.analysisLlm',
  embedding: 'system.model.type.embedding',
};

const { t } = useI18n();
const configs = ref<PageResult<ModelConfig>>(createEmptyPageResult<ModelConfig>());
const loading = ref(false);
const dialogVisible = ref(false);
const dialogMode = ref<ModelDialogMode>('create');
const editingConfigId = ref<number | null>(null);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const filters = reactive({
  keyword: '',
  model_type: '',
  enabled: '',
  is_default: '',
});
const form = reactive({
  provider: '',
  model_name: '',
  api_base: '',
  api_key: '',
  model_type: 'llm',
  is_default: false,
  enabled: true,
});

const dialogTitle = computed(() => (dialogMode.value === 'create' ? t('system.model.createTitle') : t('system.model.editTitle')));
const modelTypeOptions = computed(() =>
  Object.entries(MODEL_TYPE_LABEL_KEYS).map(([value, labelKey]) => ({ value, label: t(labelKey) })),
);

const columns = computed(() => [
  { colKey: 'provider', title: t('system.model.field.provider'), width: 140 },
  { colKey: 'model_name', title: t('system.model.field.model'), minWidth: 180 },
  { colKey: 'model_type', title: t('common.field.type'), width: 150 },
  { colKey: 'api_base', title: 'API Base', minWidth: 220 },
  { colKey: 'is_default', title: t('system.model.field.default'), width: 90 },
  { colKey: 'enabled', title: t('common.field.status'), width: 90 },
  { colKey: 'operation', title: t('common.field.operation'), width: 180, fixed: 'right' as const },
]);

function createEmptyPageResult<T>(): PageResult<T> {
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: DEFAULT_PAGE_SIZE,
  };
}

function buildListParams(): ModelConfigListParams {
  const params: ModelConfigListParams = {
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.model_type) params.model_type = filters.model_type;
  if (filters.enabled) params.enabled = filters.enabled === 'enabled';
  if (filters.is_default) params.is_default = filters.is_default === 'default';
  return params;
}

async function loadConfigs(): Promise<void> {
  loading.value = true;
  try {
    const result = await listModelConfigs(buildListParams());
    configs.value = result;
    page.value = result.page;
    pageSize.value = result.page_size;
  } finally {
    loading.value = false;
  }
}

async function reloadAfterMutation(): Promise<void> {
  if (configs.value.items.length === 1 && page.value > 1) {
    page.value -= 1;
  }
  await loadConfigs();
}

function resetForm(): void {
  Object.assign(form, {
    provider: '',
    model_name: '',
    api_base: '',
    api_key: '',
    model_type: 'llm',
    is_default: false,
    enabled: true,
  });
  editingConfigId.value = null;
}

function openCreateDialog(): void {
  dialogMode.value = 'create';
  resetForm();
  dialogVisible.value = true;
}

function openEditDialog(config: ModelConfig): void {
  dialogMode.value = 'edit';
  editingConfigId.value = config.id;
  Object.assign(form, {
    provider: config.provider,
    model_name: config.model_name,
    api_base: config.api_base || '',
    api_key: '',
    model_type: config.model_type,
    is_default: config.is_default,
    enabled: config.enabled,
  });
  dialogVisible.value = true;
}

function buildSubmitPayload(): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    provider: form.provider,
    model_name: form.model_name,
    api_base: form.api_base || null,
    model_type: form.model_type,
    is_default: form.is_default,
    enabled: form.enabled,
  };
  if (dialogMode.value === 'create' || form.api_key.trim()) {
    payload.api_key = form.api_key || null;
  }
  return payload;
}

async function handleSubmit(): Promise<void> {
  if (dialogMode.value === 'create') {
    await createModelConfig(buildSubmitPayload());
    MessagePlugin.success(t('system.model.message.created'));
  } else if (editingConfigId.value) {
    await updateModelConfig(editingConfigId.value, buildSubmitPayload());
    MessagePlugin.success(t('system.model.message.updated'));
  }
  dialogVisible.value = false;
  await loadConfigs();
}

async function toggleEnabled(config: ModelConfig): Promise<void> {
  await updateModelConfig(config.id, { enabled: !config.enabled });
  MessagePlugin.success(config.enabled ? t('system.model.message.disabled') : t('system.model.message.enabled'));
  await loadConfigs();
}

async function handleSetDefault(config: ModelConfig): Promise<void> {
  await setDefaultModelConfig(config.id);
  MessagePlugin.success(t('system.model.message.defaultUpdated'));
  await loadConfigs();
}

async function handleTest(config: ModelConfig): Promise<void> {
  await testModelConfig(config.id);
  MessagePlugin.success(t('system.model.message.testPassed'));
}

async function handleDelete(config: ModelConfig): Promise<void> {
  await deleteModelConfig(config.id);
  MessagePlugin.success(t('system.model.message.deleted'));
  await reloadAfterMutation();
}

function handleSearch(): void {
  page.value = 1;
  void loadConfigs();
}

function clearFilters(): void {
  Object.assign(filters, { keyword: '', model_type: '', enabled: '', is_default: '' });
  page.value = 1;
  void loadConfigs();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  void loadConfigs();
}

function statusTheme(enabled: boolean): TagTheme {
  return enabled ? 'success' : 'danger';
}

function defaultTheme(isDefault: boolean): TagTheme {
  return isDefault ? 'primary' : 'default';
}

function modelTypeLabel(modelType: string): string {
  const key = MODEL_TYPE_LABEL_KEYS[modelType];
  return key ? t(key) : modelType;
}

onMounted(loadConfigs);
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item :label="t('system.model.field.keyword')">
        <t-input v-model="filters.keyword" class="filter-input" clearable :placeholder="t('system.model.placeholder.keyword')" @enter="handleSearch" />
      </t-form-item>
      <t-form-item :label="t('common.field.type')">
        <t-select v-model="filters.model_type" class="filter-select" clearable :placeholder="t('system.model.placeholder.allTypes')" @change="handleSearch">
          <t-option v-for="option in modelTypeOptions" :key="option.value" :value="option.value" :label="option.label" />
        </t-select>
      </t-form-item>
      <t-form-item :label="t('common.field.status')">
        <t-select v-model="filters.enabled" class="filter-select" clearable :placeholder="t('system.status.all')" @change="handleSearch">
          <t-option :label="t('system.status.enabled')" value="enabled" />
          <t-option :label="t('system.status.disabled')" value="disabled" />
        </t-select>
      </t-form-item>
      <t-form-item :label="t('system.model.field.default')">
        <t-select v-model="filters.is_default" class="filter-select" clearable :placeholder="t('system.model.placeholder.all')" @change="handleSearch">
          <t-option :label="t('system.model.value.default')" value="default" />
          <t-option :label="t('system.model.value.nonDefault')" value="normal" />
        </t-select>
      </t-form-item>
      <t-form-item>
        <t-space>
          <t-button theme="primary" @click="handleSearch">{{ t('system.action.query') }}</t-button>
          <t-button @click="clearFilters">{{ t('system.action.reset') }}</t-button>
        </t-space>
      </t-form-item>
    </t-form>

    <div class="system-section-head">
      <div class="system-section-title">
        <h2>{{ t('system.model.title') }}</h2>
        <span>{{ t('system.summary.totalRecords', { count: configs.total }) }}</span>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="loadConfigs">
          <template #icon><RefreshIcon /></template>
          {{ t('system.action.refresh') }}
        </t-button>
        <t-button v-permission="PERMISSIONS.SYSTEM_MODEL_CREATE" theme="primary" @click="openCreateDialog">{{ t('system.model.action.create') }}</t-button>
      </t-space>
    </div>

    <div class="table-scroll">
      <t-table
        row-key="id"
        bordered
        table-layout="fixed"
        :data="configs.items"
        :columns="columns"
        :loading="loading"
        :empty="t('system.model.empty')"
      >
        <template #model_type="{ row }">
          {{ modelTypeLabel(row.model_type) }}
        </template>
        <template #api_base="{ row }">
          {{ row.api_base || '-' }}
        </template>
        <template #is_default="{ row }">
          <t-tag size="small" variant="light" :theme="defaultTheme(row.is_default)">{{ row.is_default ? t('system.model.value.default') : t('system.model.value.normal') }}</t-tag>
        </template>
        <template #enabled="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.enabled)">{{ row.enabled ? t('system.status.enabled') : t('system.status.disabled') }}</t-tag>
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton :label="t('system.action.edit')" :permission="PERMISSIONS.SYSTEM_MODEL_EDIT" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <TableActionButton :label="row.enabled ? t('system.action.disable') : t('system.action.enable')" :permission="PERMISSIONS.SYSTEM_MODEL_EDIT" @click="toggleEnabled(row)">
              <PoweroffIcon />
            </TableActionButton>
            <TableActionButton :label="t('system.model.action.setDefault')" :permission="PERMISSIONS.SYSTEM_MODEL_SET_DEFAULT" :disabled="row.is_default" @click="handleSetDefault(row)">
              <CheckCircleIcon />
            </TableActionButton>
            <t-popconfirm :content="t('system.model.confirm.test')" @confirm="handleTest(row)">
              <TableActionButton :label="t('system.model.action.test')" :permission="PERMISSIONS.SYSTEM_MODEL_TEST">
                <PlayCircleIcon />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm :content="t('system.model.confirm.delete')" @confirm="handleDelete(row)">
              <TableActionButton :label="t('system.action.delete')" :permission="PERMISSIONS.SYSTEM_MODEL_DELETE" theme="danger">
                <DeleteIcon />
              </TableActionButton>
            </t-popconfirm>
          </t-space>
        </template>
      </t-table>
    </div>

    <div class="system-pagination">
      <t-pagination
        :current="page"
        :page-size="pageSize"
        :total="configs.total"
        :page-size-options="PAGE_SIZE_OPTIONS"
        show-jumper
        @change="handlePaginationChange"
      />
    </div>

    <t-dialog v-model:visible="dialogVisible" :header="dialogTitle" width="620px" @confirm="handleSubmit">
      <t-form :data="form" label-align="top">
        <t-form-item :label="t('system.model.field.provider')" required-mark><t-input v-model="form.provider" /></t-form-item>
        <t-form-item :label="t('system.model.field.modelName')" required-mark><t-input v-model="form.model_name" /></t-form-item>
        <t-form-item :label="t('system.model.field.modelType')" required-mark>
          <t-select v-model="form.model_type">
            <t-option v-for="option in modelTypeOptions" :key="option.value" :value="option.value" :label="option.label" />
          </t-select>
        </t-form-item>
        <t-form-item label="API Base"><t-input v-model="form.api_base" /></t-form-item>
        <t-form-item :label="dialogMode === 'create' ? 'API Key' : t('system.model.field.apiKeyKeep')">
          <t-input v-model="form.api_key" type="password" />
        </t-form-item>
        <t-form-item :label="t('system.model.field.defaultModel')"><t-switch v-model="form.is_default" /></t-form-item>
        <t-form-item :label="t('system.model.field.enabled')"><t-switch v-model="form.enabled" /></t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<style scoped>
.system-card {
  display: flex;
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  margin-top: 0;
  overflow: hidden;
}

.table-scroll {
  flex: 1 1 0;
  min-height: 240px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow: auto;
  scrollbar-gutter: auto;
}

.table-scroll :deep(.t-table) {
  min-width: 100%;
}

.system-filter-form {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 16px;
  margin-bottom: 18px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 14px 16px;
}

.system-filter-form :deep(.t-form__item) {
  margin: 0;
}

.system-filter-form :deep(.t-form__label) {
  width: auto !important;
  padding-right: 8px;
}

.system-filter-form :deep(.t-form__controls) {
  margin-left: 0 !important;
}

.filter-input {
  width: 240px;
}

.filter-select {
  width: 150px;
}

.system-section-head {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.system-section-title {
  display: flex;
  align-items: baseline;
  gap: 22px;
}

.system-section-title h2 {
  margin: 0;
  color: #0f172a;
  font-size: 18px;
  font-weight: 700;
}

.system-section-title span {
  color: #64748b;
  font-size: 13px;
}

.system-pagination {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  min-height: 48px;
  margin-top: 12px;
  border-top: 1px solid #edf2f7;
  background: #fff;
  padding-top: 12px;
}
</style>
