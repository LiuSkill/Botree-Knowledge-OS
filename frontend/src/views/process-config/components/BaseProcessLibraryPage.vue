<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import {
  AddIcon,
  BrowseIcon,
  CheckCircleIcon,
  CloseCircleIcon,
  DeleteIcon,
  DownloadIcon,
  EditIcon,
  RefreshIcon,
  UploadIcon,
} from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref, watch } from 'vue';

import {
  createProcessLibrary,
  deleteProcessLibrary,
  exportProcessConfigData,
  getProcessLibrary,
  listProcessLibrary,
  updateProcessLibrary,
  updateProcessLibraryStatus,
} from '@/api/process-config';
import TableActionButton from '@/components/TableActionButton.vue';
import ProcessConfigImportDialog from '@/views/process-config/components/ProcessConfigImportDialog.vue';
import ProcessLibraryFormDialog from '@/views/process-config/components/ProcessLibraryFormDialog.vue';
import type {
  ProcessLibraryItem,
  ProcessLibraryListParams,
  ProcessLibraryPageConfig,
  ProcessLibraryPayload,
  ProcessLibraryStatus,
  ProcessRegionPrice,
} from '@/views/process-config/types';
import { normalizeRegionPrices, processLibraryTypeLabel } from '@/views/process-config/types';
import { buildProcessConfigExportFileName, triggerBlobDownload } from '@/views/process-config/utils';
import { formatDateTime } from '@/utils/format';
import type { PageResult } from '@/types/api';

type PaginationInfo = {
  current: number;
  pageSize: number;
};

type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';
type FormMode = 'create' | 'edit';

const props = defineProps<{
  config: ProcessLibraryPageConfig;
}>();

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const filters = reactive({
  keyword: '',
  type: '',
  status: '' as ProcessLibraryStatus | '',
});
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const loading = ref(false);
const submitting = ref(false);
const detailLoading = ref(false);
const deletingId = ref<number | null>(null);
const statusUpdatingId = ref<number | null>(null);
const exporting = ref(false);
const formVisible = ref(false);
const detailVisible = ref(false);
const importVisible = ref(false);
const formMode = ref<FormMode>('create');
const editingItem = ref<ProcessLibraryItem | null>(null);
const selectedItem = ref<ProcessLibraryItem | null>(null);
const records = reactive<PageResult<ProcessLibraryItem>>({
  items: [],
  total: 0,
  page: 1,
  page_size: DEFAULT_PAGE_SIZE,
});

const columns = [
  { colKey: 'code', title: '编码', width: 150, ellipsis: true },
  { colKey: 'name', title: '名称', minWidth: 170, ellipsis: true },
  { colKey: 'type', title: '类型', width: 140, ellipsis: true },
  { colKey: 'unit', title: '单位', width: 90, ellipsis: true },
  { colKey: 'region_prices', title: '区域单价', minWidth: 280 },
  { colKey: 'status', title: '状态', width: 100, align: 'center' as const },
  { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'operation', title: '操作', width: 210, fixed: 'right' as const },
];

const listTitle = computed(() => `${props.config.title}列表`);
const typeOptions = computed(() => props.config.typeOptions || []);

onMounted(() => {
  loadItems();
});

watch(
  () => props.config.apiBasePath,
  () => {
    clearFilters(false);
    loadItems();
  },
);

function buildQueryParams(): ProcessLibraryListParams {
  const params: ProcessLibraryListParams = {
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.type) params.type = filters.type;
  if (filters.status) params.status = filters.status;
  return params;
}

function buildExportParams(): { keyword?: string; type?: string; status?: ProcessLibraryStatus } {
  const params: { keyword?: string; type?: string; status?: ProcessLibraryStatus } = {};
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.type) params.type = filters.type;
  if (filters.status) params.status = filters.status;
  return params;
}

async function loadItems(): Promise<void> {
  loading.value = true;
  try {
    const result = await listProcessLibrary(props.config.apiBasePath, buildQueryParams());
    records.items = result.items;
    records.total = result.total;
    records.page = result.page;
    records.page_size = result.page_size;
  } finally {
    loading.value = false;
  }
}

function handleSearch(): void {
  page.value = 1;
  loadItems();
}

function clearFilters(reload = true): void {
  filters.keyword = '';
  filters.type = '';
  filters.status = '';
  page.value = 1;
  if (reload) loadItems();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  loadItems();
}

function openCreateDialog(): void {
  formMode.value = 'create';
  editingItem.value = null;
  formVisible.value = true;
}

function openEditDialog(row: ProcessLibraryItem): void {
  formMode.value = 'edit';
  editingItem.value = row;
  formVisible.value = true;
}

