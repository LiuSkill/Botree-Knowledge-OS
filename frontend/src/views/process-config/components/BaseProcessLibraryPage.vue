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
import { useI18n } from 'vue-i18n';

import {
  createProcessLibrary,
  deleteProcessLibrary,
  exportProcessConfigData,
  getProcessLibrary,
  listProcessLibrary,
  updateProcessLibrary,
  updateProcessLibraryStatus,
  listProcessMaterialCompositions,
  replaceProcessMaterialCompositions,
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
  ProcessMaterialCompositionPayload,
} from '@/views/process-config/types';
import { normalizeRegionPrices, processLibraryTypeLabel, processUnitLabel } from '@/views/process-config/types';
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
const MODULE_LOCALE_KEY_BY_MODULE = {
  materials: 'materials',
  products: 'products',
  consumables: 'consumables',
  'public-services': 'publicServices',
  'labor-costs': 'laborCosts',
  'equipment-assets': 'equipmentAssets',
  'infrastructure-assets': 'infrastructureAssets',
  nodes: 'nodes',
  routes: 'routes',
} as const;
const PROCESS_TYPE_KEY_BY_VALUE: Record<string, string> = {
  battery_black_mass: 'batteryBlackMass',
  raw_material: 'rawMaterial',
  product: 'product',
  byproduct: 'byproduct',
  solid_waste: 'solidWaste',
  wastewater: 'wastewater',
  waste_gas: 'wasteGas',
  chemical: 'chemical',
  reagent: 'reagent',
  utility: 'utility',
  public_service: 'publicService',
  production: 'production',
  production_management: 'productionManagement',
  management: 'management',
  engineering: 'engineering',
  maintenance: 'maintenance',
  laboratory: 'laboratory',
  hse: 'hse',
  reactor: 'reactor',
  reactor_tank: 'reactorTank',
  pump_valve_pipe: 'pumpValvePipe',
  separation_filter: 'separationFilter',
  solid_liquid_separation: 'solidLiquidSeparation',
  solvent_extraction: 'solventExtraction',
  crystallizer: 'crystallizer',
  kiln: 'kiln',
  dryer: 'dryer',
  evaporator: 'evaporator',
  off_gas_treatment: 'offGasTreatment',
  drying_thermal: 'dryingThermal',
  building: 'building',
  warehouse: 'warehouse',
  office_laboratory: 'officeLaboratory',
  tank_farm: 'tankFarm',
  cooling_water: 'coolingWater',
  compressed_air_nitrogen: 'compressedAirNitrogen',
  power_distribution: 'powerDistribution',
  wastewater_treatment: 'wastewaterTreatment',
  civil: 'civil',
  installation: 'installation',
  warehouse_logistics: 'warehouseLogistics',
  ehs: 'ehs',
};

const { t } = useI18n();
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
const materialCompositions = ref<ProcessMaterialCompositionPayload[]>([]);
const records = reactive<PageResult<ProcessLibraryItem>>({
  items: [],
  total: 0,
  page: 1,
  page_size: DEFAULT_PAGE_SIZE,
});

const columns = computed(() => [
  { colKey: 'code', title: t('process.field.code'), width: 150, ellipsis: true },
  { colKey: 'name', title: t('process.field.name'), minWidth: 170, ellipsis: true },
  { colKey: 'type', title: t('process.field.type'), width: 140, ellipsis: true },
  { colKey: 'unit', title: t('process.field.unit'), width: 90, ellipsis: true },
  { colKey: 'region_prices', title: t('process.field.regionPrice'), minWidth: 280 },
  { colKey: 'status', title: t('common.field.status'), width: 100, align: 'center' as const },
  { colKey: 'updated_at', title: t('common.field.updatedAt'), width: 170 },
  { colKey: 'operation', title: t('common.field.operation'), width: 210, fixed: 'right' as const },
]);

const moduleLocaleKey = computed(() => MODULE_LOCALE_KEY_BY_MODULE[props.config.moduleKey]);
const moduleTitle = computed(() => t(`process.module.${moduleLocaleKey.value}`));
const entityName = computed(() => t(`process.entity.${moduleLocaleKey.value}`));
const listTitle = computed(() => t('process.title.list', { title: moduleTitle.value }));
const typeOptions = computed(() =>
  (props.config.typeOptions || []).map((item) => ({ ...item, label: translateProcessType(item.value, item.label) })),
);

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
    ...props.config.fixedListParams,
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.type) params.type = filters.type;
  if (filters.status) params.status = filters.status;
  return params;
}

function buildExportParams(): ProcessLibraryListParams {
  const params: ProcessLibraryListParams = { ...props.config.fixedListParams };
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
  materialCompositions.value = [];
  formVisible.value = true;
}

async function openEditDialog(row: ProcessLibraryItem): Promise<void> {
  formMode.value = 'edit';
  const [item, compositions] = await Promise.all([
    getProcessLibrary(props.config.apiBasePath, row.id),
    props.config.moduleKey === 'materials' ? listProcessMaterialCompositions(row.id) : Promise.resolve([]),
  ]);
  editingItem.value = item;
  materialCompositions.value = compositions;
  formVisible.value = true;
}

