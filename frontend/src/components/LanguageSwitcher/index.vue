<script setup lang="ts">
import { computed } from 'vue';
import { ChevronDownSIcon, EarthIcon } from 'tdesign-icons-vue-next';
import { useI18n } from 'vue-i18n';

import { useLocaleStore } from '@/stores/locale';
import type { SupportedLocale } from '@/locales';

const localeStore = useLocaleStore();
const { t } = useI18n();

const options = computed(() => [
  { content: t('common.language.enUS'), value: 'en-US', active: localeStore.locale === 'en-US' },
  { content: t('common.language.zhCN'), value: 'zh-CN', active: localeStore.locale === 'zh-CN' },
]);

const currentLabel = computed(() => (localeStore.locale === 'zh-CN' ? 'ZH' : 'EN'));

function selectLocale(data: { value: string | number }): void {
  localeStore.setLocale(data.value as SupportedLocale);
}
</script>

<template>
  <t-dropdown :options="options" trigger="click" placement="bottom-right" @click="selectLocale">
    <t-button class="language-switcher" variant="text" :aria-label="t('common.language.label')">
      <EarthIcon class="language-switcher__earth" />
      <span>{{ currentLabel }}</span>
      <ChevronDownSIcon class="language-switcher__arrow" />
    </t-button>
  </t-dropdown>
</template>

<style scoped>
.language-switcher {
  min-width: 68px;
  height: 36px;
  padding: 0 8px;
  color: #2563eb;
  font-size: 14px;
}

.language-switcher :deep(.t-button__text) {
  display: flex;
  align-items: center;
  gap: 4px;
}

.language-switcher__earth {
  font-size: 16px;
}

.language-switcher__arrow {
  color: #94a3b8;
  font-size: 14px;
}
</style>
