<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { AddIcon, BrowseIcon, DeleteIcon, DownloadIcon, EditIcon, RefreshIcon, UploadIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';

import {
  createProcessNode,
  deleteProcessNode,
  exportProcessConfigData,
  getProcessNode,
  listProcessLibraryOptions,
  listProcessNodes,
  updateProcessNode,
} from '@/api/process-config';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import type { PageResult } from '@/types/api';
import { formatDateTime } from '@/utils/format';
import ProcessConfigImportDialog from '@/views/process-config/components/ProcessConfigImportDialog.vue';
import type { ProcessLibraryStatus } from '@/views/process-config/types';
import { buildProcessConfigExportFileName, triggerBlobDownload } from '@/views/process-config/utils';
import NodeDetailDrawer from '@/views/process-config/node/components/NodeDetailDrawer.vue';
import NodeFormDialog from '@/views/process-config/node/components/NodeFormDialog.vue';
import type {
  ProcessLibraryOptionItem,
  ProcessNodeDetail,
  ProcessNodeItem,
  ProcessNodeListParams,
  ProcessNodePayload,
  ProcessNodeType,
} from '@/views/process-config/node/types';
import { PROCESS_NODE_TYPE_OPTIONS } from '@/views/process-config/node/types';

type PaginationInfo = {
  current: number;
  pageSize: number;
};

type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';
type FormMode = 'create' | 'edit';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const permissions = {
  view: PERMISSIONS.PROCESS_CONFIG_NODE_VIEW,
  create: PERMISSIONS.PROCESS_CONFIG_NODE_CREATE,
  update: PERMISSIONS.PROCESS_CONFIG_NODE_UPDATE,
  delete: PERMISSIONS.PROCESS_CONFIG_NODE_DELETE,
  import: PERMISSIONS.PROCESS_CONFIG_NODE_IMPORT,
  export: PERMISSIONS.PROCESS_CONFIG_NODE_EXPORT,
} as const;

const filters = reactive({
  keyword: '',
  node_type: '' as ProcessNodeType | '',
  status: '' as ProcessLibraryStatus | '',
});

const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const loading = ref(false);
const statsLoading = ref(false);
const optionsLoading = ref(false);
const submitting = ref(false);
const detailLoading = ref(false);
const editLoadingId = ref<number | null>(null);
const deletingId = ref<number | null>(null);
const exporting = ref(false);
const formVisible = ref(false);
const detailVisible = ref(false);
const importVisible = ref(false);
const formMode = ref<FormMode>('create');
const editingNode = ref<ProcessNodeDetail | null>(null);
const selectedNode = ref<ProcessNodeDetail | null>(null);
const optionsLoaded = ref(false);

const records = reactive<PageResult<ProcessNodeItem>>({
  items: [],
  total: 0,
  page: 1,
  page_size: DEFAULT_PAGE_SIZE,
});

const stats = reactive({
  total: 0,
  enabled: 0,
  draft: 0,
  disabled: 0,
});

const materialOptions = ref<ProcessLibraryOptionItem[]>([]);
const productOptions = ref<ProcessLibraryOptionItem[]>([]);
const consumableOptions = ref<ProcessLibraryOptionItem[]>([]);
const publicServiceOptions = ref<ProcessLibraryOptionItem[]>([]);
const laborCostOptions = ref<ProcessLibraryOptionItem[]>([]);
const assetOptions = ref<ProcessLibraryOptionItem[]>([]);

const columns = [
  { colKey: 'code', title: '节点编码', width: 150, ellipsis: true },
  { colKey: 'name', title: '节点名称', minWidth: 170, ellipsis: true },
  { colKey: 'node_type', title: '节点类型', width: 150, ellipsis: true },
  { colKey: 'status', title: '状态', width: 100, align: 'center' as const },
  { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'operation', title: '操作', width: 160, fixed: 'right' as const },
];

const statCards = computed(() => [
  { label: '节点总数', value: stats.total, theme: 'primary' },
  { label: '启用节点数', value: stats.enabled, theme: 'success' },
  { label: '草稿节点数', value: stats.draft, theme: 'warning' },
  { label: '停用节点数', value: stats.disabled, theme: 'default' },
]);

onMounted(() => {
  loadOptions();
  refreshAll();
});

function buildQueryParams(): ProcessNodeListParams {
  const params: ProcessNodeListParams = {
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.node_type) params.node_type = filters.node_type;
  if (filters.status) params.status = filters.status;
  return params;
}

function buildExportParams(): Omit<ProcessNodeListParams, 'page' | 'page_size'> {
  const params: Omit<ProcessNodeListParams, 'page' | 'page_size'> = {};
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.node_type) params.node_type = filters.node_type;
  if (filters.status) params.status = filters.status;
  return params;
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadNodes(), loadStats()]);
}

async function loadNodes(): Promise<void> {
  loading.value = true;
  try {
    const result = await listProcessNodes(buildQueryParams());
    records.items = result.items;
    records.total = result.total;
    records.page = result.page;
    records.page_size = result.page_size;
  } finally {
    loading.value = false;
  }
}

