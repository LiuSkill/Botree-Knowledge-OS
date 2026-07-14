<script setup lang="ts">
import { PERMISSIONS } from '@/constants/permissions';
import BaseProcessLibraryPage from '@/views/process-config/components/BaseProcessLibraryPage.vue';
import type { ProcessLibraryPageConfig } from '@/views/process-config/types';
import { PROCESS_LIBRARY_TYPE_OPTIONS_MAP } from '@/views/process-config/types';

const config: ProcessLibraryPageConfig = {
  title: '\u6d88\u8017\u54c1\u5e93',
  entityName: '\u6d88\u8017\u54c1',
  moduleKey: 'consumables',
  apiBasePath: '/process-config/consumables',
  typeOptions: PROCESS_LIBRARY_TYPE_OPTIONS_MAP.consumables,
  permissions: {
    view: PERMISSIONS.PROCESS_CONFIG_CONSUMABLE_VIEW,
    create: PERMISSIONS.PROCESS_CONFIG_CONSUMABLE_CREATE,
    update: PERMISSIONS.PROCESS_CONFIG_CONSUMABLE_UPDATE,
    delete: PERMISSIONS.PROCESS_CONFIG_CONSUMABLE_DELETE,
    import: PERMISSIONS.PROCESS_CONFIG_CONSUMABLE_IMPORT,
    export: PERMISSIONS.PROCESS_CONFIG_CONSUMABLE_EXPORT,
  },
};
</script>

<template>
  <BaseProcessLibraryPage :config="config" />
</template>
