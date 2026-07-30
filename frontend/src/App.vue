<!--
  Botree Knowledge OS App

  负责：
  1. 承载顶层路由出口
  2. 保持应用入口简单
  3. 将布局选择交给路由配置
-->
<script setup lang="ts">
import { computed } from 'vue';
import enUS from 'tdesign-vue-next/es/locale/en_US';
import zhCN from 'tdesign-vue-next/es/locale/zh_CN';

import GlobalActionMask from '@/components/GlobalActionMask.vue';
import { useLocaleStore } from '@/stores/locale';

const localeStore = useLocaleStore();
const tdesignLocale = computed(() => (localeStore.locale === 'en-US' ? enUS : zhCN));
</script>

<template>
  <t-config-provider :global-config="tdesignLocale">
    <router-view />
    <GlobalActionMask />
  </t-config-provider>
</template>
