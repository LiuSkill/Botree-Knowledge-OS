<!--
  StatusTag

  负责：
  1. 统一展示审核、索引和项目状态
  2. 将后端枚举映射为中文标签
  3. 降低页面重复判断
-->
<script setup lang="ts">
import { computed } from 'vue';
import { useI18n } from 'vue-i18n';

const props = defineProps<{
  type: 'review' | 'index' | 'project' | 'generic';
  value: string;
}>();

const { t } = useI18n();

const STATUS_KEYS: Record<string, string> = {
  draft: 'status.draft', submitted: 'status.submitted', reviewing: 'status.reviewing', pending: 'status.pending',
  approved: 'status.approved', rejected: 'status.rejected', parsing: 'status.parsing', parsed: 'status.parsed',
  unparsed: 'status.unparsed',
  parsed_pending_review: 'status.parsedPendingReview', not_indexed: 'status.notIndexed', indexing: 'status.indexing', indexed: 'status.indexed',
  active: 'status.active', archived: 'status.archived', enabled: 'status.enabled', disabled: 'status.disabled', running: 'status.running',
  success: 'status.success', failed: 'status.failed', canceled: 'status.canceled',
};

const text = computed(() => {
  if (props.type === 'index' && props.value === 'failed') return t('status.indexFailed');
  if (props.type === 'generic' && props.value === 'success') return t('status.parseSuccess');
  if (props.type === 'generic' && props.value === 'failed') return t('status.parseFailed');
  const key = STATUS_KEYS[props.value];
  return key ? t(key) : props.value;
});

const theme = computed(() => {
  const value = props.value;
  if (['approved', 'indexed', 'active', 'success', 'parsed', 'enabled'].includes(value)) return 'success';
  if (['draft', 'not_indexed', 'pending', 'submitted', 'reviewing', 'parsing', 'parsed_pending_review', 'indexing', 'running'].includes(value)) {
    return 'warning';
  }
  if (['rejected', 'failed', 'disabled', 'canceled'].includes(value)) return 'danger';
  return 'primary';
});
</script>

<template>
  <t-tag size="small" variant="light" :theme="theme">{{ text }}</t-tag>
</template>
