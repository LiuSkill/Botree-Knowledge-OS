<script setup lang="ts">
import { PERMISSIONS } from '@/constants/permissions';
import BaseProcessLibraryPage from '@/views/process-config/components/BaseProcessLibraryPage.vue';
import type { ProcessLibraryPageConfig } from '@/views/process-config/types';
import { PROCESS_LIBRARY_TYPE_OPTIONS_MAP } from '@/views/process-config/types';

const config: ProcessLibraryPageConfig = {
  title: '\u516c\u5171\u670d\u52a1\u5e93',
  entityName: '\u516c\u5171\u670d\u52a1',
  moduleKey: 'public-services',
  apiBasePath: '/process-config/public-services',
  typeOptions: PROCESS_LIBRARY_TYPE_OPTIONS_MAP['public-services'],
  permissions: {
    view: PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE_VIEW,
    create: PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE_CREATE,
    update: PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE_UPDATE,
    delete: PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE_DELETE,
    import: PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE_IMPORT,
    export: PERMISSIONS.PROCESS_CONFIG_PUBLIC_SERVICE_EXPORT,
  },
};
</script>

<template>
  <BaseProcessLibraryPage :config="config" />
</template>
