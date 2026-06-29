<!--
  Operation Log Page

  负责：
  1. 展示系统关键操作日志
  2. 支持按关键字、结果、对象类型和时间分页查询
  3. 使用 TDesign 表格、分页和状态标签统一系统管理体验
-->
<script setup lang="ts">
import { RefreshIcon } from 'tdesign-icons-vue-next';
import { onMounted, reactive, ref } from 'vue';

import { listOperationLogs, type OperationLogFilters } from '@/api/system';
import type { OperationLog, PageResult } from '@/types/api';
import { formatDateTime } from '@/utils/format';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const logs = ref<PageResult<OperationLog>>(createEmptyPageResult<OperationLog>());
const loading = ref(false);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const dateRange = ref<string[]>([]);
const filters = reactive({
  keyword: '',
  result: '',
  target_type: '',
});

const columns = [
  { colKey: 'created_at', title: '时间', width: 170 },
  { colKey: 'username', title: '用户', width: 140 },
  { colKey: 'action', title: '动作', width: 180 },
  { colKey: 'target', title: '对象', width: 180 },
  { colKey: 'result', title: '结果', width: 110 },
  { colKey: 'detail', title: '详情', minWidth: 260 },
];

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
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.result) params.result = filters.result;
  if (filters.target_type.trim()) params.target_type = filters.target_type.trim();
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
  Object.assign(filters, { keyword: '', result: '', target_type: '' });
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
  if (result === 'success') return '成功';
  if (result === 'failed') return '失败';
  if (result === 'running' || result === 'processing') return '处理中';
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

onMounted(loadLogs);
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item label="关键字">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="用户 / 动作 / 详情" @enter="handleSearch" />
      </t-form-item>
      <t-form-item label="结果">
        <t-select v-model="filters.result" class="filter-select" clearable placeholder="全部结果" @change="handleSearch">
          <t-option label="成功" value="success" />
          <t-option label="失败" value="failed" />
        </t-select>
      </t-form-item>
      <t-form-item label="对象">
        <t-input v-model="filters.target_type" class="target-input" clearable placeholder="对象类型" @enter="handleSearch" />
      </t-form-item>
      <t-form-item label="时间">
        <t-date-range-picker
          v-model="dateRange"
          class="filter-date-range"
          clearable
          value-type="YYYY-MM-DD"
          format="YYYY-MM-DD"
          separator="至"
          :placeholder="['开始日期', '结束日期']"
          @change="handleSearch"
        />
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
        <h2>操作日志</h2>
        <span>共 {{ logs.total }} 条数据</span>
      </div>
      <t-button theme="default" variant="outline" @click="loadLogs">
        <template #icon><RefreshIcon /></template>
        刷新
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
        empty="暂无日志"
      >
        <template #created_at="{ row }">
          {{ formatDateTime(row.created_at) }}
        </template>
        <template #username="{ row }">
          {{ row.username || '-' }}
        </template>
        <template #target="{ row }">
          {{ targetLabel(row) }}
        </template>
        <template #result="{ row }">
          <t-tag size="small" variant="light" :theme="resultTheme(row.result)">{{ resultLabel(row.result) }}</t-tag>
        </template>
        <template #detail="{ row }">
          <div class="log-detail">{{ row.detail || '-' }}</div>
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

.target-input {
  width: 160px;
}

.filter-date-range {
  width: 260px;
}

.log-detail {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  line-height: 1.6;
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
