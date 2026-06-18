<!--
  PageContainer

  负责：
  1. 统一页面标题区
  2. 提供右侧操作插槽
  3. 保持后台页面间距一致
-->
<script setup lang="ts">
defineProps<{
  title: string;
  subtitle?: string;
}>();
</script>

<template>
  <section class="page">
    <div class="toolbar">
      <div>
        <h1 class="page-title">{{ title }}</h1>
        <p v-if="subtitle" class="page-subtitle">{{ subtitle }}</p>
      </div>
      <div>
        <slot name="actions" />
      </div>
    </div>
    <div class="page-body">
      <slot />
    </div>
  </section>
</template>
