<!--
  Login Page

  负责：
  1. 管理员登录
  2. 保存登录状态
  3. 登录成功后进入工作台
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const loading = ref(false);
const form = reactive({
  username: 'admin',
  password: 'admin123456',
});

async function submit(): Promise<void> {
  /**
   * 调用后端登录接口。
   */
  loading.value = true;
  try {
    await authStore.login(form.username, form.password);
    MessagePlugin.success('登录成功');
    await router.push((route.query.redirect as string) || '/dashboard');
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-panel">
      <div class="logo">B</div>
      <h1>Botree Knowledge OS</h1>
      <p>企业知识管理与智能体应用平台</p>
      <t-form class="login-form" :data="form" label-align="top" @submit.prevent="submit">
        <t-form-item label="用户名">
          <t-input v-model="form.username" placeholder="请输入用户名" />
        </t-form-item>
        <t-form-item label="密码">
          <t-input v-model="form.password" type="password" placeholder="请输入密码" />
        </t-form-item>
        <t-button block theme="primary" size="large" :loading="loading" @click="submit">登录系统</t-button>
      </t-form>
      <div class="hint">默认账号：admin / admin123456</div>
    </div>
  </div>
</template>

<style scoped>
.login-page {
  display: grid;
  min-height: 100vh;
  place-items: center;
  background:
    linear-gradient(135deg, rgba(37, 99, 235, 0.12), rgba(14, 165, 233, 0.06)),
    #f5f7fb;
}

.login-panel {
  width: 420px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  padding: 36px;
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.08);
}

.logo {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border-radius: 8px;
  background: #2563eb;
  color: #fff;
  font-size: 24px;
  font-weight: 800;
}

h1 {
  margin: 18px 0 6px;
  color: #111827;
  font-size: 24px;
}

p {
  margin: 0;
  color: #6b7280;
}

.login-form {
  margin-top: 28px;
}

.hint {
  margin-top: 16px;
  color: #6b7280;
  font-size: 13px;
  text-align: center;
}
</style>
