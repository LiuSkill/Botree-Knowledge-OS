<!--
  Base Chat Page

  负责：
  1. 提供基础问答独立入口
  2. 基于当前用户权限查询全部可访问资料
  3. 默认不向外部用户开放
-->
<script setup lang="ts">
import ChatWorkspace from '@/views/ai/ChatWorkspace.vue';
</script>

<template>
  <ChatWorkspace
    chat-type="base_chat"
    title="基础问答"
    subtitle="查询当前用户有权限访问的基础知识库资料"
    notice="当前问答仅基于你有权限访问的基础知识库中已审核、已索引资料生成回答。"
    :require-project="false"
  />
</template>
