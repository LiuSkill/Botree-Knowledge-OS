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
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';

import { createUser, deleteUser, listUserDepartmentTree, listUsers, resetUserPassword, updateUser } from '@/api/users';
import type { UserAvatarSubmitOptions, UserListParams } from '@/api/users';
import { listRoles } from '@/api/roles';
import TableActionButton from '@/components/TableActionButton.vue';
import UserAvatar from '@/components/UserAvatar.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { DepartmentInfo, PageResult, RoleInfo, SecurityLevel, UserInfo } from '@/types/api';
import { securityLevelLabel, securityLevelTheme } from '@/utils/securityLevels';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

type UserDialogMode = 'create' | 'edit';
type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

interface DepartmentTreeOption {
  label: string;
  value: number;
  disabled?: boolean;
  children?: DepartmentTreeOption[];
}

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];
const AVATAR_MAX_BYTES = 2 * 1024 * 1024;
const AVATAR_ACCEPT = 'image/png,image/jpeg,image/jpg,image/webp';
const AVATAR_CONTENT_TYPES = new Set(['image/png', 'image/jpeg', 'image/jpg', 'image/webp']);
const SECURITY_LEVEL_RANK: Record<SecurityLevel, number> = {
  public: 0,
  internal: 1,
  confidential: 2,
};

const authStore = useAuthStore();
const users = ref<PageResult<UserInfo>>(createEmptyPageResult<UserInfo>());
const roles = ref<RoleInfo[]>([]);
const departments = ref<DepartmentInfo[]>([]);
const loading = ref(false);
const submitting = ref(false);
const optionLoading = ref(false);
const departmentOptionLoading = ref(false);
const dialogVisible = ref(false);
const dialogMode = ref<UserDialogMode>('create');
const editingUserId = ref<number | null>(null);
const editingOriginalDepartmentId = ref<number | null>(null);
const avatarInputRef = ref<HTMLInputElement | null>(null);
const selectedAvatarFile = ref<File | null>(null);
const selectedAvatarPreviewUrl = ref<string | null>(null);
const avatarMarkedForClear = ref(false);
const editingAvatar = reactive({
  userId: null as number | null,
  avatarUrl: null as string | null,
  avatarUpdatedAt: null as string | null,
});
const page = ref(1);
const pageSize = ref(DEFAULT_PAGE_SIZE);
const filters = reactive({
  keyword: '',
  status: '',
  role_id: null as number | null,
  department_id: null as number | null,
});
const form = reactive({
  username: '',
  real_name: '',
  password: 'Botree@123456',
  email: '',
  phone: '',
  department_id: null as number | null,
  status: 'enabled',
  role_ids: [] as number[],
});

const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新建用户' : '编辑用户'));
const avatarDisplayName = computed(() => form.real_name || form.username || '用户');
const selectedAvatarName = computed(() => selectedAvatarFile.value?.name || '');
const departmentFilterOptions = computed(() => toDepartmentOptions(departments.value, false));
const departmentFormOptions = computed(() => toDepartmentOptions(departments.value, true, editingOriginalDepartmentId.value));
const canMaintainAvatar = computed(() =>
  dialogMode.value === 'create'
    ? authStore.hasActionPermission(PERMISSIONS.SYSTEM_USER_CREATE)
    : authStore.hasActionPermission(PERMISSIONS.SYSTEM_USER_EDIT),
);

