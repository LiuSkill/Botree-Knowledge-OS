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

import botreeLogo from '@/assets/botree-logo.png';
import UserAvatar from '@/components/UserAvatar.vue';
import { useAuthStore } from '@/stores/auth';
import type { SecurityLevel } from '@/types/api';
import { securityLevelLabel } from '@/utils/securityLevels';

const authStore = useAuthStore();
const router = useRouter();
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

const displayName = computed(() => authStore.user?.real_name || authStore.user?.username || '用户');
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
    MessagePlugin.warning('请先选择头像图片');
    return;
  }
  avatarUploading.value = true;
  try {
    await authStore.uploadAvatar(selectedAvatarFile.value);
    selectedAvatarFile.value = null;
    if (avatarInputRef.value) avatarInputRef.value.value = '';
    MessagePlugin.success('头像已更新');
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
    MessagePlugin.success('头像已移除');
  } finally {
    avatarUploading.value = false;
  }
}

function resetPasswordForm(): void {
  Object.assign(passwordForm, { currentPassword: '', newPassword: '', confirmPassword: '' });
}

async function submitPasswordChange(): Promise<void> {
  if (!passwordForm.currentPassword || !passwordForm.newPassword) {
    MessagePlugin.warning('请填写当前密码和新密码');
    return;
  }
  if (passwordForm.newPassword.length < 8) {
    MessagePlugin.warning('新密码至少 8 位');
    return;
  }
  if (passwordForm.newPassword !== passwordForm.confirmPassword) {
    MessagePlugin.warning('两次输入的新密码不一致');
    return;
  }
  passwordSubmitting.value = true;
  try {
    await authStore.changePassword(passwordForm.currentPassword, passwordForm.newPassword);
    resetPasswordForm();
    MessagePlugin.success('密码已修改');
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
        <div class="brand-subtitle">博萃循环知识管理与智能体应用平台</div>
      </div>
    </div>
    <div class="header-actions">
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
      <t-button variant="text" theme="danger" @click="logout">退出</t-button>
    </div>

    <t-drawer
      v-model:visible="profileVisible"
      attach="body"
      class="drawer-scroll"
      header="个人中心"
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
              <dt>姓名</dt>
              <dd>{{ authStore.user?.real_name || '-' }}</dd>
            </div>
            <div>
              <dt>邮箱</dt>
              <dd>{{ authStore.user?.email || '-' }}</dd>
            </div>
            <div>
              <dt>手机</dt>
              <dd>{{ authStore.user?.phone || '-' }}</dd>
            </div>
            <div>
              <dt>部门</dt>
              <dd>{{ authStore.user?.department || '-' }}</dd>
            </div>
            <div>
              <dt>角色</dt>
              <dd>{{ roleNames }}</dd>
            </div>
            <div>
              <dt>最高密级</dt>
              <dd>
                <span class="security-level-text" :class="maxSecurityLevelClass">
                  {{ securityLevelLabel(maxSecurityLevel) }}
                </span>
              </dd>
            </div>
          </dl>
        </section>

        <section class="profile-section">
          <h4>头像</h4>
          <t-form label-align="top">
            <t-form-item label="图片文件">
              <div class="avatar-upload-actions">
                <input
                  ref="avatarInputRef"
                  class="hidden-file-input"
                  type="file"
                  accept="image/png,image/jpeg,image/jpg,image/webp"
                  @change="handleAvatarChange"
                />
                <t-button variant="outline" @click="chooseAvatar">选择图片</t-button>
                <t-button theme="primary" :loading="avatarUploading" :disabled="!selectedAvatarFile" @click="uploadAvatar">
                  上传头像
                </t-button>
                <t-button variant="text" theme="danger" :disabled="!authStore.user?.avatar_url" @click="deleteAvatar">
                  移除
                </t-button>
              </div>
              <div v-if="selectedAvatarName" class="selected-avatar-file">{{ selectedAvatarName }}</div>
            </t-form-item>
          </t-form>
        </section>

        <section class="profile-section">
          <h4>修改密码</h4>
          <t-form :data="passwordForm" label-align="top">
            <t-form-item label="当前密码">
              <t-input v-model="passwordForm.currentPassword" type="password" placeholder="请输入当前密码" />
            </t-form-item>
            <t-form-item label="新密码">
              <t-input v-model="passwordForm.newPassword" type="password" placeholder="至少 8 位" />
            </t-form-item>
            <t-form-item label="确认新密码">
              <t-input v-model="passwordForm.confirmPassword" type="password" placeholder="请再次输入新密码" />
            </t-form-item>
            <div class="password-actions">
              <t-button variant="outline" @click="resetPasswordForm">重置</t-button>
              <t-button theme="primary" :loading="passwordSubmitting" @click="submitPasswordChange">保存密码</t-button>
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
