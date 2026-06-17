<!--
  StatusTag

  负责：
  1. 统一展示审核、索引和项目状态
  2. 将后端枚举映射为中文标签
  3. 降低页面重复判断
-->
<script setup lang="ts">
import { computed } from 'vue';

import { INDEX_STATUS_TEXT, REVIEW_STATUS_TEXT } from '@/utils/constants';

const props = defineProps<{
  type: 'review' | 'index' | 'project' | 'generic';
  value: string;
}>();

const text = computed(() => {
  if (props.type === 'review') return REVIEW_STATUS_TEXT[props.value] || props.value;
  if (props.type === 'index') return INDEX_STATUS_TEXT[props.value] || props.value;
  return props.value;
});

const theme = computed(() => {
  const value = props.value;
  if (['approved', 'indexed', 'active', 'success', 'enabled'].includes(value)) return 'success';
  if (['draft', 'not_indexed', 'pending', 'submitted', 'reviewing', 'parsing', 'parsed', 'parsed_pending_review', 'indexing', 'running'].includes(value)) {
    return 'warning';
  }
  if (['rejected', 'failed', 'disabled', 'canceled'].includes(value)) return 'danger';
  return 'primary';
});
</script>

<template>
  <t-tag size="small" variant="light" :theme="theme">{{ text }}</t-tag>
</template>
