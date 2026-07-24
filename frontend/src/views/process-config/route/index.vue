<script setup lang="ts">
import { AddIcon, BrowseIcon, DeleteIcon, DownloadIcon, EditIcon, FileSearchIcon, RefreshIcon, TimeIcon, UploadIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import {
  createProcessRoute,
  deleteProcessRoute,
  exportProcessConfigData,
  getProcessRoute,
  listProcessLibraryOptions,
  listProcessNodes,
  listProcessRoutes,
  listProcessRouteCalculationOutputs,
  replaceProcessRouteCalculationOutputs,
  updateProcessRoute,
} from '@/api/process-config';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { PageResult } from '@/types/api';
import { formatDateTime } from '@/utils/format';
import ProcessConfigImportDialog from '@/views/process-config/components/ProcessConfigImportDialog.vue';
import type { ProcessLibraryOptionItem, ProcessNodeItem } from '@/views/process-config/node/types';
import RouteFormDialog from '@/views/process-config/route/components/RouteFormDialog.vue';
import RouteVersionDialog from '@/views/process-config/route/components/RouteVersionDialog.vue';
import type {
  ProcessRouteDetail,
  ProcessRouteItem,
  ProcessRouteListParams,
  ProcessRoutePayload,
  ProcessCalculationOutputPayload,
  RouteNodeOption,
} from '@/views/process-config/route/types';
import type { ProcessLibraryStatus } from '@/views/process-config/types';
import { buildProcessConfigExportFileName, triggerBlobDownload } from '@/views/process-config/utils';

type PaginationInfo = {
  current: number;
  pageSize: number;
};

type TagTheme = 'default' | 'success' | 'warning';
type FormMode = 'create' | 'edit';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const STATS_FETCH_PAGE_SIZE = 100;

const permissions = {
  view: PERMISSIONS.PROCESS_CONFIG_ROUTE_VIEW,
  create: PERMISSIONS.PROCESS_CONFIG_ROUTE_CREATE,
  update: PERMISSIONS.PROCESS_CONFIG_ROUTE_UPDATE,
  delete: PERMISSIONS.PROCESS_CONFIG_ROUTE_DELETE,
  import: PERMISSIONS.PROCESS_CONFIG_ROUTE_IMPORT,
  export: PERMISSIONS.PROCESS_CONFIG_ROUTE_EXPORT,
  version: PERMISSIONS.PROCESS_CONFIG_ROUTE_VERSION,
  preview: PERMISSIONS.PROCESS_CONFIG_ROUTE_PREVIEW,
} as const;

const router = useRouter();
const authStore = useAuthStore();

const filters = reactive({
  keyword: '',
  input_material_id: undefined as number | undefined,
  final_product_id: undefined as number | undefined,
  status: '' as ProcessLibraryStatus | '',
});

const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const loading = ref(false);
const statsLoading = ref(false);
const optionsLoading = ref(false);
const submitting = ref(false);
const editLoadingId = ref<number | null>(null);
const deletingId = ref<number | null>(null);
const exporting = ref(false);
const formVisible = ref(false);
const importVisible = ref(false);
const formMode = ref<FormMode>('create');
const editingRoute = ref<ProcessRouteDetail | null>(null);
const editingCalculationOutputs = ref<ProcessCalculationOutputPayload[]>([]);
const optionsLoaded = ref(false);
const versionDialogVisible = ref(false);
const versionRoute = ref<ProcessRouteItem | null>(null);

const records = reactive<PageResult<ProcessRouteItem>>({
  items: [],
  total: 0,
  page: 1,
  page_size: DEFAULT_PAGE_SIZE,
});

const stats = reactive({
  total: 0,
  enabled: 0,
  draft: 0,
  averageNodeCount: 0,
});

const materialOptions = ref<ProcessLibraryOptionItem[]>([]);
const productOptions = ref<ProcessLibraryOptionItem[]>([]);
const nodeOptions = ref<RouteNodeOption[]>([]);

const columns = [
  { colKey: 'code', title: '路线编码', width: 150, ellipsis: true },
  { colKey: 'name', title: '路线名称', minWidth: 170, ellipsis: true },
  { colKey: 'input_material_name', title: '输入原料', width: 150, ellipsis: true },
  { colKey: 'final_product_name', title: '最终产品', width: 150, ellipsis: true },
  { colKey: 'version', title: '版本', width: 110 },
  { colKey: 'node_count', title: '节点数', width: 90, align: 'center' as const },
  { colKey: 'status', title: '状态', width: 100, align: 'center' as const },
  { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'operation', title: '操作', width: 272, fixed: 'right' as const },
];

const statCards = computed(() => [
  { label: '路线总数', value: stats.total, theme: 'primary' },
  { label: '启用路线', value: stats.enabled, theme: 'success' },
  { label: '草稿路线', value: stats.draft, theme: 'warning' },
  { label: '平均节点数', value: formatAverage(stats.averageNodeCount), theme: 'default' },
]);

const canManageVersion = computed(() => authStore.hasActionPermission(permissions.version));

onMounted(() => {
  loadOptions();
  refreshAll();
});

function buildQueryParams(): ProcessRouteListParams {
  const params: ProcessRouteListParams = {
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.input_material_id) params.input_material_id = filters.input_material_id;
  if (filters.final_product_id) params.final_product_id = filters.final_product_id;
  if (filters.status) params.status = filters.status;
  return params;
}

function buildExportParams(): Omit<ProcessRouteListParams, 'page' | 'page_size'> {
  const params: Omit<ProcessRouteListParams, 'page' | 'page_size'> = {};
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.input_material_id) params.input_material_id = filters.input_material_id;
  if (filters.final_product_id) params.final_product_id = filters.final_product_id;
  if (filters.status) params.status = filters.status;
  return params;
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadRoutes(), loadStats()]);
}

