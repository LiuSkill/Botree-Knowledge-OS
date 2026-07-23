<script setup lang="ts">
import BaseProcessLibraryPage from '@/views/process-config/components/BaseProcessLibraryPage.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { PROCESS_LIBRARY_TYPE_OPTIONS_MAP } from '@/views/process-config/types';

const config = {
  title: '基础设施库',
  entityName: '基础设施',
  moduleKey: 'infrastructure-assets',
  apiBasePath: '/process-config/assets',
  fixedListParams: { asset_class: 'infrastructure' },
  fixedPayload: { asset_class: 'infrastructure' },
  enableImportExport: false,
  typeOptions: PROCESS_LIBRARY_TYPE_OPTIONS_MAP['infrastructure-assets'],
  permissions: {
    view: PERMISSIONS.PROCESS_CONFIG_ASSET_VIEW,
    create: PERMISSIONS.PROCESS_CONFIG_ASSET_CREATE,
    update: PERMISSIONS.PROCESS_CONFIG_ASSET_UPDATE,
    delete: PERMISSIONS.PROCESS_CONFIG_ASSET_DELETE,
    import: PERMISSIONS.PROCESS_CONFIG_ASSET_CREATE,
    export: PERMISSIONS.PROCESS_CONFIG_ASSET_VIEW,
  },
} as const;
</script>

<template>
  <BaseProcessLibraryPage :config="config" />
</template>
