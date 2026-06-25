<!--
  ProcessingProgressPanel

  负责：
  1. 展示普通用户可见的问答处理进度
  2. 将内部检索链路收敛为固定业务阶段
  3. 在阶段更新时保持组件内部滚动，不撑开聊天页面
-->
<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue';

import type { ChatProgressEvent } from '@/types/api';
import { buildProgressRows, type ChatProgressRow } from '@/utils/chatProgress';

const props = withDefaults(
  defineProps<{
    events: ChatProgressEvent[];
    streaming?: boolean;
    title?: string;
  }>(),
  {
    streaming: false,
    title: '处理进度',
  },
);

const scrollRef = ref<HTMLElement | null>(null);
const rows = computed<ChatProgressRow[]>(() => buildProgressRows(props.events, props.streaming));
const updateSignature = computed(() => rows.value.map((row) => `${row.stage}:${row.status}:${row.title}`).join('|'));

function statusText(status: ChatProgressRow['status']): string {
  if (status === 'success') return '已完成';
  if (status === 'running') return '进行中';
  return '等待中';
}

watch(
  updateSignature,
  async () => {
    await nextTick();
    const container = scrollRef.value;
    if (!container) return;
    container.scrollTop = container.scrollHeight;
  },
  { immediate: true },
);
</script>

<template>
  <section class="processing-progress-card" aria-label="处理进度">
    <div class="processing-progress-header">
      <strong>{{ title }}</strong>
    </div>
    <div ref="scrollRef" class="processing-progress-scroll">
      <div
        v-for="row in rows"
        :key="row.stage"
        class="processing-progress-row"
        :class="row.status"
      >
        <span class="processing-progress-marker" aria-hidden="true">
          <span v-if="row.status === 'running'" class="processing-progress-spinner"></span>
          <span v-else class="processing-progress-dot"></span>
        </span>
        <div class="processing-progress-copy">
          <span class="processing-progress-title">{{ row.title }}</span>
          <span class="processing-progress-status">{{ statusText(row.status) }}</span>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.processing-progress-card {
  display: flex;
  width: 100%;
  height: 260px;
  flex-direction: column;
  border: 1px solid #e5e7eb;
  border-radius: 10px;
  background: #fff;
  box-sizing: border-box;
  color: #334155;
  font-size: 13px;
  line-height: 1.5;
  padding: 14px 14px 12px;
}

.processing-progress-header {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.processing-progress-header strong {
  color: #111827;
  font-size: 14px;
  font-weight: 700;
}

.processing-progress-scroll {
  flex: 1 1 auto;
  min-height: 0;
  overflow-y: auto;
  padding-right: 4px;
  scrollbar-color: #d4dae6 transparent;
  scrollbar-width: thin;
}

.processing-progress-scroll::-webkit-scrollbar {
  width: 6px;
}

.processing-progress-scroll::-webkit-scrollbar-thumb {
  border-radius: 999px;
  background: #d4dae6;
}

.processing-progress-scroll::-webkit-scrollbar-track {
  background: transparent;
}

.processing-progress-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  min-height: 34px;
  color: #64748b;
}

.processing-progress-row + .processing-progress-row {
  margin-top: 10px;
}

.processing-progress-marker {
  display: inline-flex;
  width: 16px;
  height: 20px;
  flex: 0 0 16px;
  align-items: center;
  justify-content: center;
  padding-top: 1px;
}

.processing-progress-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #cbd5e1;
}

.processing-progress-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid #bfdbfe;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: progress-spin 0.8s linear infinite;
}

.processing-progress-row.success .processing-progress-dot {
  background: #00a870;
}

.processing-progress-row.running .processing-progress-title {
  color: #1d4ed8;
}

.processing-progress-copy {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.processing-progress-title {
  min-width: 0;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.processing-progress-status {
  flex: 0 0 auto;
  color: #8a94a6;
  font-size: 12px;
}

@keyframes progress-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .processing-progress-card {
    height: 200px;
    padding: 12px;
  }

  .processing-progress-copy {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }
}
</style>
