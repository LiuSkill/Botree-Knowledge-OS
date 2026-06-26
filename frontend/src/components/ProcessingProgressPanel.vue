<!--
  ProcessingProgressPanel

  负责：
  1. 展示普通用户可见的问答处理进度
  2. 将内部检索链路收敛为固定业务阶段
  3. 在阶段更新时保持组件内部滚动，不撑开聊天页面
-->
<script setup lang="ts">
import { ChatLoading } from '@tdesign-vue-next/chat';
import { CheckCircleIcon, ChevronDownSIcon, ChevronUpSIcon, ErrorCircleIcon } from 'tdesign-icons-vue-next';
import { computed, nextTick, ref, watch } from 'vue';

import type { ChatProgressEvent } from '@/types/api';
import { buildProgressRows, type ChatProgressRow } from '@/utils/chatProgress';

const props = withDefaults(
  defineProps<{
    events: ChatProgressEvent[];
    streaming?: boolean;
    title?: string;
    collapsible?: boolean;
    defaultCollapsed?: boolean;
  }>(),
  {
    streaming: false,
    title: '处理进度',
    collapsible: false,
    defaultCollapsed: false,
  },
);

const scrollRef = ref<HTMLElement | null>(null);
const collapsed = ref(props.defaultCollapsed);
const rows = computed<ChatProgressRow[]>(() => buildProgressRows(props.events, props.streaming));
const updateSignature = computed(() =>
  rows.value.map((row) => `${row.stage}:${row.status}:${row.title}:${row.detail}`).join('|'),
);
const hasError = computed(() => props.events.some((event) => event.status === 'failed'));
const isThinking = computed(() => props.streaming || rows.value.some((row) => row.status === 'running'));
const thinkingStatus = computed<'pending' | 'complete' | 'error'>(() => {
  if (hasError.value) return 'error';
  if (isThinking.value) return 'pending';
  return 'complete';
});
const thinkingTitle = computed(() => {
  if (thinkingStatus.value === 'error') return '思考过程出错';
  if (thinkingStatus.value === 'complete') return '思考完成';
  return '思考中';
});
const canToggle = computed(() => props.collapsible && thinkingStatus.value !== 'pending');

function toggleCollapsed(): void {
  if (!canToggle.value) return;
  collapsed.value = !collapsed.value;
}

watch(
  () => props.defaultCollapsed,
  (value) => {
    if (props.collapsible) collapsed.value = value;
  },
);

watch(
  updateSignature,
  async () => {
    await nextTick();
    const container = scrollRef.value;
    if (!container || collapsed.value) return;
    container.scrollTop = container.scrollHeight;
  },
  { immediate: true },
);
</script>

<template>
  <section class="processing-progress-card" :class="{ collapsible, collapsed }" aria-label="处理进度">
    <div class="processing-progress-header" :class="{ clickable: canToggle }" @click="toggleCollapsed">
      <div class="processing-progress-heading">
        <span v-if="collapsible" class="processing-progress-thinking" :class="thinkingStatus">
          <ChatLoading v-if="thinkingStatus === 'pending'" animation="moving" text="思考中..." />
          <CheckCircleIcon v-else-if="thinkingStatus === 'complete'" />
          <ErrorCircleIcon v-else />
          <span v-if="thinkingStatus !== 'pending'">{{ thinkingTitle }}</span>
        </span>
        <strong v-else>{{ title }}</strong>
        <button v-if="canToggle" class="processing-progress-toggle" type="button" :aria-expanded="!collapsed" @click.stop="toggleCollapsed">
          <ChevronDownSIcon v-if="collapsed" />
          <ChevronUpSIcon v-else />
        </button>
      </div>
    </div>
    <div v-show="!collapsed" ref="scrollRef" class="processing-progress-scroll">
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

.processing-progress-card.collapsible {
  border: 0;
  border-radius: 0;
  background: transparent;
  overflow: visible;
  padding: 0;
}

.processing-progress-header {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-start;
  gap: 6px;
  margin-bottom: 10px;
}

.processing-progress-header.clickable {
  margin-bottom: 8px;
  cursor: pointer;
  user-select: none;
}

.processing-progress-card.collapsed .processing-progress-header {
  margin-bottom: 0;
}

.processing-progress-header strong {
  color: #111827;
  font-size: 13px;
  font-weight: 700;
}

.processing-progress-heading {
  display: flex;
  min-width: 0;
  flex: 0 1 auto;
  align-items: center;
  gap: 4px;
}

.processing-progress-thinking {
  display: inline-flex;
  min-width: fit-content;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  color: #111827;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
}

.processing-progress-thinking :deep(.t-icon) {
  width: 16px;
  height: 16px;
  flex: 0 0 16px;
  font-size: 16px;
}

.processing-progress-thinking :deep(.t-chat-loading) {
  gap: 8px;
  color: #111827;
  font-size: 13px;
  font-weight: 500;
  line-height: 20px;
}

.processing-progress-thinking.complete :deep(.t-icon) {
  color: #00a870;
}

.processing-progress-thinking.error :deep(.t-icon) {
  color: #d54941;
}

.processing-progress-toggle {
  display: inline-flex;
  width: 18px;
  height: 18px;
  flex: 0 0 18px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #8b95a5;
  cursor: pointer;
  margin-left: 2px;
  padding: 0;
}

.processing-progress-toggle:hover {
  background: transparent;
  color: #1d4ed8;
}

.processing-progress-toggle :deep(.t-icon) {
  font-size: 16px;
}

.processing-progress-scroll {
  flex: 0 0 auto;
  min-height: 0;
  overflow: visible;
  padding-top: 2px;
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
