<!--
  Botree Knowledge OS App

  负责：
  1. 承载顶层路由出口
  2. 保持应用入口简单
  3. 将布局选择交给路由配置
-->
<script setup lang="ts">
import GlobalActionMask from '@/components/GlobalActionMask.vue';
</script>

<template>
  <router-view />
  <GlobalActionMask />
</template>
