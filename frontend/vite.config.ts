/**
 * Botree Knowledge OS Vite Configuration
 *
 * 负责：
 * 1. 配置 Vue 3 编译插件
 * 2. 配置源码目录别名
 * 3. 配置后端 API 代理
 */
import { fileURLToPath, URL } from 'node:url';

import vue from '@vitejs/plugin-vue';
import { defineConfig } from 'vite';

/**
 * Vite 工程配置
 *
 * 返回:
 * - Vue 插件配置
 * - @ 指向 src 的路径别名
 */
export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8888',
        changeOrigin: true,
      },
    },
  },
});
