<!--
  Permission Matrix Page

  负责：
  1. 展示角色与权限点矩阵
  2. 支持按关键字、模块和角色筛选权限边界
  3. 权限编辑入口统一收敛到角色管理页
-->
<script setup lang="ts">
import { RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';

import { getPermissionMatrix } from '@/api/roles';
import type { PermissionInfo, RoleInfo } from '@/types/api';

const roles = ref<RoleInfo[]>([]);
const permissions = ref<PermissionInfo[]>([]);
const filters = reactive({
  keyword: '',
  module: '',
  role_id: null as number | null,
});
const appliedFilters = reactive({
  keyword: '',
  module: '',
  role_id: null as number | null,
});

const moduleOptions = computed(() => Array.from(new Set(permissions.value.map((item) => item.module))));
const filteredRoles = computed(() =>
  appliedFilters.role_id ? roles.value.filter((role) => role.id === appliedFilters.role_id) : roles.value,
);
const filteredPermissions = computed(() => {
  const keyword = appliedFilters.keyword.trim().toLowerCase();
  return permissions.value.filter((permission) => {
    const matchesModule = !appliedFilters.module || permission.module === appliedFilters.module;
    const matchesKeyword =
      !keyword ||
      permission.module.toLowerCase().includes(keyword) ||
      permission.code.toLowerCase().includes(keyword) ||
      permission.action.toLowerCase().includes(keyword) ||
      (permission.description || '').toLowerCase().includes(keyword);
    return matchesModule && matchesKeyword;
  });
});
const visibleModules = computed(() => Array.from(new Set(filteredPermissions.value.map((item) => item.module))));

function roleHasPermission(role: RoleInfo, permission: PermissionInfo): boolean {
  return Boolean(role.permissions?.some((item) => item.id === permission.id));
}

function permissionsByModule(module: string): PermissionInfo[] {
  return filteredPermissions.value.filter((item) => item.module === module);
}

function handleSearch(): void {
  Object.assign(appliedFilters, {
    keyword: filters.keyword,
    module: filters.module,
    role_id: filters.role_id,
  });
}

function clearFilters(): void {
  const emptyFilters = { keyword: '', module: '', role_id: null };
  Object.assign(filters, emptyFilters);
  Object.assign(appliedFilters, emptyFilters);
}

async function loadMatrix(): Promise<void> {
  const result = await getPermissionMatrix();
  roles.value = result.roles;
  permissions.value = result.permissions;
}

onMounted(loadMatrix);
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item label="关键字">
        <t-input v-model="filters.keyword" class="filter-input" clearable placeholder="模块 / 权限编码 / 描述" @enter="handleSearch" />
      </t-form-item>
      <t-form-item label="模块">
        <t-select v-model="filters.module" class="filter-select" clearable placeholder="全部模块">
          <t-option v-for="module in moduleOptions" :key="module" :value="module" :label="module" />
        </t-select>
      </t-form-item>
      <t-form-item label="角色">
        <t-select v-model="filters.role_id" class="filter-select" clearable filterable placeholder="全部角色">
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
        <h2>权限矩阵</h2>
        <span>共 {{ filteredPermissions.length }} 个权限点</span>
      </div>
      <t-button theme="default" variant="outline" @click="loadMatrix">
        <template #icon><RefreshIcon /></template>
        刷新
      </t-button>
    </div>

    <div class="matrix-content data-scroll">
      <t-empty v-if="!visibleModules.length" description="暂无匹配权限" />
      <div v-for="module in visibleModules" v-else :key="module" class="matrix-block">
        <h3>{{ module }}</h3>
        <div class="table-scroll">
          <table class="plain-table">
            <thead>
              <tr>
                <th>权限点</th>
                <th v-for="role in filteredRoles" :key="role.id">{{ role.name }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="permission in permissionsByModule(module)" :key="permission.id">
                <td>
                  <strong>{{ permission.code }}</strong>
                  <span>{{ permission.description || permission.action }}</span>
                </td>
                <td v-for="role in filteredRoles" :key="role.id">
                  <t-tag size="small" :theme="roleHasPermission(role, permission) ? 'success' : 'default'" variant="light">
                    {{ roleHasPermission(role, permission) ? '允许' : '未授权' }}
                  </t-tag>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
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
  width: 220px;
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

.matrix-content {
  flex: 1 1 0;
  min-height: 240px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow: auto;
  scrollbar-gutter: stable;
  padding: 12px;
}

.matrix-block + .matrix-block {
  margin-top: 20px;
}

.matrix-block h3 {
  margin: 0 0 10px;
  color: #1f2937;
  font-size: 16px;
}

.plain-table td:first-child {
  min-width: 220px;
}

.plain-table td:first-child strong {
  display: block;
  color: #1f2937;
  font-weight: 600;
}

.plain-table td:first-child span {
  display: block;
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
}
</style>
