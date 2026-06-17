<!--
  AgentTracePanel

  负责：
  1. 展示 Agent 执行过程
  2. 帮助用户理解检索、规划和回答生成路径
  3. 支持流式场景下的阶段性回显
-->
<script setup lang="ts">
import type { AgentTraceStep } from '@/types/api';

defineProps<{
  steps: AgentTraceStep[];
}>();

function stepSummary(step: AgentTraceStep): string {
  if (step.result) return step.result;
  if (step.output_summary && Object.keys(step.output_summary).length) {
    return JSON.stringify(step.output_summary, null, 2);
  }
  if (step.details && Object.keys(step.details).length) {
    return JSON.stringify(step.details, null, 2);
  }
  return '已执行';
}
</script>

<template>
  <t-empty v-if="!steps.length" size="small" description="暂无执行过程" />
  <t-timeline v-else mode="same">
    <t-timeline-item v-for="step in steps" :key="`${step.step}-${step.elapsed_ms || 0}`" :label="step.step">
      <div class="trace-meta">
        <t-tag size="small" variant="light" :theme="step.status === 'failed' ? 'danger' : 'primary'">
          {{ step.status === 'failed' ? '失败' : '完成' }}
        </t-tag>
        <span v-if="step.elapsed_ms !== undefined && step.elapsed_ms !== null">{{ step.elapsed_ms }} ms</span>
      </div>
      <pre class="trace-result">{{ stepSummary(step) }}</pre>
    </t-timeline-item>
  </t-timeline>
</template>

<style scoped>
.trace-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  color: #6b7280;
  font-size: 12px;
}

.trace-result {
  margin: 0;
  overflow: auto;
  color: #4b5563;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
</style>
