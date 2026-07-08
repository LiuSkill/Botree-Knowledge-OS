<script setup lang="ts">
import { PERMISSIONS } from '@/constants/permissions';
import BaseProcessLibraryPage from '@/views/process-config/components/BaseProcessLibraryPage.vue';
import type { ProcessLibraryPageConfig } from '@/views/process-config/types';

const config: ProcessLibraryPageConfig = {
  title: '\u539f\u6599\u5e93',
  entityName: '\u539f\u6599',
  moduleKey: 'materials',
  apiBasePath: '/process-config/materials',
  permissions: {
    view: PERMISSIONS.PROCESS_CONFIG_MATERIAL_VIEW,
    create: PERMISSIONS.PROCESS_CONFIG_MATERIAL_CREATE,
    update: PERMISSIONS.PROCESS_CONFIG_MATERIAL_UPDATE,
    delete: PERMISSIONS.PROCESS_CONFIG_MATERIAL_DELETE,
    import: PERMISSIONS.PROCESS_CONFIG_MATERIAL_IMPORT,
    export: PERMISSIONS.PROCESS_CONFIG_MATERIAL_EXPORT,
  },
};
</script>

<template>
  <BaseProcessLibraryPage :config="config" />
</template>
