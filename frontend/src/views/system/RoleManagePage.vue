<!--
  Role Manage Page

  负责：
  1. 展示角色分页表格
  2. 支持角色筛选、新增、编辑权限、启停和删除
  3. 使用 TDesign 组件统一系统管理行内操作
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';

import { createRole, deleteRole, getPermissionMatrix, listRoles, updateRole } from '@/api/roles';
import type { RoleListParams } from '@/api/roles';
import type { PageResult, PermissionInfo, RoleInfo } from '@/types/api';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

type RoleDialogMode = 'create' | 'edit';
type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const roles = ref<PageResult<RoleInfo>>(createEmptyPageResult<RoleInfo>());
const permissions = ref<PermissionInfo[]>([]);
const loading = ref(false);
const optionLoading = ref(false);
const dialogVisible = ref(false);
const dialogMode = ref<RoleDialogMode>('create');
const editingRoleId = ref<number | null>(null);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const filters = reactive({
  keyword: '',
  enabled: '',
});
const form = reactive({
  name: '',
  code: '',
  description: '',
  enabled: true,
  permission_ids: [] as number[],
});

const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新建角色' : '编辑角色'));

const columns = [
  { colKey: 'name', title: '角色名称', width: 160 },
  { colKey: 'code', title: '角色编码', width: 160 },
  { colKey: 'description', title: '描述', minWidth: 220 },
  { colKey: 'enabled', title: '状态', width: 100 },
  { colKey: 'permissions', title: '权限数', width: 100, align: 'center' },
  { colKey: 'operation', title: '操作', width: 210, fixed: 'right' },
];

function createEmptyPageResult<T>(): PageResult<T> {
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: DEFAULT_PAGE_SIZE,
  };
}

function buildListParams(): RoleListParams {
  const params: RoleListParams = {
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.enabled) params.enabled = filters.enabled === 'enabled';
  return params;
}

async function loadRoles(): Promise<void> {
  loading.value = true;
  try {
    const result = await listRoles(buildListParams());
    roles.value = result;
    page.value = result.page;
    pageSize.value = result.page_size;
  } finally {
    loading.value = false;
  }
}

async function loadPermissions(): Promise<void> {
  optionLoading.value = true;
  try {
    permissions.value = (await getPermissionMatrix()).permissions;
  } finally {
    optionLoading.value = false;
  }
}

async function reloadAfterMutation(): Promise<void> {
  if (roles.value.items.length === 1 && page.value > 1) {
    page.value -= 1;
  }
  await loadRoles();
}

function resetForm(): void {
  Object.assign(form, {
    name: '',
    code: '',
    description: '',
    enabled: true,
    permission_ids: [],
  });
  editingRoleId.value = null;
}

function openCreateDialog(): void {
  dialogMode.value = 'create';
  resetForm();
  dialogVisible.value = true;
}

function openEditDialog(role: RoleInfo): void {
  dialogMode.value = 'edit';
  editingRoleId.value = role.id;
  Object.assign(form, {
    name: role.name,
    code: role.code,
    description: role.description || '',
    enabled: role.enabled,
    permission_ids: (role.permissions || []).map((permission) => permission.id),
  });
  dialogVisible.value = true;
}

function buildSubmitPayload(): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    name: form.name,
    description: form.description || null,
    permission_ids: form.permission_ids,
  };
  if (dialogMode.value === 'create') {
    payload.code = form.code;
  } else {
    payload.enabled = form.enabled;
  }
  return payload;
}

async function handleSubmit(): Promise<void> {
  if (dialogMode.value === 'create') {
    await createRole(buildSubmitPayload());
    MessagePlugin.success('角色已创建');
  } else if (editingRoleId.value) {
    await updateRole(editingRoleId.value, buildSubmitPayload());
    MessagePlugin.success('角色已更新');
  }
  dialogVisible.value = false;
  await loadRoles();
}

