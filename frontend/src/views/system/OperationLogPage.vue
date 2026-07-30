<!--
  Operation Log Page

  负责：
  1. 展示系统关键操作日志
  2. 支持按用户、结果和时间分页查询
  3. 使用 TDesign 表格、分页和状态标签统一系统管理体验
-->
<script setup lang="ts">
import { BrowseIcon, RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import { listOperationLogs, listOperationLogUsers, type OperationLogFilters } from '@/api/system';
import TableActionButton from '@/components/TableActionButton.vue';
import type { OperationLog, OperationLogUserOption, PageResult } from '@/types/api';
import { formatDateTime } from '@/utils/format';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const { t } = useI18n();
const logs = ref<PageResult<OperationLog>>(createEmptyPageResult<OperationLog>());
const loading = ref(false);
const detailVisible = ref(false);
const selectedLog = ref<OperationLog | null>(null);
const userOptions = ref<OperationLogUserOption[]>([]);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const dateRange = ref<string[]>([]);
const filters = reactive({
  user_id: null as number | null,
  result: '',
});

const columns = computed(() => [
  { colKey: 'created_at', title: t('system.log.field.time'), width: 170 },
  { colKey: 'username', title: t('system.log.field.user'), width: 140 },
  { colKey: 'action', title: t('system.log.field.action'), minWidth: 220 },
  { colKey: 'result', title: t('system.log.field.result'), width: 110 },
  { colKey: 'operation', title: t('common.field.operation'), width: 90, align: 'center' as const },
]);

function createEmptyPageResult<T>(): PageResult<T> {
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: DEFAULT_PAGE_SIZE,
  };
}

function buildListParams(): OperationLogFilters {
  const params: OperationLogFilters = {
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.user_id !== null) params.user_id = filters.user_id;
  if (filters.result) params.result = filters.result;
  if (dateRange.value[0]) params.started_at = `${dateRange.value[0]}T00:00:00`;
  if (dateRange.value[1]) params.ended_at = `${dateRange.value[1]}T23:59:59`;
  return params;
}

async function loadLogs(): Promise<void> {
  loading.value = true;
  try {
    const result = await listOperationLogs(buildListParams());
    logs.value = result;
    page.value = result.page;
    pageSize.value = result.page_size;
  } finally {
    loading.value = false;
  }
}

function handleSearch(): void {
  page.value = 1;
  void loadLogs();
}

function clearFilters(): void {
  Object.assign(filters, { user_id: null, result: '' });
  dateRange.value = [];
  page.value = 1;
  void loadLogs();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  void loadLogs();
}

function resultLabel(result: string): string {
  if (result === 'success') return t('system.log.result.success');
  if (result === 'failed') return t('system.log.result.failed');
  if (result === 'running' || result === 'processing') return t('system.log.result.processing');
  return result || '-';
}

function resultTheme(result: string): TagTheme {
  if (result === 'success') return 'success';
  if (result === 'failed') return 'danger';
  if (result === 'running' || result === 'processing') return 'warning';
  return 'default';
}

function targetLabel(log: OperationLog): string {
  const targetId = log.target_id || '-';
  return `${log.target_type || '-'} #${targetId}`;
}

function openDetail(log: OperationLog): void {
  selectedLog.value = log;
  detailVisible.value = true;
}

function displayValue(value: string | number | null | undefined): string {
  return value === null || value === undefined || value === '' ? '-' : String(value);
}

function userDisplayName(log: OperationLog): string {
  return log.real_name || log.username || '-';
}

onMounted(async () => {
  const [, users] = await Promise.all([loadLogs(), listOperationLogUsers()]);
  userOptions.value = users;
});
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item :label="t('system.log.field.user')">
        <t-select
          v-model="filters.user_id"
          class="filter-input"
          clearable
          filterable
          :placeholder="t('system.log.placeholder.user')"
          @change="handleSearch"
        >
          <t-option v-for="user in userOptions" :key="user.id" :value="user.id" :label="user.real_name || user.username" />
        </t-select>
      </t-form-item>
      <t-form-item :label="t('system.log.field.result')">
        <t-select v-model="filters.result" class="filter-select" clearable :placeholder="t('system.log.placeholder.allResults')" @change="handleSearch">
          <t-option :label="t('system.log.result.success')" value="success" />
          <t-option :label="t('system.log.result.failed')" value="failed" />
        </t-select>
      </t-form-item>
      <t-form-item :label="t('system.log.field.dateRange')">
        <t-date-range-picker
          v-model="dateRange"
          class="filter-date-range"
          clearable
          value-type="YYYY-MM-DD"
          format="YYYY-MM-DD"
          :separator="t('common.date.rangeSeparator')"
          :placeholder="[t('common.date.startDate'), t('common.date.endDate')]"
          @change="handleSearch"
        />
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
        <h2>{{ t('system.log.title') }}</h2>
        <span>{{ t('system.summary.totalRecords', { count: logs.total }) }}</span>
      </div>
      <t-button theme="default" variant="outline" @click="loadLogs">
        <template #icon><RefreshIcon /></template>
        {{ t('system.action.refresh') }}
      </t-button>
    </div>

    <div class="table-scroll">
      <t-table
        row-key="id"
        bordered
        table-layout="fixed"
        vertical-align="top"
        :data="logs.items"
        :columns="columns"
        :loading="loading"
        :empty="t('system.log.empty')"
      >
        <template #created_at="{ row }">
          {{ formatDateTime(row.created_at) }}
        </template>
        <template #username="{ row }">
          {{ userDisplayName(row) }}
        </template>
        <template #result="{ row }">
          <t-tag size="small" variant="light" :theme="resultTheme(row.result)">{{ resultLabel(row.result) }}</t-tag>
        </template>
        <template #operation="{ row }">
          <TableActionButton :label="t('system.log.action.viewDetail')" @click="openDetail(row)">
            <BrowseIcon />
          </TableActionButton>
        </template>
      </t-table>
    </div>

    <div class="system-pagination">
      <t-pagination
        :current="page"
        :page-size="pageSize"
        :total="logs.total"
        :page-size-options="PAGE_SIZE_OPTIONS"
        show-jumper
        @change="handlePaginationChange"
      />
    </div>

    <t-dialog v-model:visible="detailVisible" :header="t('system.log.detailTitle')" width="720px" :footer="false">
      <t-descriptions v-if="selectedLog" bordered :column="2" label-align="left">
        <t-descriptions-item :label="t('system.log.field.time')">{{ formatDateTime(selectedLog.created_at) }}</t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.user')">{{ userDisplayName(selectedLog) }}</t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.action')">{{ displayValue(selectedLog.action) }}</t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.result')">
          <t-tag size="small" variant="light" :theme="resultTheme(selectedLog.result)">{{ resultLabel(selectedLog.result) }}</t-tag>
        </t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.target')">{{ targetLabel(selectedLog) }}</t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.projectId')">{{ displayValue(selectedLog.project_id) }}</t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.ipAddress')">{{ displayValue(selectedLog.ip_address) }}</t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.userId')">{{ displayValue(selectedLog.user_id) }}</t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.detail')" :span="2">
          <pre class="detail-content">{{ displayValue(selectedLog.detail) }}</pre>
        </t-descriptions-item>
        <t-descriptions-item :label="t('system.log.field.userAgent')" :span="2">
          <div class="detail-content">{{ displayValue(selectedLog.user_agent) }}</div>
        </t-descriptions-item>
      </t-descriptions>
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
  width: 220px;
}

.filter-select {
  width: 132px;
}

.filter-date-range {
  width: 260px;
}

.detail-content {
  margin: 0;
  max-height: 240px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
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