async function openDetailDialog(row: ProcessLibraryItem): Promise<void> {
  detailVisible.value = true;
  detailLoading.value = true;
  selectedItem.value = null;
  try {
    selectedItem.value = await getProcessLibrary(props.config.apiBasePath, row.id);
  } finally {
    detailLoading.value = false;
  }
}

async function handleSubmit(payload: ProcessLibraryPayload): Promise<void> {
  submitting.value = true;
  try {
    if (formMode.value === 'create') {
      await createProcessLibrary(props.config.apiBasePath, payload);
      MessagePlugin.success(`已新增${props.config.entityName}`);
    } else if (editingItem.value) {
      await updateProcessLibrary(props.config.apiBasePath, editingItem.value.id, payload);
      MessagePlugin.success(`已更新${props.config.entityName}`);
    }
    formVisible.value = false;
    await loadItems();
  } finally {
    submitting.value = false;
  }
}

async function handleDelete(row: ProcessLibraryItem): Promise<void> {
  deletingId.value = row.id;
  try {
    await deleteProcessLibrary(props.config.apiBasePath, row.id);
    MessagePlugin.success(`已删除${props.config.entityName}`);
    if (records.items.length === 1 && page.value > 1) {
      page.value -= 1;
    }
    await loadItems();
  } finally {
    deletingId.value = null;
  }
}

async function handleToggleStatus(row: ProcessLibraryItem): Promise<void> {
  const nextStatus = row.status === 'enabled' ? 'disabled' : 'enabled';
  statusUpdatingId.value = row.id;
  try {
    await updateProcessLibraryStatus(props.config.apiBasePath, row.id, nextStatus);
    MessagePlugin.success(`${props.config.entityName}已${nextStatus === 'enabled' ? '启用' : '停用'}`);
    await loadItems();
  } finally {
    statusUpdatingId.value = null;
  }
}

function handleImport(): void {
  importVisible.value = true;
}

async function handleExport(): Promise<void> {
  exporting.value = true;
  try {
    const blob = await exportProcessConfigData(props.config.moduleKey, buildExportParams());
    triggerBlobDownload(blob, buildProcessConfigExportFileName(props.config.moduleKey));
    MessagePlugin.success(`${props.config.entityName}数据导出完成`);
  } finally {
    exporting.value = false;
  }
}

