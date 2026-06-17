<!--
  Knowledge Authorization Page

  负责：
  1. 展示基础知识和项目知识的授权状态
  2. 预留外部用户授权管理入口
  3. 帮助管理员确认知识访问边界
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';

import { getAuthorizationSummary } from '@/api/knowledgeBases';
import PageContainer from '@/components/PageContainer.vue';
import type { KnowledgeBaseInfo } from '@/types/api';

const summary = ref<Record<string, unknown>>({});
const bases = computed(() => (summary.value.knowledge_bases || []) as KnowledgeBaseInfo[]);
const permissions = computed(() => (summary.value.permissions || []) as Array<Record<string, unknown>>);

async function loadSummary(): Promise<void> {
  /**
   * 查询授权中心汇总数据。
   */
  summary.value = await getAuthorizationSummary();
}

onMounted(loadSummary);
</script>

<template>
  <PageContainer title="知识授权中心" subtitle="查看基础知识、项目知识和外部授权预留能力">
    <div class="auth-layout">
      <t-card title="知识库授权概览">
        <div class="auth-grid">
          <div v-for="base in bases" :key="base.id" class="auth-card">
            <div class="auth-title">
              <span>{{ base.name }}</span>
              <t-tag size="small" variant="light">{{ base.type === 'project' ? '项目知识' : '基础知识' }}</t-tag>
            </div>
            <p class="muted">{{ base.description || '暂无描述' }}</p>
            <div class="auth-meta">
              <span>资料 {{ base.document_count || 0 }}</span>
              <span>分块 {{ base.chunk_count || 0 }}</span>
              <span>{{ base.visibility }}</span>
            </div>
          </div>
        </div>
      </t-card>

      <t-card title="权限边界">
        <table class="plain-table">
          <thead>
            <tr>
              <th>权限对象</th>
              <th>权限范围</th>
              <th>状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in permissions" :key="String(item.id)">
              <td>{{ item.subject_type || 'system' }} #{{ item.subject_id || '-' }}</td>
              <td>{{ item.scope_type || '-' }} #{{ item.scope_id || '-' }}</td>
              <td>{{ item.enabled === false ? '停用' : '启用' }}</td>
            </tr>
            <tr v-if="!permissions.length">
              <td colspan="3" class="muted">MVP 阶段展示当前用户可见知识库，外部用户授权能力已预留数据结构。</td>
            </tr>
          </tbody>
        </table>
      </t-card>
    </div>
  </PageContainer>
</template>

<style scoped>
.auth-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: 16px;
}

.auth-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.auth-card {
  padding: 14px;
  border: 1px solid #edf0f5;
  border-radius: 8px;
  background: #fff;
}

.auth-title,
.auth-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.auth-title {
  color: #111827;
  font-weight: 700;
}

.auth-meta {
  color: #6b7280;
  font-size: 13px;
}
</style>
