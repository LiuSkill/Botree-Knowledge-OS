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
const modelTypeOptions = [
  { value: 'llm', label: 'LLM' },
  { value: 'intent', label: '意图识别' },
  { value: 'planner', label: '检索规划' },
  { value: 'evidence_judge_fast', label: '证据判断 Flash' },
  { value: 'evidence_judge', label: '证据判断 Plus' },
  { value: 'answer_llm', label: '普通回答' },
  { value: 'vision_llm', label: '视觉回答' },
  { value: 'analysis_llm', label: '复杂分析' },
  { value: 'embedding', label: 'Embedding' },
];

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

const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新增模型配置' : '编辑模型配置'));

const columns = [
  { colKey: 'provider', title: '供应商', width: 140 },
  { colKey: 'model_name', title: '模型', minWidth: 180 },
  { colKey: 'model_type', title: '类型', width: 150 },
  { colKey: 'api_base', title: 'API Base', minWidth: 220 },
  { colKey: 'is_default', title: '默认', width: 90 },
  { colKey: 'enabled', title: '状态', width: 90 },
  { colKey: 'operation', title: '操作', width: 180, fixed: 'right' },
];

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
    MessagePlugin.success('模型配置已创建');
  } else if (editingConfigId.value) {
    await updateModelConfig(editingConfigId.value, buildSubmitPayload());
    MessagePlugin.success('模型配置已更新');
  }
  dialogVisible.value = false;
  await loadConfigs();
}

async function toggleEnabled(config: ModelConfig): Promise<void> {
  await updateModelConfig(config.id, { enabled: !config.enabled });
  MessagePlugin.success(config.enabled ? '模型已停用' : '模型已启用');
  await loadConfigs();
}

async function handleSetDefault(config: ModelConfig): Promise<void> {
  await setDefaultModelConfig(config.id);
  MessagePlugin.success('默认模型已更新');
  await loadConfigs();
}

async function handleTest(config: ModelConfig): Promise<void> {
  await testModelConfig(config.id);
  MessagePlugin.success('模型连通性测试通过');
}

async function handleDelete(config: ModelConfig): Promise<void> {
  await deleteModelConfig(config.id);
  MessagePlugin.success('模型配置已删除');
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
  return modelTypeOptions.find((item) => item.value === modelType)?.label || modelType;
}

onMounted(loadConfigs);
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item label="关键字">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="供应商 / 模型 / API Base" @enter="handleSearch" />
      </t-form-item>
      <t-form-item label="类型">
        <t-select v-model="filters.model_type" class="filter-select" clearable placeholder="全部类型" @change="handleSearch">
          <t-option v-for="option in modelTypeOptions" :key="option.value" :value="option.value" :label="option.label" />
        </t-select>
      </t-form-item>
      <t-form-item label="状态">
        <t-select v-model="filters.enabled" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
          <t-option label="启用" value="enabled" />
          <t-option label="停用" value="disabled" />
        </t-select>
      </t-form-item>
      <t-form-item label="默认">
        <t-select v-model="filters.is_default" class="filter-select" clearable placeholder="全部" @change="handleSearch">
          <t-option label="默认" value="default" />
          <t-option label="非默认" value="normal" />
        </t-select>
      </t-form-item>
      <t-form-item>
        <t-space>
          <t-button theme="primary" @click="handleSearch">查询</t-button>
          <t-button @click="clearFilters">重置</t-button>
        </t-space>
      </t-form-item>
    </t-form>

    <div class="system-section-head">
      <div class="system-section-title">
        <h2>模型配置列表</h2>
        <span>共 {{ configs.total }} 条数据</span>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="loadConfigs">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="PERMISSIONS.SYSTEM_MODEL_CREATE" theme="primary" @click="openCreateDialog">新增模型</t-button>
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
        empty="暂无模型配置"
      >
        <template #model_type="{ row }">
          {{ modelTypeLabel(row.model_type) }}
        </template>
        <template #api_base="{ row }">
          {{ row.api_base || '-' }}
        </template>
        <template #is_default="{ row }">
          <t-tag size="small" variant="light" :theme="defaultTheme(row.is_default)">{{ row.is_default ? '默认' : '普通' }}</t-tag>
        </template>
        <template #enabled="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.enabled)">{{ row.enabled ? '启用' : '停用' }}</t-tag>
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton label="编辑" :permission="PERMISSIONS.SYSTEM_MODEL_EDIT" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <TableActionButton :label="row.enabled ? '停用' : '启用'" :permission="PERMISSIONS.SYSTEM_MODEL_EDIT" @click="toggleEnabled(row)">
              <PoweroffIcon />
            </TableActionButton>
            <TableActionButton label="设为默认" :permission="PERMISSIONS.SYSTEM_MODEL_SET_DEFAULT" :disabled="row.is_default" @click="handleSetDefault(row)">
              <CheckCircleIcon />
            </TableActionButton>
            <t-popconfirm content="确认测试该模型配置？" @confirm="handleTest(row)">
              <TableActionButton label="测试" :permission="PERMISSIONS.SYSTEM_MODEL_TEST">
                <PlayCircleIcon />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm content="确认删除该模型配置？" @confirm="handleDelete(row)">
              <TableActionButton label="删除" :permission="PERMISSIONS.SYSTEM_MODEL_DELETE" theme="danger">
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
        <t-form-item label="供应商"><t-input v-model="form.provider" /></t-form-item>
        <t-form-item label="模型名称"><t-input v-model="form.model_name" /></t-form-item>
        <t-form-item label="模型类型">
          <t-select v-model="form.model_type">
            <t-option v-for="option in modelTypeOptions" :key="option.value" :value="option.value" :label="option.label" />
          </t-select>
        </t-form-item>
        <t-form-item label="API Base"><t-input v-model="form.api_base" /></t-form-item>
        <t-form-item :label="dialogMode === 'create' ? 'API Key' : 'API Key（留空则不修改）'">
          <t-input v-model="form.api_key" type="password" />
        </t-form-item>
        <t-form-item label="默认模型"><t-switch v-model="form.is_default" /></t-form-item>
        <t-form-item label="启用"><t-switch v-model="form.enabled" /></t-form-item>
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