async function openDetailDialog(row: ProcessLibraryItem): Promise<void> {
  detailVisible.value = true;
  detailLoading.value = true;
  selectedItem.value = null;
  try {
    const [item, compositions] = await Promise.all([
      getProcessLibrary(props.config.apiBasePath, row.id),
      props.config.moduleKey === 'materials' ? listProcessMaterialCompositions(row.id) : Promise.resolve([]),
    ]);
    selectedItem.value = item;
    materialCompositions.value = compositions;
  } finally {
    detailLoading.value = false;
  }
}

async function handleSubmit(payload: ProcessLibraryPayload, compositions: ProcessMaterialCompositionPayload[]): Promise<void> {
  submitting.value = true;
  try {
    const finalPayload = { ...payload, ...props.config.fixedPayload };
    if (formMode.value === 'create') {
      const created = await createProcessLibrary(props.config.apiBasePath, finalPayload);
      if (props.config.moduleKey === 'materials') await replaceProcessMaterialCompositions(created.id, compositions);
      MessagePlugin.success(t('process.message.created', { entity: entityName.value }));
    } else if (editingItem.value) {
      await updateProcessLibrary(props.config.apiBasePath, editingItem.value.id, finalPayload);
      if (props.config.moduleKey === 'materials') await replaceProcessMaterialCompositions(editingItem.value.id, compositions);
      MessagePlugin.success(t('process.message.updated', { entity: entityName.value }));
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
    MessagePlugin.success(t('process.message.deleted', { entity: entityName.value }));
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
    MessagePlugin.success(t('process.message.statusChanged', { entity: entityName.value, status: statusLabel(nextStatus) }));
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
    MessagePlugin.success(t('process.message.exportDone', { entity: entityName.value }));
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
    enabled: t('process.status.enabled'),
    draft: t('process.status.draft'),
    disabled: t('process.status.disabled'),
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
  return row.status === 'enabled' ? t('system.action.disable') : t('system.action.enable');
}

function statusConfirmText(row: ProcessLibraryItem): string {
  return t('process.confirm.toggleStatus', { action: statusActionLabel(row), entity: entityName.value });
}

function typeLabel(type: string): string {
  return translateProcessType(type, processLibraryTypeLabel(props.config.moduleKey, type));
}

function unitLabel(unit?: string | null): string {
  return processUnitLabel(unit);
}

function displayRegionPrices(row: ProcessLibraryItem): ProcessRegionPrice[] {
  return normalizeRegionPrices(row.region_prices, row.unit);
}

function translateProcessType(value: string, fallback: string): string {
  const key = PROCESS_TYPE_KEY_BY_VALUE[value];
  return key ? t(`process.type.${key}`) : fallback;
}

function regionLabel(price: ProcessRegionPrice): string {
  return t(`process.region.${price.region_code}`);
}

function formatPrice(price: ProcessRegionPrice): string {
  return `${price.currency} ${price.unit_price}/${unitLabel(price.unit)}`;
}
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item v-permission="config.permissions.view" :label="t('process.field.keyword')">
        <t-input v-model="filters.keyword" class="filter-input" clearable :placeholder="t('process.placeholder.keyword')" @enter="handleSearch" />
      </t-form-item>
      <t-form-item v-if="typeOptions.length" v-permission="config.permissions.view" :label="t('process.field.type')">
        <t-select v-model="filters.type" class="filter-select" clearable :placeholder="t('process.placeholder.allTypes')" @change="handleSearch">
          <t-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </t-select>
      </t-form-item>
      <t-form-item v-permission="config.permissions.view" :label="t('common.field.status')">
        <t-select v-model="filters.status" class="filter-select" clearable :placeholder="t('system.status.all')" @change="handleSearch">
          <t-option :label="t('process.status.enabled')" value="enabled" />
          <t-option :label="t('process.status.draft')" value="draft" />
          <t-option :label="t('process.status.disabled')" value="disabled" />
        </t-select>
      </t-form-item>
      <t-form-item>
        <t-space>
          <t-button v-permission="config.permissions.view" theme="primary" @click="handleSearch">{{ t('system.action.query') }}</t-button>
          <t-button v-permission="config.permissions.view" @click="clearFilters()">{{ t('system.action.reset') }}</t-button>
        </t-space>
      </t-form-item>
    </t-form>

    <div class="system-section-head">
      <div class="system-section-title">
        <h2>{{ listTitle }}</h2>
        <span>{{ t('system.summary.totalRecords', { count: records.total }) }}</span>
      </div>
      <t-space>
        <t-button v-permission="config.permissions.view" theme="default" variant="outline" :loading="loading" @click="loadItems">
          <template #icon><RefreshIcon /></template>
          {{ t('system.action.refresh') }}
        </t-button>
        <t-button v-if="config.enableImportExport !== false" v-permission="config.permissions.import" theme="default" variant="outline" @click="handleImport">
          <template #icon><UploadIcon /></template>
          {{ t('process.action.import') }}
        </t-button>
        <t-button v-if="config.enableImportExport !== false" v-permission="config.permissions.export" theme="default" variant="outline" :loading="exporting" @click="handleExport">
          <template #icon><DownloadIcon /></template>
          {{ t('process.action.export') }}
        </t-button>
        <t-button v-permission="config.permissions.create" theme="primary" @click="openCreateDialog">
          <template #icon><AddIcon /></template>
          {{ t('process.action.createEntity', { entity: entityName }) }}
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
        :empty="t('process.empty.list', { entity: entityName })"
      >
        <template #region_prices="{ row }">
          <div class="price-list">
            <t-tag v-for="price in displayRegionPrices(row)" :key="price.region_code" size="small" variant="light">
              {{ regionLabel(price) }} {{ formatPrice(price) }}
            </t-tag>
          </div>
        </template>
        <template #type="{ row }">
          {{ typeLabel(row.type) }}
        </template>
        <template #unit="{ row }">{{ unitLabel(row.unit) }}</template>
        <template #status="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.status)">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #updated_at="{ row }">
          {{ formatDateTime(row.updated_at) }}
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton :label="t('system.action.view')" :permission="config.permissions.view" @click="openDetailDialog(row)">
              <BrowseIcon />
            </TableActionButton>
            <TableActionButton :label="t('system.action.edit')" :permission="config.permissions.update" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <t-popconfirm :content="statusConfirmText(row)" @confirm="handleToggleStatus(row)">
              <TableActionButton :label="statusActionLabel(row)" :permission="config.permissions.update" :loading="statusUpdatingId === row.id">
                <CheckCircleIcon v-if="row.status !== 'enabled'" />
                <CloseCircleIcon v-else />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm :content="t('process.confirm.delete', { entity: entityName })" @confirm="handleDelete(row)">
              <TableActionButton :label="t('system.action.delete')" :permission="config.permissions.delete" :loading="deletingId === row.id" theme="danger">
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
      :entity-name="entityName"
      :data="editingItem"
      :loading="submitting"
      :type-options="typeOptions"
      :module-key="config.moduleKey"
      :compositions="materialCompositions"
      @submit="handleSubmit"
    />

    <ProcessConfigImportDialog
      v-model:visible="importVisible"
      :module-key="config.moduleKey"
      :module-label="entityName"
      @success="handleImportSuccess"
    />

    <t-dialog v-model:visible="detailVisible" :header="t('process.title.detail', { entity: entityName })" width="760px" :footer="false">
      <t-loading :loading="detailLoading">
        <div v-if="selectedItem" class="detail-content">
          <t-descriptions bordered :column="2" size="small">
            <t-descriptions-item :label="t('process.field.code')">{{ selectedItem.code }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.field.name')">{{ selectedItem.name }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.field.type')">{{ typeLabel(selectedItem.type) }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.field.unit')">{{ unitLabel(selectedItem.unit) }}</t-descriptions-item>
            <t-descriptions-item :label="t('common.field.status')">
              <t-tag size="small" variant="light" :theme="statusTheme(selectedItem.status)">{{ statusLabel(selectedItem.status) }}</t-tag>
            </t-descriptions-item>
            <t-descriptions-item :label="t('process.field.sort')">{{ selectedItem.sort_order }}</t-descriptions-item>
            <t-descriptions-item :label="t('common.field.createdAt')">{{ formatDateTime(selectedItem.created_at) }}</t-descriptions-item>
            <t-descriptions-item :label="t('common.field.updatedAt')">{{ formatDateTime(selectedItem.updated_at) }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.field.description')">{{ selectedItem.description || '-' }}</t-descriptions-item>
            <t-descriptions-item :label="t('process.field.remark')">{{ selectedItem.remark || '-' }}</t-descriptions-item>
          </t-descriptions>

          <div class="detail-section-title">{{ t('process.field.regionPrice') }}</div>
          <div class="detail-price-list">
            <div v-for="price in displayRegionPrices(selectedItem)" :key="price.region_code" class="detail-price-row">
              <span>{{ regionLabel(price) }}</span>
              <strong>{{ formatPrice(price) }}</strong>
              <t-tag size="small" variant="light" :theme="statusTheme(price.status)">{{ statusLabel(price.status) }}</t-tag>
            </div>
          </div>
          <template v-if="config.moduleKey === 'materials'">
            <div class="detail-section-title">{{ t('process.field.materialComposition') }}</div>
            <t-table row-key="element_code" bordered size="small" :data="materialCompositions" :columns="[
              { colKey: 'element_code', title: t('process.field.element') },
              { colKey: 'element_name', title: t('process.field.name') },
              { colKey: 'content_ratio', title: t('process.field.content'), align: 'right' },
            ]">
              <template #content_ratio="{ row }">{{ (Number(row.content_ratio) * 100).toFixed(2) }}%</template>
            </t-table>
          </template>
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
