<!--
  QA Audit Page

  负责：
  1. 展示问答审计记录
  2. 追踪问题、答案、引用和检索器
  3. 支撑 AI 回答合规复盘
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { listQAAudits } from '@/api/system';
import { formatDateTime } from '@/utils/format';

const audits = ref<Array<Record<string, unknown>>>([]);

async function loadAudits(): Promise<void> {
  /**
   * 查询问答审计记录。
   */
  audits.value = await listQAAudits();
}

onMounted(loadAudits);
</script>

<template>
  <t-card title="问答审计" class="system-card">
    <table class="plain-table">
      <thead>
        <tr>
          <th>时间</th>
          <th>用户</th>
          <th>问题</th>
          <th>回答摘要</th>
          <th>引用数</th>
          <th>检索器</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="audit in audits" :key="String(audit.id)">
          <td>{{ formatDateTime(String(audit.created_at || '')) }}</td>
          <td>{{ audit.username || '-' }}</td>
          <td>{{ audit.question || '-' }}</td>
          <td>{{ audit.answer || '-' }}</td>
          <td>{{ audit.citation_count || 0 }}</td>
          <td>{{ audit.retrievers || '-' }}</td>
        </tr>
      </tbody>
    </table>
  </t-card>
</template>

<style scoped>
.system-card {
  margin-top: 16px;
}
</style>
