<!--
  Operation Log Page

  负责：
  1. 展示系统关键操作日志
  2. 便于追踪上传、审核、解析、索引和管理动作
  3. 支撑企业级审计要求
-->
<script setup lang="ts">
import { onMounted, ref } from 'vue';

import { listOperationLogs } from '@/api/system';
import type { OperationLog } from '@/types/api';
import { formatDateTime } from '@/utils/format';

const logs = ref<OperationLog[]>([]);

async function loadLogs(): Promise<void> {
  /**
   * 查询操作日志。
   */
  logs.value = await listOperationLogs();
}

onMounted(loadLogs);
</script>

<template>
  <t-card title="操作日志" class="system-card">
    <table class="plain-table">
      <thead>
        <tr>
          <th>时间</th>
          <th>用户</th>
          <th>动作</th>
          <th>对象</th>
          <th>结果</th>
          <th>详情</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="log in logs" :key="log.id">
          <td>{{ formatDateTime(log.created_at) }}</td>
          <td>{{ log.username || '-' }}</td>
          <td>{{ log.action }}</td>
          <td>{{ log.target_type }} #{{ log.target_id || '-' }}</td>
          <td>{{ log.result }}</td>
          <td>{{ log.detail || '-' }}</td>
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
