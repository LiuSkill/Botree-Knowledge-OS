/**
 * Botree Knowledge OS Frontend Entry
 *
 * 负责：
 * 1. 创建 Vue 3 应用
 * 2. 注册 Pinia、Vue Router 和 TDesign
 * 3. 加载全局样式
 */

import TDesignChat from '@tdesign-vue-next/chat';
import TDesign from 'tdesign-vue-next';
import 'tdesign-vue-next/es/style/index.css';
import { createApp } from 'vue';
import { createPinia } from 'pinia';

import App from '@/App.vue';
import { permissionDirective } from '@/directives/permission';
import { i18n } from '@/locales';
import router from '@/router';
import { useLocaleStore } from '@/stores/locale';
import '@/styles/global.css';

const app = createApp(App);
const pinia = createPinia();

app.use(pinia).use(i18n).use(router).use(TDesign).use(TDesignChat).directive('permission', permissionDirective);
useLocaleStore(pinia).initialize();
app.mount('#app');