async function loadStats(): Promise<void> {
  statsLoading.value = true;
  try {
    const [totalResult, enabledResult, draftResult, disabledResult] = await Promise.all([
      listProcessNodes({ page: 1, page_size: 1 }),
      listProcessNodes({ status: 'enabled', page: 1, page_size: 1 }),
      listProcessNodes({ status: 'draft', page: 1, page_size: 1 }),
      listProcessNodes({ status: 'disabled', page: 1, page_size: 1 }),
    ]);
    stats.total = totalResult.total;
    stats.enabled = enabledResult.total;
    stats.draft = draftResult.total;
    stats.disabled = disabledResult.total;
  } finally {
    statsLoading.value = false;
  }
}

async function loadOptions(force = false): Promise<void> {
  if (optionsLoaded.value && !force) return;
  optionsLoading.value = true;
  try {
    const [materials, products, consumables, publicServices, laborCosts, assets] = await Promise.all([
      listProcessLibraryOptions('materials'),
      listProcessLibraryOptions('products'),
      listProcessLibraryOptions('consumables'),
      listProcessLibraryOptions('public-services'),
      listProcessLibraryOptions('labor-costs'),
      listProcessLibraryOptions('assets'),
    ]);
    materialOptions.value = materials;
    productOptions.value = products;
    consumableOptions.value = consumables;
    publicServiceOptions.value = publicServices;
    laborCostOptions.value = laborCosts;
    assetOptions.value = assets;
    optionsLoaded.value = true;
  } finally {
    optionsLoading.value = false;
  }
}

function handleSearch(): void {
  page.value = 1;
  loadNodes();
}

function clearFilters(): void {
  filters.keyword = '';
  filters.node_type = '';
  filters.status = '';
  page.value = 1;
  loadNodes();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  loadNodes();
}

async function openCreateDialog(): Promise<void> {
  await loadOptions();
  formMode.value = 'create';
  editingNode.value = null;
  formVisible.value = true;
}

async function openEditDialog(row: ProcessNodeItem): Promise<void> {
  editLoadingId.value = row.id;
  try {
    await loadOptions();
    editingNode.value = await getProcessNode(row.id);
    formMode.value = 'edit';
    formVisible.value = true;
  } finally {
    editLoadingId.value = null;
  }
}

async function openDetailDrawer(row: ProcessNodeItem): Promise<void> {
  detailVisible.value = true;
  detailLoading.value = true;
  selectedNode.value = null;
  try {
    await loadOptions();
    selectedNode.value = await getProcessNode(row.id);
  } finally {
    detailLoading.value = false;
  }
}

