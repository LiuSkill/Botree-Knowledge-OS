/**
 * Botree Knowledge OS Translation Hook
 *
 * 负责：
 * 1. 从 Zustand Store 读取当前语言
 * 2. 提供页面组件使用的 t() 翻译函数
 * 3. 保证语言切换后订阅组件自动刷新
 */
import { useCallback } from 'react';

import { useAppStore } from '@/stores/appStore';

import { translate, type AppLanguage } from './dictionary';

/**
 * 使用轻量翻译能力
 *
 * 返回:
 * - 当前语言
 * - t 文本翻译函数
 */
export function useTranslation(): { language: AppLanguage; t: (key: string) => string } {
  const language = useAppStore((state) => state.language);
  const t = useCallback((key: string) => translate(language, key), [language]);

  return { language, t };
}
