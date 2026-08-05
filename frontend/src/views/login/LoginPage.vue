<!--
  Login Page

  负责：
  1. 管理员登录
  2. 保存登录状态
  3. 登录成功后进入工作台
-->
<script setup lang="ts">
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next';
import { LockOnIcon, UserIcon } from 'tdesign-icons-vue-next';
import { reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { useI18n } from 'vue-i18n';

import botreeLogo from '@/assets/botree-logo.png';
import LanguageSwitcher from '@/components/LanguageSwitcher/index.vue';
import LoginHeroPanel from '@/components/LoginHeroPanel.vue';
import { useAuthStore } from '@/stores/auth';
import { listReviewTasks } from '@/api/reviews';

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();
const { t } = useI18n();
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
    MessagePlugin.success(t('auth.loginSuccess'));
    await notifyPendingReviews();
    await router.push((route.query.redirect as string) || authStore.firstAccessiblePath || '/');
  } finally {
    loading.value = false;
  }
}

async function notifyPendingReviews(): Promise<void> {
  if (!authStore.hasActionPermission('review:view')) return;
  try {
    const result = await listReviewTasks({ status: 'reviewing', page: 1, page_size: 1 });
    if (result.total <= 0) return;
    const dialog = DialogPlugin.confirm({
      header: t('auth.pendingReviewTitle'),
      body: t('auth.pendingReviewBody', { count: result.total }),
      confirmBtn: t('auth.pendingReviewGo'),
      cancelBtn: t('auth.pendingReviewLater'),
      onConfirm: async () => {
        dialog.destroy();
        await router.push({ path: '/reviews', query: { tab: 'tasks', status: 'reviewing' } });
      },
    });
  } catch {
    // 登录流程不因提醒查询失败而中断。
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-language-switcher">
      <LanguageSwitcher />
    </div>
    <LoginHeroPanel class="hero-panel" />

    <section class="form-panel">
      <div class="login-card">
        <div class="login-brand">
          <img class="brand-logo" :src="botreeLogo" alt="Botree Knowledge OS" />
          <div class="brand-copy">
            <h1>Botree Knowledge OS</h1>
            <p>{{ t('common.productSubtitle') }}</p>
          </div>
        </div>

        <t-form class="login-form" :data="form" label-align="top" @submit.prevent="submit">
          <t-form-item :label="t('auth.username')">
            <t-input v-model="form.username" :placeholder="t('auth.usernamePlaceholder')" size="large">
              <template #prefixIcon><UserIcon /></template>
            </t-input>
          </t-form-item>
          <t-form-item :label="t('auth.password')">
            <t-input v-model="form.password" type="password" :placeholder="t('auth.passwordPlaceholder')" size="large">
              <template #prefixIcon><LockOnIcon /></template>
            </t-input>
          </t-form-item>
          <t-button class="login-button" block theme="primary" size="large" :loading="loading" @click="submit">{{ t('auth.login') }}</t-button>
        </t-form>

        <div class="copyright">© 2026 Botree. Internal use only.</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  position: relative;
  display: flex;
  width: 100%;
  height: 100vh;
  min-height: 0;
  overflow: hidden;
  background: #f7fbff;
}

.login-language-switcher {
  position: fixed;
  top: 20px;
  right: 24px;
  z-index: 10;
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
