<script setup lang="ts">
import { AddIcon, CopyIcon, DownloadIcon, HistoryIcon, RefreshIcon, UploadIcon } from 'tdesign-icons-vue-next';
import { reactive, ref } from 'vue';

import type { PermissionCode } from '@/constants/permissions';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

interface ProcessConfigPagePermissions {
  view: PermissionCode;
  create: PermissionCode;
  update: PermissionCode;
  delete: PermissionCode;
  import: PermissionCode;
  export: PermissionCode;
  copy?: PermissionCode;
  version?: PermissionCode;
}

const props = defineProps<{
  title: string;
  permissions: ProcessConfigPagePermissions;
}>();

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const filters = reactive({
  keyword: '',
  status: '',
});
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const loading = ref(false);
const rows = ref([]);

const columns = [
  { colKey: 'code', title: '编码', width: 160 },
  { colKey: 'name', title: '名称', minWidth: 180 },
  { colKey: 'type', title: '类型', width: 140 },
  { colKey: 'unit', title: '单位', width: 110 },
  { colKey: 'status', title: '状态', width: 110 },
  { colKey: 'updated_at', title: '更新时间', width: 170 },
  { colKey: 'operation', title: '操作', fixed: 'right', width: 150 },
];

function handleSearch(): void {
  page.value = 1;
}

function clearFilters(): void {
  filters.keyword = '';
  filters.status = '';
  page.value = 1;
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
}
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item v-permission="props.permissions.view" label="关键词">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="编码 / 名称 / 类型" @enter="handleSearch" />
      </t-form-item>
      <t-form-item v-permission="props.permissions.view" label="状态">
        <t-select v-model="filters.status" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
          <t-option label="启用" value="enabled" />
          <t-option label="草稿" value="draft" />
          <t-option label="停用" value="disabled" />
        </t-select>
      </t-form-item>
      <t-form-item>
        <t-space>
          <t-button v-permission="props.permissions.view" theme="primary" @click="handleSearch">查询</t-button>
          <t-button v-permission="props.permissions.view" @click="clearFilters">重置</t-button>
        </t-space>
      </t-form-item>
    </t-form>

    <div class="system-section-head">
      <div class="system-section-title">
        <h2>{{ props.title }}</h2>
        <span>共 0 条数据</span>
      </div>
      <t-space>
        <t-button v-permission="props.permissions.view" theme="default" variant="outline" :loading="loading" @click="handleSearch">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="props.permissions.import" theme="default" variant="outline" disabled>
          <template #icon><UploadIcon /></template>
          导入
        </t-button>
        <t-button v-permission="props.permissions.export" theme="default" variant="outline" disabled>
          <template #icon><DownloadIcon /></template>
          导出
        </t-button>
        <t-button v-if="props.permissions.copy" v-permission="props.permissions.copy" theme="default" variant="outline" disabled>
          <template #icon><CopyIcon /></template>
          复制
        </t-button>
        <t-button v-if="props.permissions.version" v-permission="props.permissions.version" theme="default" variant="outline" disabled>
          <template #icon><HistoryIcon /></template>
          版本
        </t-button>
        <t-button v-permission="props.permissions.create" theme="primary" disabled>
          <template #icon><AddIcon /></template>
          新增
        </t-button>
      </t-space>
    </div>

    <div class="table-scroll">
      <t-table
        row-key="id"
        bordered
        table-layout="fixed"
        vertical-align="top"
        :data="rows"
        :columns="columns"
        :loading="loading"
        empty="暂无配置数据"
      >
        <template #operation>
          <t-space size="small">
            <t-link v-permission="props.permissions.update" theme="primary" disabled>编辑</t-link>
            <t-link v-permission="props.permissions.delete" theme="danger" disabled>删除</t-link>
          </t-space>
        </template>
      </t-table>
    </div>

    <div v-permission="props.permissions.view" class="system-pagination">
      <t-pagination
        :current="page"
        :page-size="pageSize"
        :total="0"
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
</style>