async function toggleRole(role: RoleInfo): Promise<void> {
  await updateRole(role.id, {
    enabled: !role.enabled,
    permission_ids: (role.permissions || []).map((permission) => permission.id),
  });
  MessagePlugin.success(role.enabled ? '角色已停用' : '角色已启用');
  await loadRoles();
}

async function handleDelete(role: RoleInfo): Promise<void> {
  await deleteRole(role.id);
  MessagePlugin.success('角色已删除');
  await reloadAfterMutation();
}

function handleSearch(): void {
  page.value = 1;
  void loadRoles();
}

function clearFilters(): void {
  Object.assign(filters, { keyword: '', enabled: '' });
  page.value = 1;
  void loadRoles();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  void loadRoles();
}

function statusTheme(enabled: boolean): TagTheme {
  return enabled ? 'success' : 'danger';
}

function permissionLabel(permission: PermissionInfo): string {
  return `${permission.module} / ${permission.code}`;
}

onMounted(async () => {
  await Promise.all([loadPermissions(), loadRoles()]);
});
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item label="关键字">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="角色名称 / 编码 / 描述" @enter="handleSearch" />
      </t-form-item>
      <t-form-item label="状态">
        <t-select v-model="filters.enabled" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
          <t-option label="启用" value="enabled" />
          <t-option label="停用" value="disabled" />
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
        <h2>角色列表</h2>
        <span>共 {{ roles.total }} 条数据</span>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="loadRoles">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button theme="primary" @click="openCreateDialog">新建角色</t-button>
      </t-space>
    </div>

    <div class="table-scroll">
      <t-table
        row-key="id"
        bordered
        table-layout="fixed"
        :data="roles.items"
        :columns="columns"
        :loading="loading"
        empty="暂无角色"
      >
        <template #description="{ row }">
          {{ row.description || '-' }}
        </template>
        <template #enabled="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.enabled)">{{ row.enabled ? '启用' : '停用' }}</t-tag>
        </template>
        <template #permissions="{ row }">
          {{ (row.permissions || []).length }}
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <t-button size="small" variant="text" @click="openEditDialog(row)">编辑</t-button>
            <t-button size="small" variant="text" @click="toggleRole(row)">{{ row.enabled ? '停用' : '启用' }}</t-button>
            <t-popconfirm content="确认删除该角色？" @confirm="handleDelete(row)">
              <t-button size="small" variant="text" theme="danger">删除</t-button>
            </t-popconfirm>
          </t-space>
        </template>
      </t-table>
    </div>

    <div class="system-pagination">
      <t-pagination
        :current="page"
        :page-size="pageSize"
        :total="roles.total"
        :page-size-options="PAGE_SIZE_OPTIONS"
        show-jumper
        @change="handlePaginationChange"
      />
    </div>

    <t-dialog v-model:visible="dialogVisible" :header="dialogTitle" width="620px" @confirm="handleSubmit">
      <t-form :data="form" label-align="top">
        <t-form-item label="角色名称"><t-input v-model="form.name" /></t-form-item>
        <t-form-item label="角色编码"><t-input v-model="form.code" :disabled="dialogMode === 'edit'" /></t-form-item>
        <t-form-item label="描述"><t-textarea v-model="form.description" /></t-form-item>
        <t-form-item v-if="dialogMode === 'edit'" label="状态">
          <t-radio-group v-model="form.enabled">
            <t-radio-button :value="true">启用</t-radio-button>
            <t-radio-button :value="false">停用</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="权限">
          <t-select v-model="form.permission_ids" multiple filterable :loading="optionLoading" placeholder="请选择权限">
            <t-option
              v-for="permission in permissions"
              :key="permission.id"
              :value="permission.id"
              :label="permissionLabel(permission)"
            />
          </t-select>
        </t-form-item>
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
  scrollbar-gutter: stable;
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
  border-radius: 6px;
  background: #f7f9fc;
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
  width: 160px;
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
