<!--
  Login Page

  负责：
  1. 管理员登录
  2. 保存登录状态
  3. 登录成功后进入工作台
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { LockOnIcon, UserIcon } from 'tdesign-icons-vue-next';
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import botreeLogo from '@/assets/botree-logo.png';
import LoginHeroPanel from '@/components/LoginHeroPanel.vue';
import { useAuthStore } from '@/stores/auth';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const loading = ref(false);
const form = reactive({
  username: '',
  password: '',
});

async function submit(): Promise<void> {
  /**
   * 调用后端登录接口。
   */
  loading.value = true;
  try {
    await authStore.login(form.username, form.password);
    MessagePlugin.success('登录成功');
    await router.push((route.query.redirect as string) || authStore.firstAccessiblePath || '/');
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <LoginHeroPanel class="hero-panel" />

    <section class="form-panel">
      <div class="login-card">
        <div class="login-brand">
          <img class="brand-logo" :src="botreeLogo" alt="Botree Knowledge OS" />
          <div class="brand-copy">
            <h1>Botree Knowledge OS</h1>
            <p>博萃循环知识管理与智能体应用平台</p>
          </div>
        </div>

        <t-form class="login-form" :data="form" label-align="top" @submit.prevent="submit">
          <t-form-item label="用户名">
            <t-input v-model="form.username" placeholder="请输入用户名" size="large">
              <template #prefixIcon><UserIcon /></template>
            </t-input>
          </t-form-item>
          <t-form-item label="密码">
            <t-input v-model="form.password" type="password" placeholder="请输入密码" size="large">
              <template #prefixIcon><LockOnIcon /></template>
            </t-input>
          </t-form-item>
          <t-button class="login-button" block theme="primary" size="large" :loading="loading" @click="submit">登录系统</t-button>
        </t-form>

        <div class="copyright">© 2026 Botree. Internal use only.</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  display: flex;
  width: 100%;
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  background: #f7fbff;
}

.hero-panel {
  flex: 0 0 auto;
  width: min(60.1vw, 106.92vh);
}

.form-panel {
  display: grid;
  flex: 1 1 auto;
  min-width: 0;
  place-items: center;
  background:
    radial-gradient(circle at 18% 82%, rgba(219, 236, 255, 0.85), transparent 42%),
    linear-gradient(180deg, #fbfdff 0%, #f8fbff 100%);
  padding: 48px;
}

.login-card {
  width: min(588px, 100%);
  border: 1px solid rgba(228, 235, 246, 0.92);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.96);
  padding: 52px 54px 46px;
  box-shadow: 0 22px 60px rgba(15, 58, 120, 0.1);
}

.login-brand {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 14px;
}

.brand-logo {
  width: 52px;
  height: 52px;
  flex: 0 0 auto;
  object-fit: contain;
}

.brand-copy {
  min-width: 0;
}

.brand-copy h1 {
  margin: 0;
  color: #0b1d49;
  font-size: 22px;
  font-weight: 800;
  line-height: 1.2;
  white-space: nowrap;
}

.brand-copy p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 14px;
  line-height: 1.4;
  white-space: nowrap;
}

.login-form {
  margin-top: 57px;
}

.login-form :deep(.t-form__item) {
  margin-bottom: 33px;
}

.login-form :deep(.t-form__label) {
  margin-bottom: 12px;
  color: #0f172a;
  font-size: 21px;
  font-weight: 600;
}

.login-form :deep(.t-input) {
  height: 57px;
  border-color: #dbe2ec;
  border-radius: 6px;
  box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
}

.login-form :deep(.t-input__inner) {
  height: 100%;
  font-size: 21px;
}

.login-form :deep(.t-input__prefix > .t-icon),
.login-form :deep(.t-input__suffix > .t-icon) {
  color: #8a98ad;
  font-size: 27px;
}

.login-button {
  height: 63px;
  margin-top: 12px;
  border-radius: 8px;
  background: linear-gradient(180deg, #0b6cff 0%, #0054e6 100%);
  font-size: 22px;
  font-weight: 500;
  box-shadow: 0 8px 18px rgba(0, 84, 230, 0.18);
}

.copyright {
  margin-top: 36px;
  color: #8b98aa;
  font-size: 12px;
  text-align: center;
}

@media (max-width: 980px) {
  .login-page {
    overflow: auto;
  }

  .hero-panel {
    display: none;
  }

  .form-panel {
    min-height: 100vh;
    padding: 28px;
  }
}

@media (max-width: 520px) {
  .login-card {
    padding: 32px 24px;
  }

  .login-brand {
    align-items: flex-start;
  }

  .brand-copy h1,
  .brand-copy p {
    white-space: normal;
  }
}

</style>
