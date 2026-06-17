<!--
  BasicLayout

  负责：
  1. 组合顶部 Header 和左侧 Sidebar
  2. 承载登录后的业务页面
  3. 提供稳定后台布局
-->
<template>
  <div class="basic-layout">
    <AppHeader />
    <AppSidebar />
    <main class="main-content">
      <router-view />
    </main>
  </div>
</template>

<script setup lang="ts">
import AppHeader from '@/components/AppHeader.vue';
import AppSidebar from '@/components/AppSidebar.vue';
</script>

<style scoped>
.main-content {
  min-height: 100vh;
  margin-left: 240px;
  padding-top: 64px;
  background: #f5f7fb;
}
</style>
