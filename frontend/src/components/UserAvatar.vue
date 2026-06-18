<!--
  UserAvatar

  负责：
  1. 通过鉴权接口加载用户真实头像
  2. 头像缺失或加载失败时显示姓名首字母
  3. 管理 Blob URL 生命周期
-->
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue';

import { downloadUserAvatar } from '@/api/users';

const props = withDefaults(
  defineProps<{
    userId?: number | null;
    avatarUrl?: string | null;
    avatarUpdatedAt?: string | null;
    name?: string | null;
    size?: string;
    shape?: 'circle' | 'round';
  }>(),
  {
    userId: null,
    avatarUrl: null,
    avatarUpdatedAt: null,
    name: 'User',
    size: '32px',
    shape: 'circle',
  },
);

const objectUrl = ref<string | null>(null);
let loadVersion = 0;

const fallbackText = computed(() => (props.name || 'User').trim().slice(0, 1).toUpperCase() || 'U');

function revokeObjectUrl(): void {
  if (!objectUrl.value) return;
  URL.revokeObjectURL(objectUrl.value);
  objectUrl.value = null;
}

async function loadAvatar(): Promise<void> {
  const version = ++loadVersion;
  revokeObjectUrl();
  if (!props.userId || !props.avatarUrl) return;

  try {
    const blob = await downloadUserAvatar(props.userId);
    if (version !== loadVersion) return;
    objectUrl.value = URL.createObjectURL(blob);
  } catch {
    if (version === loadVersion) objectUrl.value = null;
  }
}

function handleImageError(): void {
  revokeObjectUrl();
}

watch(
  () => [props.userId, props.avatarUrl, props.avatarUpdatedAt],
  () => {
    void loadAvatar();
  },
  { immediate: true },
);

onBeforeUnmount(() => {
  loadVersion += 1;
  revokeObjectUrl();
});
</script>

<template>
  <t-avatar
    class="user-avatar"
    :image="objectUrl || undefined"
    :shape="shape"
    :size="size"
    :alt="name || '用户头像'"
    @error="handleImageError"
  >
    {{ fallbackText }}
  </t-avatar>
</template>

<style scoped>
.user-avatar {
  flex: 0 0 auto;
  background: #2563eb;
  color: #fff;
  font-weight: 700;
  user-select: none;
}
</style>
