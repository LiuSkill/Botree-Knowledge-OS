/**
 * Global Action Mask
 *
 * 负责：
 * 1. 统一管理写操作期间的全局遮罩
 * 2. 通过 token 方式支持并发请求，避免遮罩提前消失
 * 3. 允许流式等特殊场景按需跳过全局遮罩
 */

import { computed, readonly, reactive } from 'vue';

const DEFAULT_TEXT = '正在处理中，请稍候...';

const state = reactive({
  visible: false,
  text: DEFAULT_TEXT,
  pendingCount: 0,
});

const activeMasks = new Map<symbol, string>();

function syncState(): void {
  state.pendingCount = activeMasks.size;
  state.visible = activeMasks.size > 0;
  const latestText = [...activeMasks.values()].at(-1);
  state.text = latestText || DEFAULT_TEXT;
}

export function beginActionMask(text = DEFAULT_TEXT): symbol {
  const token = Symbol('action-mask');
  activeMasks.set(token, text);
  syncState();
  return token;
}

export function endActionMask(token?: symbol): void {
  if (!token) return;
  activeMasks.delete(token);
  syncState();
}

export function clearActionMask(): void {
  activeMasks.clear();
  syncState();
}

export function useActionMask() {
  return {
    state: readonly(state),
    visible: computed(() => state.visible),
    text: computed(() => state.text),
    pendingCount: computed(() => state.pendingCount),
  };
}
