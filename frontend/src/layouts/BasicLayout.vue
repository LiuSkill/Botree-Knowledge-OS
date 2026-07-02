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
      <AppBreadcrumb />
      <section class="content-body">
        <router-view />
      </section>
    </main>
  </div>
</template>

<script setup lang="ts">
import AppBreadcrumb from '@/components/AppBreadcrumb.vue';
import AppHeader from '@/components/AppHeader.vue';
import AppSidebar from '@/components/AppSidebar.vue';
</script>

<style scoped>
.basic-layout {
  width: 100%;
  height: 100%;
  min-height: 0;
  overflow: hidden;
  background: #f5f7fb;
}

.main-content {
  position: fixed;
  top: 64px;
  right: 0;
  bottom: 0;
  left: 240px;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  background: #f5f7fb;
}

.content-body {
  flex: 1 1 0;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
}
</style>
