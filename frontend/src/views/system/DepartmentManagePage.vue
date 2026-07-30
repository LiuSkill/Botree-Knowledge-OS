<!--
  Department Manage Page

  负责：
  1. 维护企业组织部门树、上下级关系和负责人。
  2. 将新增、编辑、启停、删除等操作与权限矩阵保持一致。
  3. 前端校验只做交互兜底，最终业务规则由后端 Service 统一校验。
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { AddIcon, BrowseIcon, CheckCircleIcon, CloseCircleIcon, DeleteIcon, EditIcon, RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import {
  createDepartment,
  deleteDepartment,
  getDepartment,
  listDepartmentTree,
  listDepartmentUserOptions,
  updateDepartment,
  updateDepartmentStatus,
} from '@/api/departments';
import type { DepartmentSubmitPayload } from '@/api/departments';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import type { DepartmentInfo, DepartmentStatus, DepartmentUserOption } from '@/types/api';
import { formatDateTime } from '@/utils/format';

type DepartmentDialogMode = 'create' | 'edit';
type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

interface TreeOption {
  label: string;
  value: number;
  disabled?: boolean;
  children?: TreeOption[];
}

const departments = ref<DepartmentInfo[]>([]);
const { t } = useI18n();
const expandedDepartmentIds = ref<Array<string | number>>([]);
const leaderOptions = ref<DepartmentUserOption[]>([]);
const selectedDepartment = ref<DepartmentInfo | null>(null);
const loading = ref(false);
const submitting = ref(false);
const userOptionLoading = ref(false);
const detailLoading = ref(false);
const dialogVisible = ref(false);
const detailVisible = ref(false);
const dialogMode = ref<DepartmentDialogMode>('create');
const editingDepartmentId = ref<number | null>(null);

const filters = reactive({
  keyword: '',
  status: '' as DepartmentStatus | '',
});

const form = reactive({
  name: '',
  code: '',
  parent_id: null as number | null,
  leader_user_id: null as number | null,
  sort_order: 0,
  status: 'enabled' as DepartmentStatus,
  description: '',
});

const columns = computed(() => [
  { colKey: 'name', title: t('system.department.field.name'), minWidth: 180 },
  { colKey: 'parent_name', title: t('system.department.field.parent'), width: 150, ellipsis: true },
  { colKey: 'leader_name', title: t('system.department.field.leader'), width: 150, ellipsis: true },
  { colKey: 'status', title: t('common.field.status'), width: 100, align: 'center' as const },
  { colKey: 'created_at', title: t('common.field.createdAt'), width: 170 },
  { colKey: 'operation', title: t('common.field.operation'), width: 230, fixed: 'right' as const },
]);

const treeConfig = {
  childrenKey: 'children',
  treeNodeColumnIndex: 0,
};

const dialogTitle = computed(() => (dialogMode.value === 'create' ? t('system.department.dialog.create') : t('system.department.dialog.edit')));
const departmentTotal = computed(() => countDepartments(departments.value));
const parentTreeOptions = computed(() => {
  const disabledIds = editingDepartmentId.value ? collectDepartmentAndDescendantIds(editingDepartmentId.value, departments.value) : new Set<number>();
  return toDepartmentOptions(departments.value, disabledIds);
});

function buildQueryParams(): { keyword?: string; status?: DepartmentStatus } {
  const params: { keyword?: string; status?: DepartmentStatus } = {};
  if (filters.keyword.trim()) params.keyword = filters.keyword.trim();
  if (filters.status) params.status = filters.status;
  return params;
}

async function loadDepartments(): Promise<void> {
  loading.value = true;
  try {
    departments.value = await listDepartmentTree(buildQueryParams());
    expandedDepartmentIds.value = collectExpandableDepartmentIds(departments.value);
  } finally {
    loading.value = false;
  }
}

async function loadLeaderOptions(): Promise<void> {
  userOptionLoading.value = true;
  try {
    leaderOptions.value = await listDepartmentUserOptions();
  } finally {
    userOptionLoading.value = false;
  }
}

async function refreshAll(): Promise<void> {
  await Promise.all([loadDepartments(), loadLeaderOptions()]);
}

function resetForm(parentId: number | null = null): void {
  Object.assign(form, {
    name: '',
    code: '',
    parent_id: parentId,
    leader_user_id: null,
    sort_order: 0,
    status: 'enabled',
    description: '',
  });
  editingDepartmentId.value = null;
}

function openCreateDialog(parent?: DepartmentInfo): void {
  dialogMode.value = 'create';
  resetForm(parent?.id || null);
  dialogVisible.value = true;
}

function openEditDialog(department: DepartmentInfo): void {
  dialogMode.value = 'edit';
  editingDepartmentId.value = department.id;
  Object.assign(form, {
    name: department.name,
    code: department.code,
    parent_id: department.parent_id || null,
    leader_user_id: department.leader_user_id || null,
    sort_order: department.sort_order,
    status: department.status,
    description: department.description || '',
  });
  dialogVisible.value = true;
}

async function openDetailDialog(department: DepartmentInfo): Promise<void> {
  detailVisible.value = true;
  detailLoading.value = true;
  selectedDepartment.value = null;
  try {
    selectedDepartment.value = await getDepartment(department.id);
  } finally {
    detailLoading.value = false;
  }
}

function buildSubmitPayload(): DepartmentSubmitPayload {
  return {
    name: form.name.trim(),
    code: form.code.trim(),
    parent_id: form.parent_id || null,
    leader_user_id: form.leader_user_id || null,
    sort_order: Number(form.sort_order || 0),
    status: form.status,
    description: form.description.trim() || null,
  };
}

function validateForm(): boolean {
  if (!form.name.trim()) {
    MessagePlugin.warning(t('system.department.validation.nameRequired'));
    return false;
  }
  if (!form.code.trim()) {
    MessagePlugin.warning(t('system.department.validation.codeRequired'));
    return false;
  }
  if (!/^[A-Za-z0-9_-]{2,50}$/.test(form.code.trim())) {
    MessagePlugin.warning(t('system.department.validation.codeFormat'));
    return false;
  }
  if (!Number.isInteger(Number(form.sort_order)) || Number(form.sort_order) < 0 || Number(form.sort_order) > 999999) {
    MessagePlugin.warning(t('system.department.validation.sortRange'));
    return false;
  }
  if (!['enabled', 'disabled'].includes(form.status)) {
    MessagePlugin.warning(t('system.department.validation.statusRequired'));
    return false;
  }
  if (editingDepartmentId.value && form.parent_id) {
    const disabledIds = collectDepartmentAndDescendantIds(editingDepartmentId.value, departments.value);
    if (disabledIds.has(form.parent_id)) {
      MessagePlugin.warning(t('system.department.validation.invalidParent'));
      return false;
    }
  }
  return true;
}

async function handleSubmit(): Promise<void> {
  if (!validateForm()) return;
  submitting.value = true;
  try {
    const payload = buildSubmitPayload();
    if (dialogMode.value === 'create') {
      await createDepartment(payload);
      MessagePlugin.success(t('system.department.message.created'));
    } else if (editingDepartmentId.value) {
      await updateDepartment(editingDepartmentId.value, payload);
      MessagePlugin.success(t('system.department.message.updated'));
    }
    dialogVisible.value = false;
    await loadDepartments();
  } finally {
    submitting.value = false;
  }
}

async function handleToggleStatus(department: DepartmentInfo): Promise<void> {
  const nextStatus: DepartmentStatus = department.status === 'disabled' ? 'enabled' : 'disabled';
  await updateDepartmentStatus(department.id, nextStatus);
  MessagePlugin.success(nextStatus === 'enabled' ? t('system.department.message.enabled') : t('system.department.message.disabled'));
  await loadDepartments();
}

async function handleDelete(department: DepartmentInfo): Promise<void> {
  await deleteDepartment(department.id);
  MessagePlugin.success(t('system.department.message.deleted'));
  await loadDepartments();
}

function handleSearch(): void {
  void loadDepartments();
}

function clearFilters(): void {
  Object.assign(filters, { keyword: '', status: '' });
  void loadDepartments();
}

function statusLabel(status: DepartmentStatus | string): string {
  return status === 'disabled' ? t('system.status.disabled') : t('system.status.enabled');
}

function statusTheme(status: DepartmentStatus | string): TagTheme {
  return status === 'disabled' ? 'danger' : 'success';
}

function statusActionPermission(department: DepartmentInfo): string {
  return department.status === 'disabled' ? PERMISSIONS.SYSTEM_DEPARTMENT_ENABLE : PERMISSIONS.SYSTEM_DEPARTMENT_DISABLE;
}

function statusActionLabel(department: DepartmentInfo): string {
  return department.status === 'disabled' ? t('system.action.enable') : t('system.action.disable');
}

function confirmStatusText(department: DepartmentInfo): string {
  return department.status === 'disabled' ? t('system.department.confirm.enable') : t('system.department.confirm.disable');
}

function toDepartmentOptions(items: DepartmentInfo[], disabledIds: Set<number>): TreeOption[] {
  return items.map((item) => ({
    label: `${item.name} (${item.code})`,
    value: item.id,
    disabled: disabledIds.has(item.id),
    children: item.children?.length ? toDepartmentOptions(item.children, disabledIds) : undefined,
  }));
}

function collectDepartmentAndDescendantIds(departmentId: number, items: DepartmentInfo[]): Set<number> {
  const ids = new Set<number>();
  const visit = (nodes: DepartmentInfo[]): boolean => {
    for (const node of nodes) {
      if (node.id === departmentId) {
        collectIds(node, ids);
        return true;
      }
      if (node.children?.length && visit(node.children)) return true;
    }
    return false;
  };
  visit(items);
  return ids;
}

function collectIds(department: DepartmentInfo, ids: Set<number>): void {
  ids.add(department.id);
  department.children?.forEach((child) => collectIds(child, ids));
}

function countDepartments(items: DepartmentInfo[]): number {
  return items.reduce((total, item) => total + 1 + countDepartments(item.children || []), 0);
}

function collectExpandableDepartmentIds(items: DepartmentInfo[]): number[] {
  return items.flatMap((item) => {
    if (!item.children?.length) return [];
    return [item.id, ...collectExpandableDepartmentIds(item.children)];
  });
}

onMounted(async () => {
  await refreshAll();
});
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item :label="t('system.department.field.name')">
        <t-input v-model="filters.keyword" class="filter-input" clearable :placeholder="t('system.department.placeholder.keyword')" @enter="handleSearch" />
      </t-form-item>
      <t-form-item :label="t('system.department.field.status')">
        <t-select v-model="filters.status" class="filter-select" clearable :placeholder="t('system.status.all')" @change="handleSearch">
          <t-option :label="t('system.status.enabled')" value="enabled" />
          <t-option :label="t('system.status.disabled')" value="disabled" />
        </t-select>
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
        <h2>{{ t('system.department.title') }}</h2>
        <span>{{ t('system.summary.totalDepartments', { count: departmentTotal }) }}</span>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="refreshAll">
          <template #icon><RefreshIcon /></template>
          {{ t('system.action.refresh') }}
        </t-button>
        <t-button v-permission="PERMISSIONS.SYSTEM_DEPARTMENT_CREATE" theme="primary" @click="openCreateDialog()">
          <template #icon><AddIcon /></template>
          {{ t('system.department.action.create') }}
        </t-button>
      </t-space>
    </div>

    <div class="table-scroll">
      <t-enhanced-table
        row-key="id"
        bordered
        table-layout="fixed"
        :data="departments"
        :columns="columns"
        :tree="treeConfig"
        v-model:expanded-tree-nodes="expandedDepartmentIds"
        :loading="loading"
        :empty="t('system.department.empty')"
      >
        <template #parent_name="{ row }">
          {{ row.parent_name || '-' }}
        </template>
        <template #leader_name="{ row }">
          {{ row.leader_name || '-' }}
        </template>
        <template #status="{ row }">
          <t-tag size="small" variant="light" :theme="statusTheme(row.status)">{{ statusLabel(row.status) }}</t-tag>
        </template>
        <template #created_at="{ row }">
          {{ formatDateTime(row.created_at) }}
        </template>
        <template #operation="{ row }">
          <t-space size="small">
            <TableActionButton :label="t('system.action.view')" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_VIEW_DETAIL" @click="openDetailDialog(row)">
              <BrowseIcon />
            </TableActionButton>
            <TableActionButton :label="t('system.action.edit')" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_EDIT" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <TableActionButton :label="t('system.department.action.createChild')" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_CREATE" @click="openCreateDialog(row)">
              <AddIcon />
            </TableActionButton>
            <t-popconfirm :content="confirmStatusText(row)" @confirm="handleToggleStatus(row)">
              <TableActionButton :label="statusActionLabel(row)" :permission="statusActionPermission(row)">
                <CheckCircleIcon v-if="row.status === 'disabled'" />
                <CloseCircleIcon v-else />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm :content="t('system.department.confirm.delete')" @confirm="handleDelete(row)">
              <TableActionButton :label="t('system.action.delete')" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_DELETE" theme="danger">
                <DeleteIcon />
              </TableActionButton>
            </t-popconfirm>
          </t-space>
        </template>
      </t-enhanced-table>
    </div>

    <t-dialog v-model:visible="dialogVisible" :header="dialogTitle" width="620px" :confirm-loading="submitting" @confirm="handleSubmit">
      <t-form :data="form" label-align="top">
        <t-form-item :label="t('system.department.field.name')" required-mark>
          <t-input v-model="form.name" clearable maxlength="100" :placeholder="t('system.department.validation.nameRequired')" />
        </t-form-item>
        <t-form-item :label="t('system.department.field.code')" required-mark>
          <t-input v-model="form.code" clearable maxlength="50" :placeholder="t('system.department.placeholder.code')" />
        </t-form-item>
        <t-form-item :label="t('system.department.field.parent')">
          <t-tree-select v-model="form.parent_id" :data="parentTreeOptions" clearable filterable :placeholder="t('system.department.placeholder.noParent')" />
        </t-form-item>
        <t-form-item :label="t('system.department.field.leader')">
          <t-select v-model="form.leader_user_id" clearable filterable :loading="userOptionLoading" :placeholder="t('system.department.placeholder.leader')">
            <t-option v-for="user in leaderOptions" :key="user.id" :value="user.id" :label="`${user.real_name} (${user.username})`" />
          </t-select>
        </t-form-item>
        <t-form-item :label="t('system.department.field.sort')" required-mark>
          <t-input-number v-model="form.sort_order" :min="0" :max="999999" :step="1" />
        </t-form-item>
        <t-form-item :label="t('common.field.status')" required-mark>
          <t-radio-group v-model="form.status">
            <t-radio-button value="enabled">{{ t('system.status.enabled') }}</t-radio-button>
            <t-radio-button value="disabled">{{ t('system.status.disabled') }}</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <t-form-item :label="t('system.department.field.remark')">
          <t-textarea v-model="form.description" maxlength="500" autosize :placeholder="t('system.department.placeholder.remark')" />
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog v-model:visible="detailVisible" :header="t('system.department.detailTitle')" width="620px" :footer="false">
      <t-loading :loading="detailLoading">
        <t-descriptions v-if="selectedDepartment" bordered :column="2" size="small">
          <t-descriptions-item :label="t('system.department.field.name')">{{ selectedDepartment.name }}</t-descriptions-item>
          <t-descriptions-item :label="t('system.department.field.code')">{{ selectedDepartment.code }}</t-descriptions-item>
          <t-descriptions-item :label="t('system.department.field.parent')">{{ selectedDepartment.parent_name || '-' }}</t-descriptions-item>
          <t-descriptions-item :label="t('system.department.field.leader')">{{ selectedDepartment.leader_name || '-' }}</t-descriptions-item>
          <t-descriptions-item :label="t('system.department.field.sort')">{{ selectedDepartment.sort_order }}</t-descriptions-item>
          <t-descriptions-item :label="t('common.field.status')">{{ statusLabel(selectedDepartment.status) }}</t-descriptions-item>
          <t-descriptions-item :label="t('common.field.createdAt')">{{ formatDateTime(selectedDepartment.created_at) }}</t-descriptions-item>
          <t-descriptions-item :label="t('common.field.updatedAt')">{{ formatDateTime(selectedDepartment.updated_at) }}</t-descriptions-item>
          <t-descriptions-item :label="t('system.department.field.remark')" :span="2">{{ selectedDepartment.description || '-' }}</t-descriptions-item>
        </t-descriptions>
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
</style>
