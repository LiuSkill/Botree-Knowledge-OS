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

const columns = [
  { colKey: 'name', title: '部门名称', minWidth: 180 },
  { colKey: 'code', title: '部门编码', width: 140, ellipsis: true },
  { colKey: 'parent_name', title: '上级部门', width: 150, ellipsis: true },
  { colKey: 'leader_name', title: '部门负责人', width: 150, ellipsis: true },
  { colKey: 'sort_order', title: '排序', width: 90, align: 'center' },
  { colKey: 'status', title: '状态', width: 100, align: 'center' },
  { colKey: 'created_at', title: '创建时间', width: 170 },
  { colKey: 'operation', title: '操作', width: 230, fixed: 'right' },
];

const treeConfig = {
  childrenKey: 'children',
  treeNodeColumnIndex: 0,
  defaultExpandAll: true,
};

const dialogTitle = computed(() => (dialogMode.value === 'create' ? '新增部门' : '编辑部门'));
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
    MessagePlugin.warning('请输入部门名称');
    return false;
  }
  if (!form.code.trim()) {
    MessagePlugin.warning('请输入部门编码');
    return false;
  }
  if (!/^[A-Za-z0-9_-]{2,50}$/.test(form.code.trim())) {
    MessagePlugin.warning('部门编码支持 2-50 位字母、数字、下划线或短横线');
    return false;
  }
  if (!Number.isInteger(Number(form.sort_order)) || Number(form.sort_order) < 0 || Number(form.sort_order) > 999999) {
    MessagePlugin.warning('排序必须为 0-999999 的整数');
    return false;
  }
  if (!['enabled', 'disabled'].includes(form.status)) {
    MessagePlugin.warning('请选择部门状态');
    return false;
  }
  if (editingDepartmentId.value && form.parent_id) {
    const disabledIds = collectDepartmentAndDescendantIds(editingDepartmentId.value, departments.value);
    if (disabledIds.has(form.parent_id)) {
      MessagePlugin.warning('上级部门不能选择自己或自己的下级部门');
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
      MessagePlugin.success('部门已新增');
    } else if (editingDepartmentId.value) {
      await updateDepartment(editingDepartmentId.value, payload);
      MessagePlugin.success('部门已更新');
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
  MessagePlugin.success(nextStatus === 'enabled' ? '部门已启用' : '部门已停用');
  await loadDepartments();
}

async function handleDelete(department: DepartmentInfo): Promise<void> {
  await deleteDepartment(department.id);
  MessagePlugin.success('部门已删除');
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
  return status === 'disabled' ? '停用' : '启用';
}

function statusTheme(status: DepartmentStatus | string): TagTheme {
  return status === 'disabled' ? 'danger' : 'success';
}

function statusActionPermission(department: DepartmentInfo): string {
  return department.status === 'disabled' ? PERMISSIONS.SYSTEM_DEPARTMENT_ENABLE : PERMISSIONS.SYSTEM_DEPARTMENT_DISABLE;
}

function statusActionLabel(department: DepartmentInfo): string {
  return department.status === 'disabled' ? '启用' : '停用';
}

function confirmStatusText(department: DepartmentInfo): string {
  return department.status === 'disabled' ? '确认启用该部门？' : '确认停用该部门？停用后该部门将不能作为新增或编辑用户时的可选启用部门。';
}

function toDepartmentOptions(items: DepartmentInfo[], disabledIds: Set<number>): TreeOption[] {
  return items.map((item) => ({
    label: `${item.name}（${item.code}）`,
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

onMounted(async () => {
  await refreshAll();
});
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item label="部门名称">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="请输入部门名称或编码" @enter="handleSearch" />
      </t-form-item>
      <t-form-item label="部门状态">
        <t-select v-model="filters.status" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
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
        <h2>部门列表</h2>
        <span>共 {{ departmentTotal }} 个部门</span>
      </div>
      <t-space>
        <t-button theme="default" variant="outline" @click="refreshAll">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="PERMISSIONS.SYSTEM_DEPARTMENT_CREATE" theme="primary" @click="openCreateDialog()">
          <template #icon><AddIcon /></template>
          新增部门
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
        :loading="loading"
        empty="暂无部门"
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
            <TableActionButton label="查看" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_VIEW_DETAIL" @click="openDetailDialog(row)">
              <BrowseIcon />
            </TableActionButton>
            <TableActionButton label="编辑" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_EDIT" @click="openEditDialog(row)">
              <EditIcon />
            </TableActionButton>
            <TableActionButton label="新增下级" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_CREATE" @click="openCreateDialog(row)">
              <AddIcon />
            </TableActionButton>
            <t-popconfirm :content="confirmStatusText(row)" @confirm="handleToggleStatus(row)">
              <TableActionButton :label="statusActionLabel(row)" :permission="statusActionPermission(row)">
                <CheckCircleIcon v-if="row.status === 'disabled'" />
                <CloseCircleIcon v-else />
              </TableActionButton>
            </t-popconfirm>
            <t-popconfirm content="确认删除该部门？删除前系统会检查子部门和归属用户。" @confirm="handleDelete(row)">
              <TableActionButton label="删除" :permission="PERMISSIONS.SYSTEM_DEPARTMENT_DELETE" theme="danger">
                <DeleteIcon />
              </TableActionButton>
            </t-popconfirm>
          </t-space>
        </template>
      </t-enhanced-table>
    </div>

    <t-dialog v-model:visible="dialogVisible" :header="dialogTitle" width="620px" :confirm-loading="submitting" @confirm="handleSubmit">
      <t-form :data="form" label-align="top">
        <t-form-item label="部门名称" required-mark>
          <t-input v-model="form.name" clearable maxlength="100" placeholder="请输入部门名称" />
        </t-form-item>
        <t-form-item label="部门编码" required-mark>
          <t-input v-model="form.code" clearable maxlength="50" placeholder="请输入唯一部门编码，如 DEFAULT" />
        </t-form-item>
        <t-form-item label="上级部门">
          <t-tree-select v-model="form.parent_id" :data="parentTreeOptions" clearable filterable placeholder="无上级部门" />
        </t-form-item>
        <t-form-item label="部门负责人">
          <t-select v-model="form.leader_user_id" clearable filterable :loading="userOptionLoading" placeholder="请选择负责人">
            <t-option v-for="user in leaderOptions" :key="user.id" :value="user.id" :label="`${user.real_name}（${user.username}）`" />
          </t-select>
        </t-form-item>
        <t-form-item label="排序" required-mark>
          <t-input-number v-model="form.sort_order" :min="0" :max="999999" :step="1" />
        </t-form-item>
        <t-form-item label="状态" required-mark>
          <t-radio-group v-model="form.status">
            <t-radio-button value="enabled">启用</t-radio-button>
            <t-radio-button value="disabled">停用</t-radio-button>
          </t-radio-group>
        </t-form-item>
        <t-form-item label="备注">
          <t-textarea v-model="form.description" maxlength="500" autosize placeholder="请输入备注" />
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog v-model:visible="detailVisible" header="部门详情" width="620px" :footer="false">
      <t-loading :loading="detailLoading">
        <t-descriptions v-if="selectedDepartment" bordered :column="2" size="small">
          <t-descriptions-item label="部门名称">{{ selectedDepartment.name }}</t-descriptions-item>
          <t-descriptions-item label="部门编码">{{ selectedDepartment.code }}</t-descriptions-item>
          <t-descriptions-item label="上级部门">{{ selectedDepartment.parent_name || '-' }}</t-descriptions-item>
          <t-descriptions-item label="部门负责人">{{ selectedDepartment.leader_name || '-' }}</t-descriptions-item>
          <t-descriptions-item label="排序">{{ selectedDepartment.sort_order }}</t-descriptions-item>
          <t-descriptions-item label="状态">{{ statusLabel(selectedDepartment.status) }}</t-descriptions-item>
          <t-descriptions-item label="创建时间">{{ formatDateTime(selectedDepartment.created_at) }}</t-descriptions-item>
          <t-descriptions-item label="更新时间">{{ formatDateTime(selectedDepartment.updated_at) }}</t-descriptions-item>
          <t-descriptions-item label="备注" :span="2">{{ selectedDepartment.description || '-' }}</t-descriptions-item>
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
