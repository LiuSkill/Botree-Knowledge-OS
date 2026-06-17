<!--
  Project Chat Page

  负责：
  1. 提供项目问答独立入口
  2. 强制选择项目后才能提问
  3. 限制问答范围为所选项目资料
-->
<script setup lang="ts">
import ChatWorkspace from '@/views/ai/ChatWorkspace.vue';
</script>

<template>
  <ChatWorkspace
    chat-type="project_chat"
    title="项目问答"
    subtitle="围绕具体项目进行资料追溯式问答"
    notice="当前问答仅基于所选项目资料生成回答，不跨项目查询。"
    require-project
  />
</template>