async function handleSubmit(payload: ProcessNodePayload): Promise<void> {
  submitting.value = true;
  try {
    if (formMode.value === 'create') {
      await createProcessNode(payload);
      MessagePlugin.success('已新增工艺节点');
    } else if (editingNode.value) {
      await updateProcessNode(editingNode.value.id, payload);
      MessagePlugin.success('已更新工艺节点');
    }
    formVisible.value = false;
    await refreshAll();
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: ProcessNodeItem): Promise<void> {
  deletingId.value = row.id;
  try {
    await deleteProcessNode(row.id);
    MessagePlugin.success('已删除工艺节点');
    if (records.items.length === 1 && page.value > 1) {
      page.value -= 1;
    }
    await refreshAll();
  } finally {
    deletingId.value = null;
  }
}

function handleImport(): void {
  importVisible.value = true;
}

async function handleExport(): Promise<void> {
  exporting.value = true;
  try {
    const blob = await exportProcessConfigData('nodes', buildExportParams());
    triggerBlobDownload(blob, buildProcessConfigExportFileName('nodes'));
    MessagePlugin.success('工艺节点数据导出完成');
  } finally {
    exporting.value = false;
  }
}

async function handleImportSuccess(): Promise<void> {
  page.value = 1;
  await refreshAll();
}

function statusLabel(status: ProcessLibraryStatus): string {
  const labels: Record<ProcessLibraryStatus, string> = {
    enabled: '启用',
    draft: '草稿',
    disabled: '停用',
  };
  return labels[status] || status;
}

function statusTheme(status: ProcessLibraryStatus): TagTheme {
  const themes: Record<ProcessLibraryStatus, TagTheme> = {
    enabled: 'success',
    draft: 'warning',
    disabled: 'default',
  };
  return themes[status] || 'default';
}

function nodeTypeLabel(value: ProcessNodeType): string {
  return PROCESS_NODE_TYPE_OPTIONS.find((item) => item.value === value)?.label || value;
}
</script>

<template>
  <div class="system-card scroll-card">
    <div v-permission="permissions.view" class="stats-grid">
      <div v-for="item in statCards" :key="item.label" class="stat-card" :class="`stat-card--${item.theme}`">
        <div class="stat-card-label">{{ item.label }}</div>
        <div class="stat-card-value">
          <t-loading size="small" :loading="statsLoading">{{ item.value }}</t-loading>
        </div>
      </div>
    </div>

    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item v-permission="permissions.view" label="关键字">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="节点编码 / 名称 / 类型" @enter="handleSearch" />
      </t-form-item>
      <t-form-item v-permission="permissions.view" label="节点类型">
        <t-select v-model="filters.node_type" class="filter-select" clearable placeholder="全部类型" @change="handleSearch">
          <t-option v-for="item in PROCESS_NODE_TYPE_OPTIONS" :key="item.value" :label="item.label" :value="item.value" />
        </t-select>
      </t-form-item>
      <t-form-item v-permission="permissions.view" label="状态">
        <t-select v-model="filters.status" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
          <t-option label="启用" value="enabled" />
          <t-option label="草稿" value="draft" />
          <t-option label="停用" value="disabled" />
        </t-select>
      </t-form-item>
      <t-form-item>
        <t-space>
          <t-button v-permission="permissions.view" theme="primary" @click="handleSearch">查询</t-button>
          <t-button v-permission="permissions.view" @click="clearFilters">重置</t-button>
        </t-space>
      </t-form-item>
    </t-form>

    <div class="system-section-head">
      <div class="system-section-title">
        <h2>工艺节点列表</h2>
        <span>共 {{ records.total }} 条数据</span>
      </div>
      <t-space>
        <t-button v-permission="permissions.view" theme="default" variant="outline" :loading="loading" @click="refreshAll">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="permissions.import" theme="default" variant="outline" @click="handleImport">
          <template #icon><UploadIcon /></template>
          导入
        </t-button>
        <t-button v-permission="permissions.export" theme="default" variant="outline" :loading="exporting" @click="handleExport">
          <template #icon><DownloadIcon /></template>
          导出
        </t-button>
        <t-button v-permission="permissions.create" theme="primary" @click="openCreateDialog">
          <template #icon><AddIcon /></template>
          新增节点
        </t-button>
      </t-space>
    </div>

    <div class="table-scroll">
      <t-table
        row-key="id"
        bordered
        table-layout="fixed"
        vertical-align="top"
        :data="records.items"
        :columns="columns"
        :loading="loading"
        empty="暂无工艺节点数据"
      >
        <template #node_type="{ row }">
          {{ nodeTypeLabel(row.node_type) }}
        </template>
        <template #status="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.status)">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #updated_at="{ row }">
          {{ formatDateTime(row.updated_at) }}
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton label="查看" :permission="permissions.view" @click="openDetailDrawer(row)">
              <BrowseIcon />
            </TableActionButton>
            <TableActionButton label="编辑" :permission="permissions.update" :loading="editLoadingId === row.id" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <t-popconfirm content="确认删除该工艺节点吗？删除前系统会检查工艺路线引用关系。" @confirm="handleDelete(row)">
              <TableActionButton label="删除" :permission="permissions.delete" :loading="deletingId === row.id" theme="danger">
                <DeleteIcon />
              </TableActionButton>
            </t-popconfirm>
          </t-space>
        </template>
      </t-table>
    </div>

    <div v-permission="permissions.view" class="system-pagination">
      <t-pagination
        :current="page"
        :page-size="pageSize"
        :total="records.total"
        :page-size-options="PAGE_SIZE_OPTIONS"
        show-jumper
        @change="handlePaginationChange"
      />
    </div>

    <NodeFormDialog
      v-model:visible="formVisible"
      :mode="formMode"
      :node="editingNode"
      :saving="submitting"
      :options-loading="optionsLoading"
      :material-options="materialOptions"
      :product-options="productOptions"
      :consumable-options="consumableOptions"
      :public-service-options="publicServiceOptions"
      :labor-cost-options="laborCostOptions"
      :asset-options="assetOptions"
      @submit="handleSubmit"
    />

    <NodeDetailDrawer
      v-model:visible="detailVisible"
      :node="selectedNode"
      :loading="detailLoading"
      :material-options="materialOptions"
      :product-options="productOptions"
      :consumable-options="consumableOptions"
      :public-service-options="publicServiceOptions"
      :asset-options="assetOptions"
    />

    <ProcessConfigImportDialog v-model:visible="importVisible" module-key="nodes" module-label="工艺节点" @success="handleImportSuccess" />
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

.stats-grid {
  display: grid;
  flex: 0 0 auto;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 18px;
}

.stat-card {
  display: grid;
  gap: 8px;
  min-width: 0;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 14px 16px;
}

.stat-card-label {
  color: #64748b;
  font-size: 13px;
}

.stat-card-value {
  color: #0f172a;
  font-size: 28px;
  font-weight: 800;
  line-height: 1.1;
}

.stat-card--primary {
  border-top: 3px solid #0052d9;
}

.stat-card--success {
  border-top: 3px solid #00a870;
}

.stat-card--warning {
  border-top: 3px solid #ed7b2f;
}

.stat-card--default {
  border-top: 3px solid #94a3b8;
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
  width: 260px;
}

.filter-select {
  width: 150px;
}

.system-section-head {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
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

@media (max-width: 1080px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .system-section-head,
  .system-pagination {
    align-items: stretch;
    flex-direction: column;
  }

  .system-filter-form {
    align-items: stretch;
  }

  .filter-input,
  .filter-select {
    width: 100%;
  }
}
</style>
