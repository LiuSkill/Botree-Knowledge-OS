<!--
  TableActionButton

  负责：
  1. 统一数据表行内操作的图标按钮样式。
  2. 保留 tooltip 和 aria-label，避免纯图标操作缺少语义。
  3. 支持按钮级权限控制，与全局 v-permission 使用同一权限来源。
-->
<script setup lang="ts">
import { computed } from 'vue';

import { useAuthStore } from '@/stores/auth';

type ButtonTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';
type PermissionValue = string | string[];

const props = withDefaults(
  defineProps<{
    label: string;
    disabled?: boolean;
    loading?: boolean;
    permission?: PermissionValue;
    theme?: ButtonTheme;
  }>(),
  {
    disabled: false,
    loading: false,
    permission: undefined,
    theme: 'default',
  },
);

const emit = defineEmits<{
  click: [event: MouseEvent];
}>();

const authStore = useAuthStore();

const visible = computed(() => {
  if (!props.permission) return true;
  const permissions = Array.isArray(props.permission) ? props.permission : [props.permission];
  return permissions.some((permission) => authStore.hasActionPermission(permission));
});
</script>

<template>
  <span v-if="visible" class="table-action-button">
    <t-tooltip :content="label" placement="top">
      <t-button
        :aria-label="label"
        :disabled="disabled"
        :loading="loading"
        :theme="theme"
        :title="label"
        shape="square"
        size="small"
        variant="text"
        @click="emit('click', $event)"
      >
        <template #icon>
          <slot />
        </template>
      </t-button>
    </t-tooltip>
  </span>
</template>

<style scoped>
.table-action-button {
  display: inline-flex;
  line-height: 1;
}
</style>