async function loadRoutes(): Promise<void> {
  loading.value = true;
  try {
    const result = await listProcessRoutes(buildQueryParams());
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
    const [totalResult, enabledResult, draftResult, averageNodeCount] = await Promise.all([
      listProcessRoutes({ page: 1, page_size: 1 }),
      listProcessRoutes({ status: 'enabled', page: 1, page_size: 1 }),
      listProcessRoutes({ status: 'draft', page: 1, page_size: 1 }),
      fetchAverageNodeCount(),
    ]);
    stats.total = totalResult.total;
    stats.enabled = enabledResult.total;
    stats.draft = draftResult.total;
    stats.averageNodeCount = averageNodeCount;
  } finally {
    statsLoading.value = false;
  }
}

async function fetchAverageNodeCount(): Promise<number> {
  const firstPage = await listProcessRoutes({ page: 1, page_size: STATS_FETCH_PAGE_SIZE });
  if (!firstPage.total) return 0;

  let totalNodeCount = firstPage.items.reduce((sum, item) => sum + Number(item.node_count || 0), 0);
  const totalPages = Math.ceil(firstPage.total / firstPage.page_size);

  if (totalPages > 1) {
    const restPages = await Promise.all(
      Array.from({ length: totalPages - 1 }, (_, index) =>
        listProcessRoutes({
          page: index + 2,
          page_size: firstPage.page_size,
        }),
      ),
    );
    restPages.forEach((result) => {
      totalNodeCount += result.items.reduce((sum, item) => sum + Number(item.node_count || 0), 0);
    });
  }

  return totalNodeCount / firstPage.total;
}

async function loadOptions(force = false): Promise<void> {
  if (optionsLoaded.value && !force) return;
  optionsLoading.value = true;
  try {
    const [materials, products, nodes] = await Promise.all([
      listProcessLibraryOptions('materials'),
      listProcessLibraryOptions('products', { output_type: 'product' }),
      loadAllNodeOptions(),
    ]);
    materialOptions.value = materials;
    productOptions.value = products;
    nodeOptions.value = nodes;
    optionsLoaded.value = true;
  } finally {
    optionsLoading.value = false;
  }
}

async function loadAllNodeOptions(): Promise<RouteNodeOption[]> {
  const firstPage = await listProcessNodes({ page: 1, page_size: STATS_FETCH_PAGE_SIZE });
  const items: ProcessNodeItem[] = [...firstPage.items];
  const totalPages = Math.ceil(firstPage.total / firstPage.page_size);

  if (totalPages > 1) {
    const restPages = await Promise.all(
      Array.from({ length: totalPages - 1 }, (_, index) =>
        listProcessNodes({
          page: index + 2,
          page_size: firstPage.page_size,
        }),
      ),
    );
    restPages.forEach((result) => items.push(...result.items));
  }

  return items.sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);
}

function handleSearch(): void {
  page.value = 1;
  loadRoutes();
}

function clearFilters(): void {
  filters.keyword = '';
  filters.input_material_id = undefined;
  filters.final_product_id = undefined;
  filters.status = '';
  page.value = 1;
  loadRoutes();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  loadRoutes();
}

async function openCreateDialog(): Promise<void> {
  await loadOptions();
  formMode.value = 'create';
  editingRoute.value = null;
  editingCalculationOutputs.value = [];
  formVisible.value = true;
}

async function openEditDialog(row: ProcessRouteItem): Promise<void> {
  editLoadingId.value = row.id;
  try {
    await loadOptions();
    const [routeDetail, calculationOutputs] = await Promise.all([
      getProcessRoute(row.id),
      listProcessRouteCalculationOutputs(row.id),
    ]);
    editingRoute.value = routeDetail;
    editingCalculationOutputs.value = calculationOutputs;
    formMode.value = 'edit';
    formVisible.value = true;
  } finally {
    editLoadingId.value = null;
  }
}

