<!--
  User Manage Page

  负责：
  1. 展示用户分页列表
  2. 支持用户筛选、新增、编辑、启停、重置密码和删除
  3. 使用 TDesign 表格、分页和按钮统一系统管理交互
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { DeleteIcon, EditIcon, RefreshIcon, UserCheckedIcon, UserLockedIcon, UserPasswordIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';

import { createUser, deleteUser, listUsers, resetUserPassword, updateUser } from '@/api/users';
import type { UserListParams } from '@/api/users';
import { listRoles } from '@/api/roles';
import TableActionButton from '@/components/TableActionButton.vue';
import type { PageResult, RoleInfo, UserInfo } from '@/types/api';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

type UserDialogMode = 'create' | 'edit';
type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const users = ref<PageResult<UserInfo>>(createEmptyPageResult<UserInfo>());
const roles = ref<RoleInfo[]>([]);
const loading = ref(false);
const optionLoading = ref(false);
const dialogVisible = ref(false);
const dialogMode = ref<UserDialogMode>('create');
const editingUserId = ref<number | null>(null);
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const filters = reactive({
  keyword: '',
  status: '',
  role_id: null as number | null,
});
const form = reactive({
  username: '',
  real_name: '',
  password: 'Botree@123456',
  email: '',
  phone: '',
  department: '',
  status: 'enabled',
  role_ids: [] as number[],
});

const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新建用户' : '编辑用户'));

const columns = [
  { colKey: 'username', title: '用户名', width: 150 },
  { colKey: 'real_name', title: '姓名', width: 150 },
  { colKey: 'department', title: '部门', width: 160 },
  { colKey: 'email', title: '邮箱', minWidth: 180 },
  { colKey: 'status', title: '状态', width: 100 },
  { colKey: 'roles', title: '角色', minWidth: 180 },
  { colKey: 'operation', title: '操作', width: 160, fixed: 'right' },
];

function createEmptyPageResult<T>(): PageResult<T> {
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: DEFAULT_PAGE_SIZE,
  };
}

function buildListParams(): UserListParams {
  const params: UserListParams = {
    page: page.value,
    page_size: pageSize.value,
  };
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.status) params.status = filters.status;
  if (filters.role_id) params.role_id = filters.role_id;
  return params;
}

async function loadUsers(): Promise<void> {
  loading.value = true;
  try {
    const result = await listUsers(buildListParams());
    users.value = result;
    page.value = result.page;
    pageSize.value = result.page_size;
  } finally {
    loading.value = false;
  }
}

async function loadRoleOptions(): Promise<void> {
  optionLoading.value = true;
  try {
    roles.value = (await listRoles({ page: 1, page_size: 100 })).items;
  } finally {
    optionLoading.value = false;
  }
}

async function reloadAfterMutation(): Promise<void> {
  if (users.value.items.length === 1 && page.value > 1) {
    page.value -= 1;
  }
  await loadUsers();
}

function resetForm(): void {
  Object.assign(form, {
    username: '',
    real_name: '',
    password: 'Botree@123456',
    email: '',
    phone: '',
    department: '',
    status: 'enabled',
    role_ids: [],
  });
  editingUserId.value = null;
}

function openCreateDialog(): void {
  dialogMode.value = 'create';
  resetForm();
  dialogVisible.value = true;
}

function openEditDialog(user: UserInfo): void {
  dialogMode.value = 'edit';
  editingUserId.value = user.id;
  Object.assign(form, {
    username: user.username,
    real_name: user.real_name,
    password: '',
    email: user.email || '',
    phone: user.phone || '',
    department: user.department || '',
    status: user.status || 'enabled',
    role_ids: user.roles.map((role) => role.id),
  });
  dialogVisible.value = true;
}

function buildSubmitPayload(): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    real_name: form.real_name,
    email: form.email || null,
    phone: form.phone || null,
    department: form.department || null,
    role_ids: form.role_ids,
  };
  if (dialogMode.value === 'create') {
    payload.username = form.username;
    payload.password = form.password || 'Botree@123456';
  } else {
    payload.status = form.status;
  }
  return payload;
}

async function handleSubmit(): Promise<void> {
  if (dialogMode.value === 'create') {
    await createUser(buildSubmitPayload());
    MessagePlugin.success('用户已创建');
  } else if (editingUserId.value) {
    await updateUser(editingUserId.value, buildSubmitPayload());
    MessagePlugin.success('用户已更新');
  }
  dialogVisible.value = false;
  await loadUsers();
}

