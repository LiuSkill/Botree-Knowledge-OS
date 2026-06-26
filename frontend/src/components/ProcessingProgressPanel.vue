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
const updateSignature = computed(() =>
  rows.value.map((row) => `${row.stage}:${row.status}:${row.title}:${row.detail}`).join('|'),
);

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
      <TransitionGroup name="progress-step" tag="div" class="processing-progress-list">
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
            <div class="processing-progress-main">
              <span class="processing-progress-title">{{ row.title }}</span>
            </div>
            <p class="processing-progress-detail">{{ row.detail }}</p>
          </div>
        </div>
      </TransitionGroup>
    </div>
  </section>
</template>

<style scoped>
.processing-progress-card {
  display: flex;
  width: 100%;
  height: auto;
  flex-direction: column;
  box-sizing: border-box;
  color: #64748b;
  font-size: 12px;
  line-height: 1.45;
  padding: 2px 0;
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
  font-size: 13px;
  font-weight: 700;
}

.processing-progress-scroll {
  flex: 0 0 auto;
  min-height: 0;
  overflow: visible;
}

.processing-progress-list {
  min-height: 0;
}

.processing-progress-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  min-height: 0;
  color: #7b8798;
}

.processing-progress-row + .processing-progress-row {
  margin-top: 10px;
}

.processing-progress-marker {
  display: inline-flex;
  width: 14px;
  height: 18px;
  flex: 0 0 14px;
  align-items: center;
  justify-content: center;
  padding-top: 3px;
}

.processing-progress-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #cbd5e1;
}

.processing-progress-spinner {
  width: 10px;
  height: 10px;
  border: 2px solid #bfdbfe;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: progress-spin 0.8s linear infinite;
}

.processing-progress-row.success .processing-progress-dot {
  background: #00a870;
}

.processing-progress-row.running .processing-progress-title {
  color: #2563eb;
}

.processing-progress-row.pending .processing-progress-title {
  color: #94a3b8;
}

.processing-progress-copy {
  display: block;
  min-width: 0;
  flex: 1;
}

.processing-progress-main {
  display: flex;
  min-width: 0;
  align-items: center;
}

.processing-progress-title {
  min-width: 0;
  color: #475569;
  font-size: 12px;
  font-weight: 500;
  overflow-wrap: anywhere;
}

.processing-progress-detail {
  margin: 2px 0 0;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.progress-step-enter-active,
.progress-step-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.progress-step-enter-from,
.progress-step-leave-to {
  opacity: 0;
  transform: translateY(4px);
}

@keyframes progress-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (max-width: 768px) {
  .processing-progress-card {
    padding: 2px 0;
  }

  .processing-progress-main {
    align-items: flex-start;
  }
}
</style>
