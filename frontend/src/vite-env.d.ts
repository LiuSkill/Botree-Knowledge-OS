/**
 * Botree Knowledge OS Vite Type Declarations
 *
 * 负责：
 * 1. 注入 Vite 客户端类型
 * 2. 声明前端环境变量类型
 * 3. 保证 import.meta.env 使用具备类型约束
 */
/// <reference types="vite/client" />

interface ImportMetaEnv {
  /**
   * 应用标题
   */
  readonly VITE_APP_TITLE?: string;
}

interface ImportMeta {
  /**
   * Vite 注入的环境变量对象
   */
  readonly env: ImportMetaEnv;
}

declare module '*.vue' {
  /**
   * Vue 单文件组件模块声明。
   */
  import type { DefineComponent } from 'vue';

  const component: DefineComponent<Record<string, unknown>, Record<string, unknown>, unknown>;
  export default component;
}
