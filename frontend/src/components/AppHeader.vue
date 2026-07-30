<!--
  AppHeader

  负责：
  1. 展示顶部品牌和当前用户
  2. 提供退出登录入口
  3. 还原原型顶部导航气质
-->
<script setup lang="ts">
import { computed, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { MessagePlugin } from 'tdesign-vue-next';
import { useI18n } from 'vue-i18n';

import botreeLogo from '@/assets/botree-logo.png';
import LanguageSwitcher from '@/components/LanguageSwitcher/index.vue';
import UserAvatar from '@/components/UserAvatar.vue';
import { useAuthStore } from '@/stores/auth';
import type { SecurityLevel } from '@/types/api';

const authStore = useAuthStore();
const router = useRouter();
const { t } = useI18n();
const profileVisible = ref(false);
const avatarInputRef = ref<HTMLInputElement | null>(null);
const selectedAvatarFile = ref<File | null>(null);
const avatarUploading = ref(false);
const passwordSubmitting = ref(false);
const passwordForm = reactive({
  currentPassword: '',
  newPassword: '',
  confirmPassword: '',
});

const displayName = computed(() => authStore.user?.real_name || authStore.user?.username || t('common.field.user'));
const roleNames = computed(() => authStore.user?.roles.map((role) => role.name).join('、') || '-');
const securityLevelRank: Record<SecurityLevel, number> = {
  public: 0,
  internal: 1,
  confidential: 2,
};
const maxSecurityLevel = computed<SecurityLevel>(() => {
  const enabledRoleLevels = (authStore.user?.roles || [])
    .filter((role) => role.enabled)
    .map((role) => role.security_level)
    .filter((level): level is SecurityLevel => Boolean(level));
  if (!enabledRoleLevels.length) return authStore.user?.max_security_level || 'public';
  return enabledRoleLevels.reduce((maxLevel, level) =>
    securityLevelRank[level] > securityLevelRank[maxLevel] ? level : maxLevel,
  );
});
const maxSecurityLevelClass = computed(() => `security-level-${maxSecurityLevel.value}`);
const selectedAvatarName = computed(() => selectedAvatarFile.value?.name || '');

function openProfile(): void {
  profileVisible.value = true;
}

function chooseAvatar(): void {
  avatarInputRef.value?.click();
}

function handleAvatarChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectedAvatarFile.value = input.files?.[0] || null;
}

async function uploadAvatar(): Promise<void> {
  if (!selectedAvatarFile.value) {
    MessagePlugin.warning(t('common.profile.selectAvatarFirst'));
    return;
  }
  avatarUploading.value = true;
  try {
    await authStore.uploadAvatar(selectedAvatarFile.value);
    selectedAvatarFile.value = null;
    if (avatarInputRef.value) avatarInputRef.value.value = '';
    MessagePlugin.success(t('common.profile.avatarUpdated'));
  } finally {
    avatarUploading.value = false;
  }
}

async function deleteAvatar(): Promise<void> {
  avatarUploading.value = true;
  try {
    await authStore.deleteAvatar();
    selectedAvatarFile.value = null;
    if (avatarInputRef.value) avatarInputRef.value.value = '';
    MessagePlugin.success(t('common.profile.avatarRemoved'));
  } finally {
    avatarUploading.value = false;
  }
}

function resetPasswordForm(): void {
  Object.assign(passwordForm, { currentPassword: '', newPassword: '', confirmPassword: '' });
}

