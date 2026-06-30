<!--
  Permission Matrix Page

  负责：
  1. 在权限矩阵内统一维护角色创建、编辑、删除
  2. 从后端真实菜单路由和按钮权限注册表加载权限点
  3. 强制按钮权限挂靠页面权限，取消页面权限时同步取消按钮权限
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { AddIcon, DeleteIcon, EditIcon, RefreshIcon, SaveIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import { createRole, deleteRole, listRoles, updateRole } from '@/api/roles';
import { getActionPermissions, getSystemMenus } from '@/api/system';
import PermissionMenuTree from '@/components/PermissionMenuTree.vue';
import { ACTION_PERMISSION_GROUPS, CURRENT_PERMISSION_CODE_SET, MENU_PERMISSION_TREE, PERMISSIONS } from '@/constants/permissions';
import { syncAuthorizedRoutes } from '@/router/dynamicRoutes';
import { useAuthStore } from '@/stores/auth';
import type { ActionGroupDefinition } from '@/constants/permissions';
import type { ActionPermissionGroup, ActionPermissionInfo, DataScope, RoleInfo, SecurityLevel, SystemMenuNode } from '@/types/api';
import { SECURITY_LEVEL_OPTIONS, securityLevelLabel, securityLevelTheme } from '@/utils/securityLevels';

type RoleDialogMode = 'create' | 'edit';

const DEFAULT_ROLE_PAGE_SIZE = 200;
const DATA_SCOPE_OPTIONS: Array<{ value: DataScope; label: string }> = [
  { value: 'all', label: '全部项目' },
  { value: 'department', label: '本部门项目' },
  { value: 'own', label: '自己创建或负责' },
  { value: 'public_only', label: '仅公开项目' },
];

const authStore = useAuthStore();
const router = useRouter();
const roles = ref<RoleInfo[]>([]);
const menus = ref<SystemMenuNode[]>([]);
const actionGroups = ref<ActionPermissionGroup[]>([]);
const selectedRoleId = ref<number | null>(null);
const selectedPermissionIds = ref<number[]>([]);
const loading = ref(false);
const saving = ref(false);
const roleDialogVisible = ref(false);
const roleDialogMode = ref<RoleDialogMode>('create');
const editingRoleId = ref<number | null>(null);
const roleForm = reactive({
  name: '',
  code: '',
  description: '',
  enabled: true,
  security_level: 'internal' as SecurityLevel,
  data_scope: 'own' as DataScope,
});

function dataScopeLabel(scope: DataScope): string {
  return DATA_SCOPE_OPTIONS.find((item) => item.value === scope)?.label || scope;
}

const selectedRole = computed(() => roles.value.find((role) => role.id === selectedRoleId.value) || null);
const selectedIdSet = computed(() => new Set(selectedPermissionIds.value));
const currentPermissionIdSet = computed(() => {
  const ids = new Set<number>();
  walkMenus((node) => {
    if (typeof node.permission_id === 'number') {
      ids.add(node.permission_id);
    }
  });
  actionGroups.value.forEach((group) => {
    actionPermissionIds(group).forEach((permissionId) => ids.add(permissionId));
  });
  return ids;
});
const selectedMenuIds = computed(() => {
  const menuIdMap = menuPermissionIdByCode.value;
  return new Set(
    Array.from(menuIdMap.entries())
      .filter(([, permissionId]) => selectedIdSet.value.has(permissionId))
      .map(([menuId]) => menuId),
  );
});
const selectedIdsForTree = computed(() => selectedPermissionIds.value);
const roleDialogTitle = computed(() => (roleDialogMode.value === 'create' ? '新建角色' : '编辑角色'));

const menuPermissionIdByCode = computed(() => {
  const result = new Map<string, number>();
  walkMenus((node) => {
    if (typeof node.permission_id === 'number') {
      result.set(node.id, node.permission_id);
    }
  });
  return result;
});

const menuNameByCode = computed(() => {
  const result = new Map<string, string>();
  walkMenus((node) => result.set(node.id, node.name));
  return result;
});

function walkMenus(visitor: (node: SystemMenuNode) => void, nodes = menus.value): void {
  nodes.forEach((node) => {
    visitor(node);
    walkMenus(visitor, node.children);
  });
}

function collectMenuPermissionIds(node: SystemMenuNode): number[] {
  const ids = typeof node.permission_id === 'number' ? [node.permission_id] : [];
  return ids.concat(node.children.flatMap((child) => collectMenuPermissionIds(child)));
}

function collectMenuCodes(node: SystemMenuNode): string[] {
  const ids = typeof node.permission_id === 'number' ? [node.id] : [];
  return ids.concat(node.children.flatMap((child) => collectMenuCodes(child)));
}

function actionPermissionIds(group: ActionPermissionGroup): number[] {
  return group.actions
    .map((action) => action.permission_id)
    .filter((permissionId): permissionId is number => typeof permissionId === 'number');
}

function collectMenuPermissionIdsByCode(nodes: SystemMenuNode[], result = new Map<string, number>()): Map<string, number> {
  nodes.forEach((node) => {
    if (typeof node.permission_id === 'number') {
      result.set(node.id, node.permission_id);
    }
    collectMenuPermissionIdsByCode(node.children, result);
  });
  return result;
}

function collectActionPermissionIdsByCode(groups: ActionPermissionGroup[]): Map<string, number> {
  const result = new Map<string, number>();
  groups.forEach((group) => {
    group.actions.forEach((action) => {
      if (typeof action.permission_id === 'number') {
        result.set(action.code, action.permission_id);
      }
    });
  });
  return result;
}

function hydrateMenuTree(definitions: SystemMenuNode[], permissionIds: Map<string, number>): SystemMenuNode[] {
  return definitions.map((node) => ({
    ...node,
    permission_id: permissionIds.get(node.id) ?? null,
    children: hydrateMenuTree(node.children, permissionIds),
  }));
}

function hydrateActionGroups(definitions: ActionGroupDefinition[], permissionIds: Map<string, number>): ActionPermissionGroup[] {
  return definitions.map((group) => ({
    module: group.module,
    module_name: group.module_name,
    menu_ids: [...group.menu_ids],
    actions: group.actions.map((action) => ({
      ...action,
      permission_id: permissionIds.get(action.code) ?? null,
    })),
  }));
}

function isActionGroupEnabled(group: ActionPermissionGroup): boolean {
  return group.menu_ids.some((menuId) => selectedMenuIds.value.has(menuId));
}

function isActionChecked(action: ActionPermissionInfo): boolean {
  return typeof action.permission_id === 'number' && selectedIdSet.value.has(action.permission_id);
}

function isActionGroupAllChecked(group: ActionPermissionGroup): boolean {
  const ids = actionPermissionIds(group);
  return ids.length > 0 && ids.every((id) => selectedIdSet.value.has(id));
}

function isActionGroupPartialChecked(group: ActionPermissionGroup): boolean {
  const ids = actionPermissionIds(group);
  const checkedCount = ids.filter((id) => selectedIdSet.value.has(id)).length;
  return checkedCount > 0 && checkedCount < ids.length;
}

function replaceSelection(nextSelection: Set<number>): void {
  selectedPermissionIds.value = Array.from(nextSelection)
    .filter((permissionId) => currentPermissionIdSet.value.has(permissionId))
    .sort((left, right) => left - right);
}

function pruneUnboundActions(selection: Set<number>): void {
  selection.forEach((permissionId) => {
    if (!currentPermissionIdSet.value.has(permissionId)) {
      selection.delete(permissionId);
    }
  });
  const selectedMenuCodes = new Set(
    Array.from(menuPermissionIdByCode.value.entries())
      .filter(([, permissionId]) => selection.has(permissionId))
      .map(([menuId]) => menuId),
  );
  actionGroups.value.forEach((group) => {
    const groupEnabled = group.menu_ids.some((menuId) => selectedMenuCodes.has(menuId));
    if (groupEnabled) return;
    actionPermissionIds(group).forEach((permissionId) => selection.delete(permissionId));
  });
}

function applySelectedRolePermissions(): void {
  const role = selectedRole.value;
  const nextSelection = new Set(
    (role?.permissions || [])
      .filter((permission) => CURRENT_PERMISSION_CODE_SET.has(permission.code))
      .map((permission) => permission.id),
  );
  pruneUnboundActions(nextSelection);
  replaceSelection(nextSelection);
}

function selectRole(role: RoleInfo): void {
  selectedRoleId.value = role.id;
  applySelectedRolePermissions();
}

function rolePermissionCount(role: RoleInfo): number {
  return role.permissions?.filter((permission) => CURRENT_PERMISSION_CODE_SET.has(permission.code)).length || 0;
}

function boundMenuLabel(group: ActionPermissionGroup): string {
  return group.menu_ids.map((menuId) => menuNameByCode.value.get(menuId) || menuId).join(' / ');
}

function toggleMenu(node: SystemMenuNode, checked: boolean): void {
  const nextSelection = new Set(selectedPermissionIds.value);
  collectMenuPermissionIds(node).forEach((permissionId) => {
    if (checked) {
      nextSelection.add(permissionId);
    } else {
      nextSelection.delete(permissionId);
    }
  });
  if (!checked) {
    const affectedMenuIds = new Set(collectMenuCodes(node));
    actionGroups.value.forEach((group) => {
      if (!group.menu_ids.some((menuId) => affectedMenuIds.has(menuId))) return;
      const stillHasPage = group.menu_ids.some((menuId) => {
        const permissionId = menuPermissionIdByCode.value.get(menuId);
        return typeof permissionId === 'number' && nextSelection.has(permissionId);
      });
      if (!stillHasPage) {
        actionPermissionIds(group).forEach((permissionId) => nextSelection.delete(permissionId));
      }
    });
  }
  pruneUnboundActions(nextSelection);
  replaceSelection(nextSelection);
}

function toggleAction(group: ActionPermissionGroup, action: ActionPermissionInfo, checked: boolean): void {
  if (typeof action.permission_id !== 'number') return;
  const nextSelection = new Set(selectedPermissionIds.value);
  if (checked && isActionGroupEnabled(group)) {
    nextSelection.add(action.permission_id);
  } else {
    nextSelection.delete(action.permission_id);
  }
  pruneUnboundActions(nextSelection);
  replaceSelection(nextSelection);
}

function toggleActionGroup(group: ActionPermissionGroup, checked: boolean): void {
  const nextSelection = new Set(selectedPermissionIds.value);
  actionPermissionIds(group).forEach((permissionId) => {
    if (checked && isActionGroupEnabled(group)) {
      nextSelection.add(permissionId);
    } else {
      nextSelection.delete(permissionId);
    }
  });
  pruneUnboundActions(nextSelection);
  replaceSelection(nextSelection);
}

function resetRoleForm(): void {
  Object.assign(roleForm, {
    name: '',
    code: '',
    description: '',
    enabled: true,
    security_level: 'internal' as SecurityLevel,
    data_scope: 'own' as DataScope,
  });
  editingRoleId.value = null;
}

function openCreateRoleDialog(): void {
  roleDialogMode.value = 'create';
  resetRoleForm();
  roleDialogVisible.value = true;
}

function openEditRoleDialog(role: RoleInfo): void {
  roleDialogMode.value = 'edit';
  editingRoleId.value = role.id;
  Object.assign(roleForm, {
    name: role.name,
    code: role.code,
    description: role.description || '',
    enabled: role.enabled,
    security_level: role.security_level,
    data_scope: role.data_scope,
  });
  roleDialogVisible.value = true;
}

async function submitRole(): Promise<void> {
  if (!roleForm.name.trim()) {
    MessagePlugin.warning('请输入角色名称');
    return;
  }
  if (roleDialogMode.value === 'create') {
    if (!roleForm.code.trim()) {
      MessagePlugin.warning('请输入角色编码');
      return;
    }
    const role = await createRole({
      name: roleForm.name.trim(),
      code: roleForm.code.trim(),
      description: roleForm.description.trim() || null,
      security_level: roleForm.security_level,
      data_scope: roleForm.data_scope,
      permission_ids: [],
    });
    selectedRoleId.value = role.id;
    MessagePlugin.success('角色已创建');
  } else if (editingRoleId.value) {
    await updateRole(editingRoleId.value, {
      name: roleForm.name.trim(),
      description: roleForm.description.trim() || null,
      enabled: roleForm.enabled,
      security_level: roleForm.security_level,
      data_scope: roleForm.data_scope,
    });
    MessagePlugin.success('角色已更新');
  }
  roleDialogVisible.value = false;
  await loadMatrix();
}

async function removeRole(role: RoleInfo): Promise<void> {
  await deleteRole(role.id);
  MessagePlugin.success('角色已删除');
  if (selectedRoleId.value === role.id) {
    selectedRoleId.value = null;
  }
  await loadMatrix();
}

async function savePermissions(): Promise<void> {
  if (!selectedRole.value) return;
  saving.value = true;
  try {
    const nextSelection = new Set(selectedPermissionIds.value);
    pruneUnboundActions(nextSelection);
    const role = await updateRole(selectedRole.value.id, {
      permission_ids: Array.from(nextSelection),
    });
    const index = roles.value.findIndex((item) => item.id === role.id);
    if (index >= 0) {
      roles.value.splice(index, 1, role);
    }
    selectedRoleId.value = role.id;
    await authStore.loadAccessContext();
    syncAuthorizedRoutes(router, authStore.authorizedMenuTree);
    if (!authStore.hasMenuPermission('system:permission') && authStore.firstAccessiblePath) {
      await router.replace(authStore.firstAccessiblePath);
    }
    applySelectedRolePermissions();
    MessagePlugin.success('权限配置已保存');
  } finally {
    saving.value = false;
  }
}

async function loadMatrix(): Promise<void> {
  loading.value = true;
  try {
    const [roleResult, menuResult, actionResult] = await Promise.all([
      listRoles({ page: 1, page_size: DEFAULT_ROLE_PAGE_SIZE }),
      getSystemMenus(),
      getActionPermissions(),
    ]);
    roles.value = roleResult.items;
    menus.value = hydrateMenuTree(MENU_PERMISSION_TREE, collectMenuPermissionIdsByCode(menuResult));
    actionGroups.value = hydrateActionGroups(ACTION_PERMISSION_GROUPS, collectActionPermissionIdsByCode(actionResult));
    if (!selectedRoleId.value || !roles.value.some((role) => role.id === selectedRoleId.value)) {
      selectedRoleId.value = roles.value[0]?.id || null;
    }
    applySelectedRolePermissions();
  } finally {
    loading.value = false;
  }
}

onMounted(loadMatrix);
</script>

<template>
  <div class="system-card permission-page">
    <div class="permission-layout" v-loading="loading">
      <aside class="role-panel">
        <div class="role-panel-head">
          <div>
            <h2>角色列表</h2>
            <span>{{ roles.length }} 个角色</span>
          </div>
          <t-button v-permission="PERMISSIONS.SYSTEM_PERMISSION_CREATE_ROLE" size="small" theme="primary" @click="openCreateRoleDialog">
            <template #icon><AddIcon /></template>
            新建
          </t-button>
        </div>

        <div class="role-list">
          <div
            v-for="role in roles"
            :key="role.id"
            class="role-card"
            :class="{ active: selectedRoleId === role.id }"
            role="button"
            tabindex="0"
            @click="selectRole(role)"
            @keydown.enter="selectRole(role)"
          >
            <div class="role-main">
              <strong>{{ role.name }}</strong>
              <t-tag size="small" variant="light" :theme="role.enabled ? 'success' : 'danger'">
                {{ role.enabled ? '启用' : '停用' }}
              </t-tag>
              <t-tag size="small" variant="light" :theme="securityLevelTheme(role.security_level)">
                {{ securityLevelLabel(role.security_level) }}
              </t-tag>
              <t-tag size="small" variant="light">
                {{ dataScopeLabel(role.data_scope) }}
              </t-tag>
            </div>
            <p>{{ role.description || '未填写角色说明' }}</p>
            <div class="role-meta">
              <span>{{ role.code }}</span>
              <span>{{ rolePermissionCount(role) }} 个权限</span>
            </div>
            <div class="role-actions">
              <t-button v-permission="PERMISSIONS.SYSTEM_PERMISSION_EDIT_ROLE" size="small" variant="text" @click.stop="openEditRoleDialog(role)">
                <template #icon><EditIcon /></template>
              </t-button>
              <t-popconfirm content="确认删除该角色？" @confirm="removeRole(role)">
                <t-button v-permission="PERMISSIONS.SYSTEM_PERMISSION_DELETE_ROLE" size="small" variant="text" theme="danger" @click.stop>
                  <template #icon><DeleteIcon /></template>
                </t-button>
              </t-popconfirm>
            </div>
          </div>
        </div>
      </aside>

      <main class="matrix-panel">
        <div class="matrix-head">
          <div>
            <h2>{{ selectedRole?.name || '请选择角色' }}</h2>
            <p>{{ selectedRole?.description || '配置该角色可访问的菜单和按钮操作' }}</p>
          </div>
          <t-button theme="default" variant="outline" @click="loadMatrix">
            <template #icon><RefreshIcon /></template>
            刷新
          </t-button>
        </div>

        <t-empty v-if="!selectedRole" description="暂无角色，请先新建角色" />

        <template v-else>
          <div class="permission-grid">
            <section class="permission-section menu-section">
              <div class="section-head">
                <div>
                  <h3>菜单权限</h3>
                  <span>控制路由访问和菜单显示</span>
                </div>
              </div>
              <div class="section-body">
                <PermissionMenuTree :nodes="menus" :selected-ids="selectedIdsForTree" @toggle-node="toggleMenu" />
              </div>
            </section>

            <section class="permission-section action-section">
              <div class="section-head">
                <div>
                  <h3>操作权限</h3>
                  <span>按钮权限必须绑定已授权页面，未授权页面下操作会自动取消</span>
                </div>
              </div>
              <div class="action-table-wrap">
                <table class="action-table">
                  <thead>
                    <tr>
                      <th>功能模块</th>
                      <th>绑定页面</th>
                      <th>操作权限</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="group in actionGroups" :key="group.module" :class="{ muted: !isActionGroupEnabled(group) }">
                      <td>
                        <strong>{{ group.module_name }}</strong>
                        <small>{{ group.module }}</small>
                      </td>
                      <td>{{ boundMenuLabel(group) }}</td>
                      <td>
                        <t-checkbox
                          class="check-item select-all"
                          :model-value="isActionGroupAllChecked(group)"
                          :indeterminate="isActionGroupPartialChecked(group)"
                          :disabled="!isActionGroupEnabled(group)"
                          @change="(checked) => toggleActionGroup(group, Boolean(checked))"
                        >
                          全选
                        </t-checkbox>
                        <t-checkbox
                          v-for="action in group.actions"
                          :key="action.code"
                          class="check-item"
                          :model-value="isActionChecked(action)"
                          :disabled="!isActionGroupEnabled(group)"
                          @change="(checked) => toggleAction(group, action, Boolean(checked))"
                        >
                          {{ action.name }}
                        </t-checkbox>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </section>
          </div>

          <div class="matrix-footer">
            <span>当前选择 {{ selectedPermissionIds.length }} 个权限点</span>
            <t-button v-permission="PERMISSIONS.SYSTEM_PERMISSION_SAVE" theme="primary" :loading="saving" @click="savePermissions">
              <template #icon><SaveIcon /></template>
              保存配置
            </t-button>
          </div>
        </template>
      </main>
    </div>

    <t-dialog v-model:visible="roleDialogVisible" :header="roleDialogTitle" width="520px" @confirm="submitRole">
      <t-form :data="roleForm" label-align="top">
        <t-form-item label="角色名称"><t-input v-model="roleForm.name" /></t-form-item>
        <t-form-item label="角色编码"><t-input v-model="roleForm.code" :disabled="roleDialogMode === 'edit'" /></t-form-item>
        <t-form-item label="角色说明"><t-textarea v-model="roleForm.description" /></t-form-item>
        <t-form-item label="最高密级">
          <t-select v-model="roleForm.security_level">
            <t-option v-for="item in SECURITY_LEVEL_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
          </t-select>
        </t-form-item>
        <t-form-item v-if="roleDialogMode === 'edit'" label="状态"><t-switch v-model="roleForm.enabled" /></t-form-item>
        <t-form-item label="项目数据范围">
          <t-select v-model="roleForm.data_scope">
            <t-option v-for="item in DATA_SCOPE_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
          </t-select>
        </t-form-item>
      </t-form>
    </t-dialog>
  </div>
</template>

<style scoped>
.permission-page {
  min-width: 0;
  overflow: hidden;
}

.permission-layout {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: 300px minmax(0, 1fr);
  gap: 16px;
}

.role-panel,
.matrix-panel,
.permission-section {
  min-height: 0;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.role-panel {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.role-panel-head,
.matrix-head,
.section-head,
.matrix-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.role-panel-head {
  flex: 0 0 auto;
  border-bottom: 1px solid #edf2f7;
  padding: 14px;
}

h2,
h3,
p {
  margin: 0;
}

h2 {
  color: #0f172a;
  font-size: 16px;
  font-weight: 700;
}

h3 {
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
}

.role-panel-head span,
.section-head span,
.matrix-head p,
.matrix-footer span {
  color: #64748b;
  font-size: 12px;
}

.role-list {
  display: flex;
  flex: 1 1 0;
  min-height: 0;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  padding: 12px;
}

.role-card {
  position: relative;
  width: 100%;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  padding: 12px;
  text-align: left;
  transition: border-color 0.16s ease, background 0.16s ease;
}

.role-card.active {
  border-color: #2563eb;
  background: #eff6ff;
}

.role-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding-right: 52px;
}

.role-main strong {
  min-width: 0;
  overflow: hidden;
  color: #111827;
  font-size: 14px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.role-card p {
  margin-top: 6px;
  min-height: 18px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.role-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  color: #94a3b8;
  font-size: 12px;
}

.role-actions {
  position: absolute;
  top: 8px;
  right: 8px;
  display: flex;
  gap: 2px;
}

.matrix-panel {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 12px;
  overflow: hidden;
  padding: 14px;
}

.matrix-head {
  flex: 0 0 auto;
}

.permission-grid {
  display: grid;
  flex: 1 1 0;
  min-height: 0;
  grid-template-columns: minmax(280px, 0.34fr) minmax(0, 1fr);
  gap: 12px;
}

.permission-section {
  display: flex;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
}

.menu-section {
  min-width: 0;
}

.action-section {
  min-width: 0;
}

.section-head {
  flex: 0 0 auto;
  border-bottom: 1px solid #edf2f7;
  padding: 12px 14px;
}

.section-body,
.action-table-wrap {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  padding: 14px;
}

.action-table {
  width: 100%;
  min-width: 760px;
  border-collapse: collapse;
  font-size: 13px;
}

.action-table th,
.action-table td {
  border-bottom: 1px solid #edf2f7;
  padding: 12px;
  text-align: left;
  vertical-align: top;
}

.action-table th {
  background: #f8fafc;
  color: #475569;
  font-weight: 700;
}

.action-table td:first-child {
  width: 160px;
}

.action-table td:nth-child(2) {
  width: 180px;
  color: #64748b;
}

.action-table strong,
.action-table small {
  display: block;
}

.action-table small {
  margin-top: 4px;
  color: #94a3b8;
}

.action-table tr.muted {
  background: #f8fafc;
  color: #94a3b8;
}

.check-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 86px;
  margin: 0 14px 8px 0;
  color: #1f2937;
  font-size: 13px;
}

.check-item input {
  width: 14px;
  height: 14px;
  accent-color: #2563eb;
}

.check-item input:disabled + span,
.action-table tr.muted .check-item {
  color: #94a3b8;
}

.select-all {
  color: #2563eb;
  font-weight: 700;
}

.matrix-footer {
  flex: 0 0 auto;
  border-top: 1px solid #edf2f7;
  padding-top: 12px;
}

@media (max-width: 1080px) {
  .permission-layout {
    grid-template-columns: 1fr;
  }

  .permission-grid {
    grid-template-columns: 1fr;
  }

  .role-panel {
    max-height: 280px;
  }
}
</style>
