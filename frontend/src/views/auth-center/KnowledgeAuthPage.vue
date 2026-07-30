<!--
  Knowledge Authorization Page

  负责：
  1. 展示基础知识和项目知识的授权状态
  2. 预留外部用户授权管理入口
  3. 帮助管理员确认知识访问边界
-->
<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useI18n } from 'vue-i18n';

import { getAuthorizationSummary } from '@/api/knowledgeBases';
import PageContainer from '@/components/PageContainer.vue';
import type { KnowledgeBaseInfo } from '@/types/api';

const summary = ref<Record<string, unknown>>({});
const bases = computed(() => (summary.value.knowledge_bases || []) as KnowledgeBaseInfo[]);
const permissions = computed(() => (summary.value.permissions || []) as Array<Record<string, unknown>>);
const { t } = useI18n();

function knowledgeBaseVisibility(base: KnowledgeBaseInfo): string {
  return (base as KnowledgeBaseInfo & { visibility?: string }).visibility || '-';
}

async function loadSummary(): Promise<void> {
  /**
   * 查询授权中心汇总数据。
   */
  summary.value = await getAuthorizationSummary();
}

onMounted(loadSummary);
</script>

<template>
  <PageContainer :title="t('knowledge.authorization.title')" :subtitle="t('knowledge.authorization.subtitle')">
    <div class="auth-layout">
      <t-card :title="t('knowledge.authorization.overview')" class="scroll-card">
        <div class="auth-grid data-scroll">
          <div v-for="base in bases" :key="base.id" class="auth-card">
            <div class="auth-title">
              <span>{{ base.name }}</span>
              <t-tag size="small" variant="light">{{ base.type === 'project' ? t('knowledge.authorization.projectKnowledge') : t('knowledge.authorization.baseKnowledge') }}</t-tag>
            </div>
            <p class="muted">{{ base.description || t('knowledge.authorization.noDescription') }}</p>
            <div class="auth-meta">
              <span>{{ t('knowledge.authorization.documents', { count: base.document_count || 0 }) }}</span>
              <span>{{ t('knowledge.authorization.chunks', { count: base.chunk_count || 0 }) }}</span>
              <span>{{ knowledgeBaseVisibility(base) }}</span>
            </div>
          </div>
        </div>
      </t-card>

      <t-card :title="t('knowledge.authorization.boundary')" class="scroll-card">
        <div class="table-scroll">
          <table class="plain-table">
          <thead>
            <tr>
              <th>{{ t('knowledge.authorization.subject') }}</th>
              <th>{{ t('knowledge.authorization.scope') }}</th>
              <th>{{ t('knowledge.authorization.status') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in permissions" :key="String(item.id)">
              <td>{{ item.subject_type || 'system' }} #{{ item.subject_id || '-' }}</td>
              <td>{{ item.scope_type || '-' }} #{{ item.scope_id || '-' }}</td>
              <td>{{ item.enabled === false ? t('knowledge.authorization.disabled') : t('knowledge.authorization.enabled') }}</td>
            </tr>
            <tr v-if="!permissions.length">
              <td colspan="3" class="muted">{{ t('knowledge.authorization.empty') }}</td>
            </tr>
          </tbody>
          </table>
        </div>
      </t-card>
    </div>
  </PageContainer>
</template>

<style scoped>
.auth-layout {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr) 420px;
  gap: 16px;
  overflow: hidden;
}

.auth-grid {
  display: grid;
  flex: 1;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  align-content: start;
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