const columns = [
  { colKey: 'avatar', title: '头像', width: 88, align: 'center' },
  { colKey: 'username', title: '用户名', width: 150 },
  { colKey: 'real_name', title: '姓名', width: 150 },
  { colKey: 'department', title: '所属部门', width: 160 },
  { colKey: 'email', title: '邮箱', minWidth: 180 },
  { colKey: 'status', title: '状态', width: 100 },
  { colKey: 'roles', title: '角色', minWidth: 180 },
  { colKey: 'max_security_level', title: '最高密级', width: 120 },
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
  if (filters.department_id) params.department_id = filters.department_id;
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

async function loadDepartmentOptions(): Promise<void> {
  departmentOptionLoading.value = true;
  try {
    departments.value = await listUserDepartmentTree();
  } finally {
    departmentOptionLoading.value = false;
  }
}

async function reloadAfterMutation(): Promise<void> {
  if (users.value.items.length === 1 && page.value > 1) {
    page.value -= 1;
  }
  await loadUsers();
}

function revokeAvatarPreview(): void {
  if (!selectedAvatarPreviewUrl.value) return;
  URL.revokeObjectURL(selectedAvatarPreviewUrl.value);
  selectedAvatarPreviewUrl.value = null;
}

function resetAvatarState(): void {
  revokeAvatarPreview();
  selectedAvatarFile.value = null;
  avatarMarkedForClear.value = false;
  Object.assign(editingAvatar, {
    userId: null,
    avatarUrl: null,
    avatarUpdatedAt: null,
  });
  if (avatarInputRef.value) avatarInputRef.value.value = '';
}

function validateAvatarFile(file: File): boolean {
  if (!AVATAR_CONTENT_TYPES.has(file.type)) {
    MessagePlugin.warning('头像仅支持 JPG、JPEG、PNG、WEBP 图片');
    return false;
  }
  if (file.size > AVATAR_MAX_BYTES) {
    MessagePlugin.warning('头像文件不能超过 2MB');
    return false;
  }
  return true;
}

function chooseAvatar(): void {
  if (!canMaintainAvatar.value) return;
  if (avatarInputRef.value) avatarInputRef.value.value = '';
  avatarInputRef.value?.click();
}

function handleAvatarChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0] || null;
  if (!file) return;
  if (!validateAvatarFile(file)) {
    input.value = '';
    return;
  }
  revokeAvatarPreview();
  selectedAvatarFile.value = file;
  selectedAvatarPreviewUrl.value = URL.createObjectURL(file);
  avatarMarkedForClear.value = false;
}

function clearAvatarSelection(): void {
  revokeAvatarPreview();
  selectedAvatarFile.value = null;
  if (avatarInputRef.value) avatarInputRef.value.value = '';
}

function clearAvatar(): void {
  if (!canMaintainAvatar.value) return;
  if (selectedAvatarFile.value) {
    clearAvatarSelection();
    return;
  }
  if (dialogMode.value === 'edit' && editingAvatar.avatarUrl) {
    avatarMarkedForClear.value = true;
  }
}

function undoClearAvatar(): void {
  avatarMarkedForClear.value = false;
}

function buildAvatarOptions(): UserAvatarSubmitOptions | undefined {
  if (selectedAvatarFile.value) {
    return { avatarFile: selectedAvatarFile.value };
  }
  if (dialogMode.value === 'edit' && avatarMarkedForClear.value) {
    return { clearAvatar: true };
  }
  return undefined;
}

function resetForm(): void {
  Object.assign(form, {
    username: '',
    real_name: '',
    password: 'Botree@123456',
    email: '',
    phone: '',
    department_id: null,
    status: 'enabled',
    role_ids: [],
  });
  editingUserId.value = null;
  editingOriginalDepartmentId.value = null;
  resetAvatarState();
}

function openCreateDialog(): void {
  dialogMode.value = 'create';
  resetForm();
  dialogVisible.value = true;
}

function openEditDialog(user: UserInfo): void {
  dialogMode.value = 'edit';
  editingUserId.value = user.id;
  resetAvatarState();
  Object.assign(editingAvatar, {
    userId: user.id,
    avatarUrl: user.avatar_url || null,
    avatarUpdatedAt: user.avatar_updated_at || null,
  });
  Object.assign(form, {
    username: user.username,
    real_name: user.real_name,
    password: '',
    email: user.email || '',
    phone: user.phone || '',
    department_id: user.department_id || null,
    status: user.status || 'enabled',
    role_ids: user.roles.map((role) => role.id),
  });
  editingOriginalDepartmentId.value = user.department_id || null;
  dialogVisible.value = true;
}

