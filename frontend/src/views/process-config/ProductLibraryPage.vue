<script setup lang="ts">
import { PERMISSIONS } from '@/constants/permissions';
import BaseProcessLibraryPage from '@/views/process-config/components/BaseProcessLibraryPage.vue';
import type { ProcessLibraryPageConfig } from '@/views/process-config/types';
import { PROCESS_LIBRARY_TYPE_OPTIONS_MAP } from '@/views/process-config/types';

const config: ProcessLibraryPageConfig = {
  title: '\u4ea7\u54c1\u5e93',
  entityName: '\u4ea7\u54c1',
  moduleKey: 'products',
  apiBasePath: '/process-config/products',
  typeOptions: PROCESS_LIBRARY_TYPE_OPTIONS_MAP.products,
  permissions: {
    view: PERMISSIONS.PROCESS_CONFIG_PRODUCT_VIEW,
    create: PERMISSIONS.PROCESS_CONFIG_PRODUCT_CREATE,
    update: PERMISSIONS.PROCESS_CONFIG_PRODUCT_UPDATE,
    delete: PERMISSIONS.PROCESS_CONFIG_PRODUCT_DELETE,
    import: PERMISSIONS.PROCESS_CONFIG_PRODUCT_IMPORT,
    export: PERMISSIONS.PROCESS_CONFIG_PRODUCT_EXPORT,
  },
};
</script>

<template>
  <BaseProcessLibraryPage :config="config" />
</template>
