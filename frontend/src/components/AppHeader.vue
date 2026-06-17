<!--
  AppHeader

  负责：
  1. 展示顶部品牌和当前用户
  2. 提供退出登录入口
  3. 还原原型顶部导航气质
-->
<script setup lang="ts">
import { useRouter } from 'vue-router';

import { useAuthStore } from '@/stores/auth';

const authStore = useAuthStore();
const router = useRouter();

async function logout(): Promise<void> {
  /**
   * 退出登录并跳转登录页。
   */
  await authStore.logout();
  await router.push('/login');
}
</script>

<template>
  <header class="app-header">
    <div class="brand">
      <div class="brand-mark">B</div>
      <div>
        <div class="brand-title">Botree Knowledge OS</div>
        <div class="brand-subtitle">企业知识管理与智能体应用平台</div>
      </div>
    </div>
    <div class="header-actions">
      <t-tag theme="success" variant="light">AI 引擎运行中</t-tag>
      <span class="user-name">{{ authStore.user?.real_name || authStore.user?.username }}</span>
      <t-button variant="text" theme="danger" @click="logout">退出</t-button>
    </div>
  </header>
</template>

<style scoped>
.app-header {
  position: fixed;
  top: 0;
  right: 0;
  left: 0;
  z-index: 20;
  display: flex;
  height: 64px;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  border-bottom: 1px solid #e5e7eb;
  background: rgba(255, 255, 255, 0.96);
  backdrop-filter: blur(12px);
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

.brand-mark {
  display: grid;
  width: 36px;
  height: 36px;
  place-items: center;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-weight: 800;
}

.brand-title {
  color: #111827;
  font-size: 16px;
  font-weight: 700;
}

.brand-subtitle {
  color: #6b7280;
  font-size: 12px;
}

.header-actions {
  display: flex;
  align-items: center;
  gap: 16px;
}

.user-name {
  color: #374151;
  font-weight: 600;
}
</style>