function buildSubmitPayload(): Record<string, unknown> {
  const payload: Record<string, unknown> = {
    real_name: form.real_name,
    email: form.email || null,
    phone: form.phone || null,
    department_id: form.department_id || null,
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
  submitting.value = true;
  try {
    const avatarOptions = buildAvatarOptions();
    if (dialogMode.value === 'create') {
      await createUser(buildSubmitPayload(), avatarOptions);
      MessagePlugin.success('用户已创建');
    } else if (editingUserId.value) {
      await updateUser(editingUserId.value, buildSubmitPayload(), avatarOptions);
      if (editingUserId.value === authStore.user?.id) {
        await authStore.loadMe();
      }
      MessagePlugin.success('用户已更新');
    }
    dialogVisible.value = false;
    resetAvatarState();
    await loadUsers();
  } finally {
    submitting.value = false;
  }
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
  Object.assign(filters, { keyword: '', status: '', role_id: null, department_id: null });
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

function userMaxSecurityLevel(user: UserInfo): SecurityLevel {
  if (user.max_security_level) return user.max_security_level;
  return user.roles.reduce<SecurityLevel>((current, role) => {
    return SECURITY_LEVEL_RANK[role.security_level] > SECURITY_LEVEL_RANK[current] ? role.security_level : current;
  }, 'public');
}

function departmentDisplay(user: UserInfo): string {
  if (user.department) return user.department;
  if (!user.department_id) return '-';
  return findDepartmentName(user.department_id, departments.value) || '-';
}

function findDepartmentName(departmentId: number, items: DepartmentInfo[]): string | null {
  for (const item of items) {
    if (item.id === departmentId) return item.name;
    const childName = item.children?.length ? findDepartmentName(departmentId, item.children) : null;
    if (childName) return childName;
  }
  return null;
}

function toDepartmentOptions(items: DepartmentInfo[], disableDisabled: boolean, keepEnabledId: number | null = null): DepartmentTreeOption[] {
  return items.map((item) => ({
    label: `${item.name}（${item.code}）${item.status === 'disabled' ? ' - 停用' : ''}`,
    value: item.id,
    disabled: disableDisabled && item.status === 'disabled' && item.id !== keepEnabledId,
    children: item.children?.length ? toDepartmentOptions(item.children, disableDisabled, keepEnabledId) : undefined,
  }));
}

onMounted(async () => {
  await Promise.all([loadRoleOptions(), loadDepartmentOptions(), loadUsers()]);
});

onBeforeUnmount(() => {
  revokeAvatarPreview();
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
      <t-form-item label="所属部门">
        <t-tree-select
          v-model="filters.department_id"
          class="filter-tree-select"
          :data="departmentFilterOptions"
          clearable
          filterable
          :loading="departmentOptionLoading"
          placeholder="全部部门"
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
        <h2>用户列表</h2>
        <span>共 {{ users.total }} 条数据</span>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="loadUsers">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="PERMISSIONS.SYSTEM_USER_CREATE" theme="primary" @click="openCreateDialog">新建用户</t-button>
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
        <template #avatar="{ row }">
          <UserAvatar
            :user-id="row.id"
            :avatar-url="row.avatar_url"
            :avatar-updated-at="row.avatar_updated_at"
            :name="row.real_name || row.username"
            size="34px"
            shape="circle"
          />
        </template>
        <template #department="{ row }">
          {{ departmentDisplay(row) }}
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
        <template #max_security_level="{ row }">
          <t-tag size="small" variant="light" :theme="securityLevelTheme(userMaxSecurityLevel(row))">
            {{ securityLevelLabel(userMaxSecurityLevel(row)) }}
          </t-tag>
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton label="编辑" :permission="PERMISSIONS.SYSTEM_USER_EDIT" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <TableActionButton :label="row.status === 'disabled' ? '启用' : '停用'" :permission="PERMISSIONS.SYSTEM_USER_DISABLE" @click="toggleStatus(row)">
              <UserCheckedIcon v-if="row.status === 'disabled'" />
              <UserLockedIcon v-else />
            </TableActionButton>
            <t-popconfirm content="确认重置该用户密码？" @confirm="handleResetPassword(row)">
              <TableActionButton label="重置密码" :permission="PERMISSIONS.SYSTEM_USER_RESET_PASSWORD">
                <UserPasswordIcon />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm content="确认删除该用户？" @confirm="handleDelete(row)">
              <TableActionButton label="删除" :permission="PERMISSIONS.SYSTEM_USER_DELETE" theme="danger">
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

    <t-dialog v-model:visible="dialogVisible" :header="dialogTitle" width="560px" :confirm-loading="submitting" @confirm="handleSubmit">
      <t-form :data="form" label-align="top">
        <t-form-item label="用户名"><t-input v-model="form.username" :disabled="dialogMode === 'edit'" /></t-form-item>
        <t-form-item label="头像">
          <div class="avatar-maintenance">
            <t-avatar
              v-if="selectedAvatarFile"
              class="avatar-preview"
              :image="selectedAvatarPreviewUrl || undefined"
              shape="circle"
              size="52px"
              :alt="avatarDisplayName"
              @error="revokeAvatarPreview"
            >
              {{ avatarDisplayName.slice(0, 1).toUpperCase() || 'U' }}
            </t-avatar>
            <UserAvatar
              v-else
              :user-id="editingAvatar.userId"
              :avatar-url="avatarMarkedForClear ? null : editingAvatar.avatarUrl"
              :avatar-updated-at="editingAvatar.avatarUpdatedAt"
              :name="avatarDisplayName"
              size="52px"
              shape="circle"
            />
            <div class="avatar-control">
              <input ref="avatarInputRef" class="hidden-file-input" type="file" :accept="AVATAR_ACCEPT" @change="handleAvatarChange" />
              <t-space size="small">
                <t-button variant="outline" :disabled="!canMaintainAvatar" @click="chooseAvatar">
                  {{ selectedAvatarFile || editingAvatar.avatarUrl ? '更换图片' : '选择图片' }}
                </t-button>
                <t-button
                  v-if="selectedAvatarFile || (dialogMode === 'edit' && editingAvatar.avatarUrl && !avatarMarkedForClear)"
                  variant="text"
                  theme="danger"
                  :disabled="!canMaintainAvatar"
                  @click="clearAvatar"
                >
                  {{ selectedAvatarFile ? '移除选择' : '清除头像' }}
                </t-button>
                <t-button v-if="avatarMarkedForClear" variant="text" :disabled="!canMaintainAvatar" @click="undoClearAvatar">撤销清除</t-button>
              </t-space>
              <div class="avatar-helper">
                <span v-if="selectedAvatarName">{{ selectedAvatarName }}</span>
                <span v-else-if="avatarMarkedForClear">保存后将清除头像</span>
                <span v-else>支持 JPG、JPEG、PNG、WEBP，最大 2MB</span>
              </div>
            </div>
          </div>
        </t-form-item>
        <t-form-item v-if="dialogMode === 'create'" label="初始密码"><t-input v-model="form.password" type="password" /></t-form-item>
        <t-form-item label="姓名"><t-input v-model="form.real_name" /></t-form-item>
        <t-form-item label="邮箱"><t-input v-model="form.email" /></t-form-item>
        <t-form-item label="电话"><t-input v-model="form.phone" /></t-form-item>
        <t-form-item label="所属部门">
          <t-tree-select
            v-model="form.department_id"
            :data="departmentFormOptions"
            clearable
            filterable
            :loading="departmentOptionLoading"
            placeholder="请选择所属部门"
          />
        </t-form-item>
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
  scrollbar-gutter: auto;
}

.table-scroll :deep(.t-table) {
  min-width: 100%;
}

.avatar-maintenance {
  display: flex;
  align-items: center;
  gap: 14px;
}

.avatar-preview {
  flex: 0 0 auto;
  background: #2563eb;
  color: #fff;
  font-weight: 700;
}

.avatar-control {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 8px;
}

.avatar-helper {
  color: #64748b;
  font-size: 12px;
  line-height: 1.4;
}

.hidden-file-input {
  display: none;
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
  width: 160px;
}

.filter-tree-select {
  width: 220px;
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