async function handleSubmit(payload: ProcessRoutePayload, calculationOutputs: ProcessCalculationOutputPayload[]): Promise<void> {
  submitting.value = true;
  try {
    if (formMode.value === 'create') {
      const created = await createProcessRoute(payload);
      await replaceProcessRouteCalculationOutputs(created.route.id, calculationOutputs);
      MessagePlugin.success('工艺路线已创建');
    } else if (editingRoute.value) {
      await updateProcessRoute(editingRoute.value.route.id, payload);
      await replaceProcessRouteCalculationOutputs(editingRoute.value.route.id, calculationOutputs);
      MessagePlugin.success('工艺路线已更新');
    }
    formVisible.value = false;
    await refreshAll();
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: ProcessRouteItem): Promise<void> {
  deletingId.value = row.id;
  try {
    await deleteProcessRoute(row.id);
    MessagePlugin.success('工艺路线已删除');
    if (records.items.length === 1 && page.value > 1) {
      page.value -= 1;
    }
    await refreshAll();
  } finally {
    deletingId.value = null;
  }
}

function openVersionDialog(row: ProcessRouteItem): void {
  versionRoute.value = row;
  versionDialogVisible.value = true;
}

function openDetailPage(row: ProcessRouteItem): void {
  router.push(`/process-config/routes/${row.id}`);
}

function openPreviewPage(row: ProcessRouteItem): void {
  const target = router.resolve(`/process-config/routes/${row.id}/preview`);
  window.open(target.href, '_blank', 'noopener,noreferrer');
}

function handleImport(): void {
  importVisible.value = true;
}

async function handleExport(): Promise<void> {
  exporting.value = true;
  try {
    const blob = await exportProcessConfigData('routes', buildExportParams());
    triggerBlobDownload(blob, buildProcessConfigExportFileName('routes'));
    MessagePlugin.success('工艺路线数据导出完成');
  } finally {
    exporting.value = false;
  }
}

async function handleImportSuccess(): Promise<void> {
  page.value = 1;
  await refreshAll();
}

function statusLabel(status: ProcessLibraryStatus): string {
  return (
    {
      enabled: '启用',
      draft: '草稿',
      disabled: '停用',
    }[status] || status
  );
}

function statusTheme(status: ProcessLibraryStatus): TagTheme {
  return (
    {
      enabled: 'success',
      draft: 'warning',
      disabled: 'default',
    }[status] || 'default'
  );
}

function formatAverage(value: number): string {
  return Number.isFinite(value) ? value.toFixed(1) : '0.0';
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
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="路线编码 / 名称" @enter="handleSearch" />
      </t-form-item>
      <t-form-item v-permission="permissions.view" label="输入原料">
        <t-select v-model="filters.input_material_id" class="filter-select" clearable filterable placeholder="全部原料" @change="handleSearch">
          <t-option v-for="item in materialOptions" :key="item.id" :label="`${item.code} / ${item.name}`" :value="item.id" />
        </t-select>
      </t-form-item>
      <t-form-item v-permission="permissions.view" label="最终产品">
        <t-select v-model="filters.final_product_id" class="filter-select" clearable filterable placeholder="全部产品" @change="handleSearch">
          <t-option v-for="item in productOptions" :key="item.id" :label="`${item.code} / ${item.name}`" :value="item.id" />
        </t-select>
      </t-form-item>
      <t-form-item v-permission="permissions.view" label="状态">
        <t-select v-model="filters.status" class="filter-select status-filter" clearable placeholder="全部状态" @change="handleSearch">
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
        <h2>工艺路线列表</h2>
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
          新增路线
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
        empty="暂无工艺路线数据"
      >
        <template #input_material_name="{ row }">
          {{ row.input_material_name || '-' }}
        </template>
        <template #final_product_name="{ row }">
          {{ row.final_product_name || '-' }}
        </template>
        <template #status="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.status)">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #updated_at="{ row }">
          {{ formatDateTime(row.updated_at) }}
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton label="查看详情" :permission="permissions.view" @click="openDetailPage(row)">
              <BrowseIcon />
            </TableActionButton>
            <TableActionButton label="线路预览" :permission="permissions.preview" @click="openPreviewPage(row)">
              <FileSearchIcon />
            </TableActionButton>
            <TableActionButton label="编辑" :permission="permissions.update" :loading="editLoadingId === row.id" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <TableActionButton label="版本管理" :permission="permissions.version" @click="openVersionDialog(row)">
              <TimeIcon />
            </TableActionButton>
            <t-popconfirm content="确认删除该工艺路线吗？系统会保留软删除审计记录。" @confirm="handleDelete(row)">
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

    <RouteFormDialog
      v-model:visible="formVisible"
      :mode="formMode"
      :route="editingRoute"
      :node-options="nodeOptions"
      :material-options="materialOptions"
      :product-options="productOptions"
      :calculation-outputs="editingCalculationOutputs"
      :saving="submitting"
      :options-loading="optionsLoading"
      @submit="handleSubmit"
    />

    <RouteVersionDialog
      v-model:visible="versionDialogVisible"
      :route-id="versionRoute?.id || null"
      :route-name="versionRoute?.name || ''"
      :can-create="canManageVersion"
    />

    <ProcessConfigImportDialog v-model:visible="importVisible" module-key="routes" module-label="工艺路线" @success="handleImportSuccess" />
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
  width: 180px;
}

.status-filter {
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
  .filter-select,
  .status-filter {
    width: 100%;
  }
}
</style>