async function handleImportSuccess(): Promise<void> {
  page.value = 1;
  await loadItems();
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

function statusActionLabel(row: ProcessLibraryItem): string {
  return row.status === 'enabled' ? '停用' : '启用';
}

function statusConfirmText(row: ProcessLibraryItem): string {
  return `确认${statusActionLabel(row)}该${props.config.entityName}吗？`;
}

function typeLabel(type: string): string {
  return processLibraryTypeLabel(props.config.moduleKey, type);
}

function displayRegionPrices(row: ProcessLibraryItem): ProcessRegionPrice[] {
  return normalizeRegionPrices(row.region_prices, row.unit);
}

function formatPrice(price: ProcessRegionPrice): string {
  return `${price.currency} ${price.unit_price}/${price.unit || '-'}`;
}
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item v-permission="config.permissions.view" label="关键字">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="编码 / 名称 / 类型 / 描述" @enter="handleSearch" />
      </t-form-item>
      <t-form-item v-if="typeOptions.length" v-permission="config.permissions.view" label="类型">
        <t-select v-model="filters.type" class="filter-select" clearable placeholder="全部类型" @change="handleSearch">
          <t-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </t-select>
      </t-form-item>
      <t-form-item v-permission="config.permissions.view" label="状态">
        <t-select v-model="filters.status" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
          <t-option label="启用" value="enabled" />
          <t-option label="草稿" value="draft" />
          <t-option label="停用" value="disabled" />
        </t-select>
      </t-form-item>
      <t-form-item>
        <t-space>
          <t-button v-permission="config.permissions.view" theme="primary" @click="handleSearch">查询</t-button>
          <t-button v-permission="config.permissions.view" @click="clearFilters()">重置</t-button>
        </t-space>
      </t-form-item>
    </t-form>

    <div class="system-section-head">
      <div class="system-section-title">
        <h2>{{ listTitle }}</h2>
        <span>共 {{ records.total }} 条数据</span>
      </div>
      <t-space>
        <t-button v-permission="config.permissions.view" theme="default" variant="outline" :loading="loading" @click="loadItems">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="config.permissions.import" theme="default" variant="outline" @click="handleImport">
          <template #icon><UploadIcon /></template>
          导入
        </t-button>
        <t-button v-permission="config.permissions.export" theme="default" variant="outline" :loading="exporting" @click="handleExport">
          <template #icon><DownloadIcon /></template>
          导出
        </t-button>
        <t-button v-permission="config.permissions.create" theme="primary" @click="openCreateDialog">
          <template #icon><AddIcon /></template>
          新增{{ config.entityName }}
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
        :empty="`暂无${config.entityName}数据`"
      >
        <template #region_prices="{ row }">
          <div class="price-list">
            <t-tag v-for="price in displayRegionPrices(row)" :key="price.region_code" size="small" variant="light">
              {{ price.region_name }} {{ formatPrice(price) }}
            </t-tag>
          </div>
        </template>
        <template #type="{ row }">
          {{ typeLabel(row.type) }}
        </template>
        <template #status="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.status)">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #updated_at="{ row }">
          {{ formatDateTime(row.updated_at) }}
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton label="查看" :permission="config.permissions.view" @click="openDetailDialog(row)">
              <BrowseIcon />
            </TableActionButton>
            <TableActionButton label="编辑" :permission="config.permissions.update" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <t-popconfirm :content="statusConfirmText(row)" @confirm="handleToggleStatus(row)">
              <TableActionButton :label="statusActionLabel(row)" :permission="config.permissions.update" :loading="statusUpdatingId === row.id">
                <CheckCircleIcon v-if="row.status !== 'enabled'" />
                <CloseCircleIcon v-else />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm :content="`确认删除该${config.entityName}吗？删除前系统会检查引用关系。`" @confirm="handleDelete(row)">
              <TableActionButton label="删除" :permission="config.permissions.delete" :loading="deletingId === row.id" theme="danger">
                <DeleteIcon />
              </TableActionButton>
            </t-popconfirm>
          </t-space>
        </template>
      </t-table>
    </div>

    <div v-permission="config.permissions.view" class="system-pagination">
      <t-pagination
        :current="page"
        :page-size="pageSize"
        :total="records.total"
        :page-size-options="PAGE_SIZE_OPTIONS"
        show-jumper
        @change="handlePaginationChange"
      />
    </div>

    <ProcessLibraryFormDialog
      v-model:visible="formVisible"
      :mode="formMode"
      :entity-name="config.entityName"
      :data="editingItem"
      :loading="submitting"
      :type-options="typeOptions"
      @submit="handleSubmit"
    />

    <ProcessConfigImportDialog
      v-model:visible="importVisible"
      :module-key="config.moduleKey"
      :module-label="config.entityName"
      @success="handleImportSuccess"
    />

    <t-dialog v-model:visible="detailVisible" :header="`${config.entityName}详情`" width="760px" :footer="false">
      <t-loading :loading="detailLoading">
        <div v-if="selectedItem" class="detail-content">
          <t-descriptions bordered :column="2" size="small">
            <t-descriptions-item label="编码">{{ selectedItem.code }}</t-descriptions-item>
            <t-descriptions-item label="名称">{{ selectedItem.name }}</t-descriptions-item>
            <t-descriptions-item label="类型">{{ typeLabel(selectedItem.type) }}</t-descriptions-item>
            <t-descriptions-item label="单位">{{ selectedItem.unit }}</t-descriptions-item>
            <t-descriptions-item label="状态">
              <t-tag size="small" variant="light" :theme="statusTheme(selectedItem.status)">{{ statusLabel(selectedItem.status) }}</t-tag>
            </t-descriptions-item>
            <t-descriptions-item label="排序">{{ selectedItem.sort_order }}</t-descriptions-item>
            <t-descriptions-item label="创建时间">{{ formatDateTime(selectedItem.created_at) }}</t-descriptions-item>
            <t-descriptions-item label="更新时间">{{ formatDateTime(selectedItem.updated_at) }}</t-descriptions-item>
            <t-descriptions-item label="描述">{{ selectedItem.description || '-' }}</t-descriptions-item>
            <t-descriptions-item label="备注">{{ selectedItem.remark || '-' }}</t-descriptions-item>
          </t-descriptions>

          <div class="detail-section-title">区域单价</div>
          <div class="detail-price-list">
            <div v-for="price in displayRegionPrices(selectedItem)" :key="price.region_code" class="detail-price-row">
              <span>{{ price.region_name }}</span>
              <strong>{{ formatPrice(price) }}</strong>
              <t-tag size="small" variant="light" :theme="statusTheme(price.status)">{{ statusLabel(price.status) }}</t-tag>
            </div>
          </div>
        </div>
      </t-loading>
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

.price-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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

.detail-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.detail-section-title {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.detail-price-list {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.detail-price-row {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 6px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 10px;
}

.detail-price-row span {
  color: #64748b;
  font-size: 12px;
}

.detail-price-row strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

@media (max-width: 920px) {
  .detail-price-list {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 720px) {
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