async function submitPasswordChange(): Promise<void> {
  if (!passwordForm.currentPassword || !passwordForm.newPassword) {
    MessagePlugin.warning(t('common.profile.passwordsRequired'));
    return;
  }
  if (passwordForm.newPassword.length < 8) {
    MessagePlugin.warning(t('common.profile.passwordMinLength'));
    return;
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    MessagePlugin.warning(t('common.profile.passwordMismatch'));
    return;
  }
  passwordSubmitting.value = true;
  try {
    await authStore.changePassword(passwordForm.currentPassword, passwordForm.newPassword);
    resetPasswordForm();
    MessagePlugin.success(t('common.profile.passwordChanged'));
  } finally {
    passwordSubmitting.value = false;
  }
}

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
      <img class="brand-logo" :src="botreeLogo" alt="Botree Knowledge OS" />
      <div>
        <div class="brand-title">Botree Knowledge OS</div>
        <div class="brand-subtitle">{{ t('common.productSubtitle') }}</div>
      </div>
    </div>
    <div class="header-actions">
      <LanguageSwitcher />
      <t-button class="avatar-button" variant="text" shape="circle" @click="openProfile">
        <UserAvatar
          :user-id="authStore.user?.id"
          :avatar-url="authStore.user?.avatar_url"
          :avatar-updated-at="authStore.user?.avatar_updated_at"
          :name="displayName"
          size="36px"
          shape="circle"
        />
      </t-button>
      <span class="user-name">{{ displayName }}</span>
      <t-button variant="text" theme="danger" @click="logout">{{ t('common.action.logout') }}</t-button>
    </div>

    <t-drawer
      v-model:visible="profileVisible"
      attach="body"
      class="drawer-scroll"
      :header="t('common.profile.title')"
      placement="right"
      size="420px"
      :footer="false"
      :z-index="3000"
      destroy-on-close
    >
      <div class="profile-drawer">
        <section class="profile-section">
          <div class="profile-overview">
            <UserAvatar
              :user-id="authStore.user?.id"
              :avatar-url="authStore.user?.avatar_url"
              :avatar-updated-at="authStore.user?.avatar_updated_at"
              :name="displayName"
              size="64px"
              shape="circle"
            />
            <div>
              <h3>{{ displayName }}</h3>
              <p>@{{ authStore.user?.username }}</p>
            </div>
          </div>
          <dl class="profile-info">
            <div>
              <dt>{{ t('common.field.name') }}</dt>
              <dd>{{ authStore.user?.real_name || '-' }}</dd>
            </div>
            <div>
              <dt>{{ t('common.field.email') }}</dt>
              <dd>{{ authStore.user?.email || '-' }}</dd>
            </div>
            <div>
              <dt>{{ t('common.field.phone') }}</dt>
              <dd>{{ authStore.user?.phone || '-' }}</dd>
            </div>
            <div>
              <dt>{{ t('common.field.department') }}</dt>
              <dd>{{ authStore.user?.department || '-' }}</dd>
            </div>
            <div>
              <dt>{{ t('common.field.role') }}</dt>
              <dd>{{ roleNames }}</dd>
            </div>
            <div>
              <dt>{{ t('common.profile.highestSecurityLevel') }}</dt>
              <dd>
                <span class="security-level-text" :class="maxSecurityLevelClass">
                  {{ t(`status.${maxSecurityLevel}`) }}
                </span>
              </dd>
            </div>
          </dl>
        </section>

        <section class="profile-section">
          <h4>{{ t('common.profile.avatar') }}</h4>
          <t-form label-align="top">
            <t-form-item :label="t('common.profile.imageFile')">
              <div class="avatar-upload-actions">
                <input
                  ref="avatarInputRef"
                  class="hidden-file-input"
                  type="file"
                  accept="image/png,image/jpeg,image/jpg,image/webp"
                  @change="handleAvatarChange"
                />
                <t-button variant="outline" @click="chooseAvatar">{{ t('common.profile.chooseImage') }}</t-button>
                <t-button theme="primary" :loading="avatarUploading" :disabled="!selectedAvatarFile" @click="uploadAvatar">
                  {{ t('common.profile.uploadAvatar') }}
                </t-button>
                <t-button variant="text" theme="danger" :disabled="!authStore.user?.avatar_url" @click="deleteAvatar">
                  {{ t('common.profile.removeAvatar') }}
                </t-button>
              </div>
              <div v-if="selectedAvatarName" class="selected-avatar-file">{{ selectedAvatarName }}</div>
            </t-form-item>
          </t-form>
        </section>

        <section class="profile-section">
          <h4>{{ t('common.profile.changePassword') }}</h4>
          <t-form :data="passwordForm" label-align="top">
            <t-form-item :label="t('common.profile.currentPassword')">
              <t-input v-model="passwordForm.currentPassword" type="password" :placeholder="t('common.profile.currentPasswordPlaceholder')" />
            </t-form-item>
            <t-form-item :label="t('common.profile.newPassword')">
              <t-input v-model="passwordForm.newPassword" type="password" :placeholder="t('common.profile.newPasswordPlaceholder')" />
            </t-form-item>
            <t-form-item :label="t('common.profile.confirmPassword')">
              <t-input v-model="passwordForm.confirmPassword" type="password" :placeholder="t('common.profile.confirmPasswordPlaceholder')" />
            </t-form-item>
            <div class="password-actions">
              <t-button variant="outline" @click="resetPasswordForm">{{ t('common.action.reset') }}</t-button>
              <t-button theme="primary" :loading="passwordSubmitting" @click="submitPasswordChange">{{ t('common.profile.savePassword') }}</t-button>
            </div>
          </t-form>
        </section>
      </div>
    </t-drawer>
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

.brand-logo {
  width: 44px;
  height: 44px;
  object-fit: contain;
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
  gap: 12px;
}

.avatar-button {
  width: 40px;
  height: 40px;
  padding: 0;
  border-radius: 999px;
}

.avatar-button :deep(.t-button__text) {
  display: flex;
  align-items: center;
  justify-content: center;
}

.user-name {
  color: #374151;
  font-weight: 600;
}

.profile-drawer {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.profile-section {
  border-bottom: 1px solid #e5e7eb;
  padding-bottom: 18px;
}

.profile-section:last-child {
  border-bottom: 0;
  padding-bottom: 0;
}

.profile-section h4 {
  margin: 0 0 12px;
  color: #111827;
  font-size: 15px;
}

.profile-overview {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 16px;
}

.profile-overview h3 {
  margin: 0;
  color: #111827;
  font-size: 18px;
}

.profile-overview p {
  margin: 4px 0 0;
  color: #6b7280;
  font-size: 13px;
}

.profile-info {
  display: grid;
  gap: 10px;
  margin: 0;
}

.profile-info div {
  display: grid;
  grid-template-columns: 72px 1fr;
  gap: 12px;
}

.profile-info dt {
  color: #6b7280;
}

.profile-info dd {
  margin: 0;
  color: #111827;
}

.security-level-text {
  font-weight: 600;
}

.security-level-public {
  color: #00a870;
}

.security-level-internal {
  color: #b7791f;
}

.security-level-confidential {
  color: #d54941;
}

.avatar-upload-actions,
.password-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.hidden-file-input {
  display: none;
}

.selected-avatar-file {
  margin-top: 8px;
  color: #6b7280;
  font-size: 12px;
}

.password-actions {
  justify-content: flex-end;
  margin-top: 8px;
}
</style>
