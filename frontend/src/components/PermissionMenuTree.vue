<!--
  Permission Menu Tree

  负责：
  1. 渲染后端菜单权限树
  2. 支持父子节点联动勾选
  3. 将具体勾选逻辑交给权限矩阵页面统一处理
-->
<script setup lang="ts">
import type { SystemMenuNode } from '@/types/api';

defineOptions({ name: 'PermissionMenuTree' });

const props = defineProps<{
  nodes: SystemMenuNode[];
  selectedIds: number[];
  disabled?: boolean;
}>();

const emit = defineEmits<{
  toggleNode: [node: SystemMenuNode, checked: boolean];
}>();

function collectPermissionIds(node: SystemMenuNode): number[] {
  const ids = typeof node.permission_id === 'number' ? [node.permission_id] : [];
  return ids.concat(node.children.flatMap((child) => collectPermissionIds(child)));
}

function isChecked(node: SystemMenuNode): boolean {
  const ids = collectPermissionIds(node);
  return ids.length > 0 && ids.every((id) => props.selectedIds.includes(id));
}

function isIndeterminate(node: SystemMenuNode): boolean {
  const ids = collectPermissionIds(node);
  const checkedCount = ids.filter((id) => props.selectedIds.includes(id)).length;
  return checkedCount > 0 && checkedCount < ids.length;
}
</script>

<template>
  <div class="permission-menu-tree">
    <div v-for="node in nodes" :key="node.id" class="tree-node">
      <t-checkbox
        :model-value="isChecked(node)"
        :indeterminate="isIndeterminate(node)"
        :disabled="props.disabled"
        @change="(checked) => emit('toggleNode', node, Boolean(checked))"
      >
        <span class="node-label">{{ node.name }}</span>
        <small v-if="node.path">{{ node.path }}</small>
      </t-checkbox>
      <PermissionMenuTree
        v-if="node.children.length"
        class="tree-children"
        :nodes="node.children"
        :selected-ids="selectedIds"
        :disabled="props.disabled"
        @toggle-node="(childNode, checked) => emit('toggleNode', childNode, checked)"
      />
    </div>
  </div>
</template>

<style scoped>
.permission-menu-tree {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tree-node {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.tree-children {
  margin-left: 22px;
  border-left: 1px solid #e5e7eb;
  padding-left: 12px;
}

.node-label {
  color: #1f2937;
  font-size: 13px;
  font-weight: 600;
}

small {
  margin-left: 8px;
  color: #94a3b8;
  font-size: 12px;
}
</style>
