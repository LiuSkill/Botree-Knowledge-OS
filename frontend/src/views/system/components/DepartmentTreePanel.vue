<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { ChevronDownIcon, ChevronRightIcon, RefreshIcon } from 'tdesign-icons-vue-next';

import type { DepartmentInfo, DepartmentStatus } from '@/types/api';

interface DepartmentTreeRow {
  id: number;
  name: string;
  code: string;
  status: DepartmentStatus;
  level: number;
  hasChildren: boolean;
}

const props = withDefaults(
  defineProps<{
    departments: DepartmentInfo[];
    selectedDepartmentId: number | null;
    loading: boolean;
    error?: string;
    refreshable?: boolean;
  }>(),
  {
    error: '',
    refreshable: true,
  },
);

const emit = defineEmits<{
  select: [departmentId: number | null];
  refresh: [];
}>();

const expandedIds = ref<Set<number>>(new Set());

const visibleRows = computed(() => {
  const rows: DepartmentTreeRow[] = [];
  const visit = (items: DepartmentInfo[], level: number): void => {
    items.forEach((item) => {
      const hasChildren = Boolean(item.children?.length);
      rows.push({
        id: item.id,
        name: item.name,
        code: item.code,
        status: item.status,
        level,
        hasChildren,
      });
      if (hasChildren && expandedIds.value.has(item.id)) {
        visit(item.children || [], level + 1);
      }
    });
  };
  visit(props.departments, 0);
  return rows;
});

function isSelected(departmentId: number | null): boolean {
  return props.selectedDepartmentId === departmentId;
}

function selectDepartment(departmentId: number | null): void {
  emit('select', departmentId);
}

function toggleExpand(row: DepartmentTreeRow): void {
  if (!row.hasChildren) return;
  const next = new Set(expandedIds.value);
  if (next.has(row.id)) {
    next.delete(row.id);
  } else {
    next.add(row.id);
  }
  expandedIds.value = next;
}

function statusLabel(status: DepartmentStatus): string {
  return status === 'disabled' ? '停用' : '启用';
}

function collectDepartmentIds(items: DepartmentInfo[], ids = new Set<number>()): Set<number> {
  items.forEach((item) => {
    ids.add(item.id);
    if (item.children?.length) collectDepartmentIds(item.children, ids);
  });
  return ids;
}

watch(
  () => props.departments,
  (items) => {
    expandedIds.value = collectDepartmentIds(items);
  },
  { immediate: true },
);
</script>

<template>
  <aside class="department-panel">
    <div class="department-panel__head">
      <h2>部门</h2>
      <t-button v-if="refreshable" theme="default" variant="text" shape="square" size="small" :loading="loading" @click="emit('refresh')">
        <template #icon><RefreshIcon /></template>
      </t-button>
    </div>

    <div class="department-tree" :class="{ 'is-loading': loading }">
      <button class="department-node" :class="{ 'is-active': isSelected(null) }" type="button" @click="selectDepartment(null)">
        <span class="department-node__spacer" />
        <span class="department-node__name">全部</span>
      </button>

      <t-loading :loading="loading" size="small">
        <div v-if="error" class="department-state">
          <span>{{ error }}</span>
          <t-button v-if="refreshable" size="small" variant="outline" @click="emit('refresh')">重试</t-button>
        </div>
        <div v-else-if="!departments.length" class="department-state">暂无部门</div>
        <div v-else class="department-tree__rows">
          <div
            v-for="row in visibleRows"
            :key="row.id"
            class="department-row"
            :style="{ paddingLeft: `${row.level * 16}px` }"
          >
            <button class="department-expand" type="button" :disabled="!row.hasChildren" @click.stop="toggleExpand(row)">
              <ChevronDownIcon v-if="row.hasChildren && expandedIds.has(row.id)" />
              <ChevronRightIcon v-else-if="row.hasChildren" />
            </button>
            <button
              class="department-node department-node--child"
              :class="{ 'is-active': isSelected(row.id), 'is-disabled': row.status === 'disabled' }"
              type="button"
              @click="selectDepartment(row.id)"
            >
              <span class="department-node__name" :title="`${row.name}（${row.code}）`">{{ row.name }}</span>
              <t-tag v-if="row.status === 'disabled'" size="small" variant="light" theme="danger">{{ statusLabel(row.status) }}</t-tag>
            </button>
          </div>
        </div>
      </t-loading>
    </div>
  </aside>
</template>

<style scoped>
.department-panel {
  display: flex;
  flex: 0 0 264px;
  min-height: 0;
  flex-direction: column;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.department-panel__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #edf2f7;
  padding: 12px 12px 10px 16px;
}

.department-panel__head h2 {
  margin: 0;
  color: #0f172a;
  font-size: 16px;
  font-weight: 700;
}

.department-tree {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
  padding: 10px;
}

.department-tree.is-loading {
  overflow: hidden;
}

.department-tree__rows {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.department-row {
  display: flex;
  align-items: center;
  min-width: 0;
}

.department-expand {
  display: inline-flex;
  flex: 0 0 24px;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 30px;
  border: 0;
  background: transparent;
  color: #64748b;
  cursor: pointer;
}

.department-expand:disabled {
  cursor: default;
  opacity: 0;
}

.department-node {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 8px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #334155;
  cursor: pointer;
  font: inherit;
  padding: 7px 8px;
  text-align: left;
}

.department-node:hover {
  background: #f8fafc;
}

.department-node.is-active {
  background: #e8f2ff;
  color: #0052d9;
  font-weight: 600;
}

.department-node.is-disabled {
  color: #94a3b8;
}

.department-node--child {
  flex: 1 1 0;
}

.department-node__spacer {
  flex: 0 0 24px;
}

.department-node__name {
  min-width: 0;
  flex: 1 1 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.department-state {
  display: flex;
  min-height: 88px;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: #64748b;
  font-size: 13px;
}
</style>