async function toggleStatus(user: UserInfo): Promise<void> {
  const nextStatus = user.status === 'disabled' ? 'enabled' : 'disabled';
  await updateUser(user.id, {
    status: nextStatus,
  });
  MessagePlugin.success(nextStatus === 'enabled' ? '用户已启用' : '用户已停用');
  await loadUsers();
}

async function handleResetPassword(user: UserInfo): Promise<void> {
  const result = await resetUserPassword(user.id);
  MessagePlugin.success(`密码已重置为 ${result.default_password}`);
}

async function handleDelete(user: UserInfo): Promise<void> {
  await deleteUser(user.id);
  MessagePlugin.success('用户已删除');
  await reloadAfterMutation();
}

function handleSearch(): void {
  page.value = 1;
  void loadUsers();
}

function clearFilters(): void {
  Object.assign(filters, { keyword: '', status: '', role_id: null });
  page.value = 1;
  void loadUsers();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  page.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  void loadUsers();
}

function statusLabel(status: string): string {
  return status === 'disabled' ? '停用' : '启用';
}

function statusTheme(status: string): TagTheme {
  return status === 'disabled' ? 'danger' : 'success';
}

function roleNames(userRoles: UserInfo['roles']): string {
  return userRoles.map((role) => role.name).join('、') || '-';
}

onMounted(async () => {
  await Promise.all([loadRoleOptions(), loadUsers()]);
});
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item label="关键字">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="用户名 / 姓名 / 邮箱 / 部门" @enter="handleSearch" />
      </t-form-item>
      <t-form-item label="状态">
        <t-select v-model="filters.status" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
          <t-option label="启用" value="enabled" />
          <t-option label="停用" value="disabled" />
        </t-select>
      </t-form-item>
      <t-form-item label="角色">
        <t-select
          v-model="filters.role_id"
          class="filter-select"
          clearable
          filterable
          :loading="optionLoading"
          placeholder="全部角色"
          @change="handleSearch"
        >
          <t-option v-for="role in roles" :key="role.id" :value="role.id" :label="role.name" />
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
        <h2>用户列表</h2>
        <span>共 {{ users.total }} 条数据</span>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="loadUsers">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="'user:create'" theme="primary" @click="openCreateDialog">新建用户</t-button>
      </t-space>
    </div>

    <div class="table-scroll">
      <t-table
        row-key="id"
        bordered
        table-layout="fixed"
        :data="users.items"
        :columns="columns"
        :loading="loading"
        empty="暂无用户"
      >
        <template #department="{ row }">
          {{ row.department || '-' }}
        </template>
        <template #email="{ row }">
          {{ row.email || '-' }}
        </template>
        <template #status="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.status)">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #roles="{ row }">
          {{ roleNames(row.roles) }}
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton label="编辑" permission="user:edit" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <TableActionButton :label="row.status === 'disabled' ? '启用' : '停用'" permission="user:status" @click="toggleStatus(row)">
              <UserCheckedIcon v-if="row.status === 'disabled'" />
              <UserLockedIcon v-else />
            </TableActionButton>
            <t-popconfirm content="确认重置该用户密码？" @confirm="handleResetPassword(row)">
              <TableActionButton label="重置密码" permission="user:reset-password">
                <UserPasswordIcon />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm content="确认删除该用户？" @confirm="handleDelete(row)">
              <TableActionButton label="删除" permission="user:delete" theme="danger">
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
        :total="users.total"
        :page-size-options="PAGE_SIZE_OPTIONS"
        show-jumper
        @change="handlePaginationChange"
      />
    </div>

    <t-dialog v-model:visible="dialogVisible" :header="dialogTitle" width="560px" @confirm="handleSubmit">
      <t-form :data="form" label-align="top">
        <t-form-item label="用户名"><t-input v-model="form.username" :disabled="dialogMode === 'edit'" /></t-form-item>
        <t-form-item v-if="dialogMode === 'create'" label="初始密码"><t-input v-model="form.password" type="password" /></t-form-item>
        <t-form-item label="姓名"><t-input v-model="form.real_name" /></t-form-item>
        <t-form-item label="邮箱"><t-input v-model="form.email" /></t-form-item>
        <t-form-item label="电话"><t-input v-model="form.phone" /></t-form-item>
        <t-form-item label="部门"><t-input v-model="form.department" /></t-form-item>
        <t-form-item v-if="dialogMode === 'edit'" label="状态">
          <t-radio-group v-model="form.status">
            <t-radio-button value="enabled">启用</t-radio-button>
            <t-radio-button value="disabled">停用</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="角色">
          <t-select v-model="form.role_ids" multiple filterable :loading="optionLoading" placeholder="请选择角色">
            <t-option v-for="role in roles" :key="role.id" :value="role.id" :label="role.name" />
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
