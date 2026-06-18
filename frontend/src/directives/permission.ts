/**
 * Permission Directive
 *
 * 负责：
 * 1. 根据当前登录用户按钮权限控制元素是否进入 DOM
 * 2. 统一使用 v-permission="'module:action'" 规范
 * 3. 未授权操作移除真实元素，而不是置灰或 display:none
 */

import type { Directive, DirectiveBinding, EffectScope, Ref } from 'vue';
import { effectScope, shallowRef, watch } from 'vue';

import { useAuthStore } from '@/stores/auth';

type PermissionValue = string | string[];
type PermissionElement = HTMLElement & {
  __permissionContext?: {
    placeholder: Comment;
    value: Ref<PermissionValue>;
    scope: EffectScope;
    mounted: boolean;
  };
};

function normalizePermissions(value: PermissionValue): string[] {
  return Array.isArray(value) ? value : [value];
}

function hasPermission(value: PermissionValue): boolean {
  const authStore = useAuthStore();
  return normalizePermissions(value).some((permission) => authStore.hasActionPermission(permission));
}

function applyPermission(el: PermissionElement, visible: boolean): void {
  const context = el.__permissionContext;
  if (!context || !context.mounted) return;

  if (visible) {
    if (!el.isConnected && context.placeholder.parentNode) {
      context.placeholder.parentNode.insertBefore(el, context.placeholder);
      context.placeholder.remove();
    }
    el.hidden = false;
    return;
  }

  el.hidden = true;
  if (el.parentNode) {
    el.parentNode.replaceChild(context.placeholder, el);
  }
}

export const permissionDirective: Directive<PermissionElement, PermissionValue> = {
  beforeMount(el, binding: DirectiveBinding<PermissionValue>) {
    el.hidden = !hasPermission(binding.value);
    el.__permissionContext = {
      placeholder: document.createComment(`v-permission:${normalizePermissions(binding.value).join('|')}`),
      value: shallowRef(binding.value),
      scope: effectScope(),
      mounted: false,
    };
  },
  mounted(el) {
    const context = el.__permissionContext;
    if (!context) return;
    context.mounted = true;
    context.scope.run(() => {
      const authStore = useAuthStore();
      watch(
        () => [
          normalizePermissions(context.value.value).join('|'),
          authStore.permissions.actions.join('|'),
          authStore.isAdmin,
        ],
        () => applyPermission(el, hasPermission(context.value.value)),
        { immediate: true },
      );
    });
  },
  updated(el, binding) {
    const context = el.__permissionContext;
    if (!context) return;
    context.value.value = binding.value;
    applyPermission(el, hasPermission(binding.value));
  },
  unmounted(el) {
    const context = el.__permissionContext;
    if (!context) return;
    context.scope.stop();
    context.placeholder.remove();
    delete el.__permissionContext;
  },
};
