<script setup lang="ts">
import type { RouteTreePreviewNode as RouteTreePreviewNodeData } from '@/views/process-config/route/types';

defineOptions({
  name: 'RouteTreePreviewNode',
});

defineProps<{
  node: RouteTreePreviewNodeData;
}>();

function nodePrefix(node: RouteTreePreviewNodeData): string {
  if (node.kind === 'product') return '（产品）';
  if (node.kind === 'waste') return `（${node.meta || '三废'}）`;
  return '';
}
</script>

<template>
  <div class="tree-branch" :class="{ 'tree-branch--leaf': !node.children.length, 'tree-branch--active': node.active }">
    <div
      class="tree-node-label"
      :class="[
        `tree-node-label--${node.kind}`,
        {
          'tree-node-label--active': node.active,
        },
      ]"
    >
      <strong>{{ nodePrefix(node) }}{{ node.label }}</strong>
      <span v-if="node.code">{{ node.code }}</span>
    </div>

    <div v-if="node.children.length" class="tree-children">
      <RouteTreePreviewNode v-for="child in node.children" :key="child.key" :node="child" />
    </div>
  </div>
</template>

<style scoped>
.tree-branch {
  display: flex;
  align-items: flex-start;
  min-width: max-content;
  position: relative;
}

.tree-node-label {
  display: inline-flex;
  min-height: 28px;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  color: #8b95a5;
  font-size: 13px;
  line-height: 22px;
  padding: 2px 8px 4px;
  position: relative;
  white-space: nowrap;
}

.tree-node-label strong {
  font-weight: 600;
}

.tree-node-label span {
  color: #a1aab8;
  font-size: 11px;
}

.tree-node-label--material {
  min-height: 32px;
  border: 1px solid #d3d9e3;
  border-radius: 6px;
  background: #fff;
  padding: 4px 12px;
}

.tree-node-label--material span {
  display: none;
}

.tree-node-label--product {
  color: #d98a8a;
}

.tree-node-label--product span {
  color: #d98a8a;
}

.tree-node-label--waste {
  color: #b184db;
}

.tree-node-label--waste span {
  color: #b184db;
}

.tree-node-label--active {
  border: 1px solid #0052d9;
  border-radius: 5px;
  background: #eaf2ff;
  color: #0052d9;
  box-shadow:
    0 0 0 2px rgb(0 82 217 / 16%),
    inset 0 -2px 0 #0052d9;
  font-weight: 700;
}

.tree-node-label--active span {
  color: #0052d9;
}

.tree-node-label--product.tree-node-label--active {
  color: #d62f2f;
  border-color: #d62f2f;
  background: #fff4f4;
  box-shadow:
    0 0 0 2px rgb(214 47 47 / 14%),
    inset 0 -2px 0 #d62f2f;
}

.tree-node-label--product.tree-node-label--active span {
  color: #d62f2f;
}

.tree-node-label--waste.tree-node-label--active {
  color: #7e22ce;
  border-color: #7e22ce;
  background: #fbf6ff;
  box-shadow:
    0 0 0 2px rgb(126 34 206 / 13%),
    inset 0 -2px 0 #7e22ce;
}

.tree-node-label--waste.tree-node-label--active span {
  color: #7e22ce;
}

.tree-children {
  display: grid;
  gap: 7px;
  margin-left: 42px;
  padding-left: 24px;
  position: relative;
}

.tree-children::before {
  position: absolute;
  top: 14px;
  bottom: 14px;
  left: 0;
  width: 1px;
  background: #d3d9e3;
  content: '';
}

.tree-children > .tree-branch::before {
  position: absolute;
  top: 14px;
  left: -24px;
  width: 24px;
  height: 1px;
  background: #d3d9e3;
  content: '';
}

.tree-node-label::after {
  position: absolute;
  top: 14px;
  right: -42px;
  width: 42px;
  height: 1px;
  background: #d3d9e3;
  content: '';
}

.tree-branch--leaf > .tree-node-label::after {
  display: none;
}

.tree-branch--active::before,
.tree-branch--active > .tree-node-label::after {
  height: 2px;
  background: #0052d9;
}
</style>
