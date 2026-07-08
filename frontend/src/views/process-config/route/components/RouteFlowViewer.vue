<script setup lang="ts">
import { ArrowDownIcon, ArrowUpIcon, DeleteIcon, AddIcon } from 'tdesign-icons-vue-next';

import type { RouteFlowNode } from '@/views/process-config/route/types';
import type { ProcessLibraryStatus } from '@/views/process-config/types';
import { PROCESS_NODE_TYPE_OPTIONS } from '@/views/process-config/node/types';

const props = withDefaults(
  defineProps<{
    nodes: RouteFlowNode[];
    selectedKey?: string | null;
    editable?: boolean;
    disabled?: boolean;
  }>(),
  {
    selectedKey: null,
    editable: false,
    disabled: false,
  },
);

const emit = defineEmits<{
  select: [localKey: string];
  moveUp: [localKey: string];
  moveDown: [localKey: string];
  remove: [localKey: string];
}>();

function statusLabel(status: ProcessLibraryStatus): string {
  return (
    {
      enabled: '启用',
      draft: '草稿',
      disabled: '停用',
    }[status] || status
  );
}

function statusTheme(status: ProcessLibraryStatus): 'success' | 'warning' | 'default' {
  return (
    {
      enabled: 'success',
      draft: 'warning',
      disabled: 'default',
    }[status] || 'default'
  );
}

function nodeTypeLabel(value: string): string {
  return PROCESS_NODE_TYPE_OPTIONS.find((item) => item.value === value)?.label || value;
}
</script>

<template>
  <div class="route-flow-viewer">
    <t-empty v-if="!nodes.length" description="当前路线还没有配置节点">
      <template #image>
        <AddIcon />
      </template>
    </t-empty>

    <template v-else>
      <div v-for="(item, index) in nodes" :key="item.local_key" class="route-flow-viewer__item-wrap">
        <button
          type="button"
          class="route-flow-viewer__item"
          :class="{ 'route-flow-viewer__item--active': item.local_key === selectedKey }"
          @click="emit('select', item.local_key)"
        >
          <div class="route-flow-viewer__order">{{ index + 1 }}</div>
          <div class="route-flow-viewer__main">
            <div class="route-flow-viewer__title">
              <strong>{{ item.node_name }}</strong>
              <t-tag size="small" variant="light" :theme="statusTheme(item.status)">{{ statusLabel(item.status) }}</t-tag>
            </div>
            <div class="route-flow-viewer__meta">
              <span>{{ item.node_code }}</span>
              <span>{{ nodeTypeLabel(item.node_type) }}</span>
              <span>{{ item.version }}</span>
            </div>
            <p v-if="item.remark" class="route-flow-viewer__remark">{{ item.remark }}</p>
          </div>
          <div v-if="editable" class="route-flow-viewer__actions" @click.stop>
            <t-button
              shape="square"
              size="small"
              variant="text"
              :disabled="disabled || index === 0"
              @click="emit('moveUp', item.local_key)"
            >
              <template #icon><ArrowUpIcon /></template>
            </t-button>
            <t-button
              shape="square"
              size="small"
              variant="text"
              :disabled="disabled || index === nodes.length - 1"
              @click="emit('moveDown', item.local_key)"
            >
              <template #icon><ArrowDownIcon /></template>
            </t-button>
            <t-button shape="square" size="small" theme="danger" variant="text" :disabled="disabled" @click="emit('remove', item.local_key)">
              <template #icon><DeleteIcon /></template>
            </t-button>
          </div>
        </button>
        <div v-if="index < nodes.length - 1" class="route-flow-viewer__arrow">
          <span />
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.route-flow-viewer {
  display: grid;
  gap: 0;
  min-height: 180px;
}

.route-flow-viewer__item-wrap {
  display: grid;
  gap: 10px;
}

.route-flow-viewer__item {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) auto;
  align-items: center;
  gap: 14px;
  width: 100%;
  border: 1px solid #dbe4f0;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  padding: 14px 16px;
  text-align: left;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.route-flow-viewer__item:hover {
  border-color: #b7d1ff;
  box-shadow: 0 8px 18px rgb(15 23 42 / 8%);
  transform: translateY(-1px);
}

.route-flow-viewer__item--active {
  border-color: #0052d9;
  box-shadow: 0 0 0 2px rgb(0 82 217 / 10%);
}

.route-flow-viewer__order {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 50%;
  background: #edf5ff;
  color: #0052d9;
  font-size: 16px;
  font-weight: 800;
}

.route-flow-viewer__main {
  display: grid;
  min-width: 0;
  gap: 6px;
}

.route-flow-viewer__title {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.route-flow-viewer__title strong {
  min-width: 0;
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.route-flow-viewer__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  color: #64748b;
  font-size: 12px;
}

.route-flow-viewer__remark {
  margin: 0;
  color: #475569;
  font-size: 13px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.route-flow-viewer__actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.route-flow-viewer__arrow {
  display: grid;
  justify-items: center;
  padding: 0 0 10px;
}

.route-flow-viewer__arrow span {
  width: 2px;
  height: 24px;
  background: linear-gradient(180deg, #9ec1ff 0%, #dbeafe 100%);
  position: relative;
}

.route-flow-viewer__arrow span::after {
  position: absolute;
  left: 50%;
  bottom: -3px;
  width: 8px;
  height: 8px;
  border-right: 2px solid #9ec1ff;
  border-bottom: 2px solid #9ec1ff;
  content: '';
  transform: translateX(-50%) rotate(45deg);
}
</style>
