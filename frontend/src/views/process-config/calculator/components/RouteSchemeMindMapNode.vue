<script setup lang="ts">
import type { CalculatorRouteTreeNode } from '@/views/process-config/calculator/types';

defineOptions({
  name: 'RouteSchemeMindMapNode',
});

defineProps<{
  node: CalculatorRouteTreeNode;
}>();
</script>

<template>
  <div class="mind-branch" :class="{ 'mind-branch--leaf': !node.children.length }">
    <div class="mind-label" :class="`mind-label--${node.kind}`" :title="`${node.label} ${node.code}`">
      <span class="mind-label-name">{{ node.label }}</span>
      <span class="mind-label-code">{{ node.code }}</span>
    </div>

    <div v-if="node.children.length" class="mind-children">
      <RouteSchemeMindMapNode v-for="child in node.children" :key="child.key" :node="child" />
    </div>
  </div>
</template>

<style scoped>
.mind-branch {
  display: flex;
  min-width: max-content;
  align-items: flex-start;
  position: relative;
}

.mind-label {
  display: flex;
  width: 136px;
  min-height: 40px;
  flex: 0 0 136px;
  flex-direction: column;
  justify-content: center;
  padding: 5px 9px;
  border: 1px solid #9db9df;
  border-radius: 4px;
  color: #27496f;
  background: #fff;
  box-sizing: border-box;
  position: relative;
}

.mind-label-name {
  overflow: hidden;
  font-size: 12px;
  font-weight: 600;
  line-height: 17px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.mind-label-code {
  margin-top: 1px;
  color: #7790ad;
  font-size: 10px;
  line-height: 14px;
}

.mind-label--material {
  border-color: #276ef1;
  color: #1652b8;
  background: #edf4ff;
  box-shadow: inset 3px 0 0 #276ef1;
}

.mind-label--product {
  border-color: #e87979;
  color: #c93636;
  background: #fff6f6;
  box-shadow: inset 3px 0 0 #e05252;
}

.mind-label--product .mind-label-code {
  color: #cb6b6b;
}

.mind-children {
  display: grid;
  gap: 8px;
  margin-left: 34px;
  padding-left: 20px;
  position: relative;
}

.mind-children::before {
  position: absolute;
  top: 20px;
  bottom: 20px;
  left: 0;
  width: 1px;
  background: #b8c8dc;
  content: '';
}

.mind-children > .mind-branch::before {
  position: absolute;
  top: 20px;
  left: -20px;
  width: 20px;
  height: 1px;
  background: #b8c8dc;
  content: '';
}

.mind-label::after {
  position: absolute;
  top: 20px;
  right: -34px;
  width: 34px;
  height: 1px;
  background: #b8c8dc;
  content: '';
}

.mind-branch--leaf > .mind-label::after {
  display: none;
}
</style>
