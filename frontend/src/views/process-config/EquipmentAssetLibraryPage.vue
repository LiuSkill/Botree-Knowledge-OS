<script setup lang="ts">
import BaseProcessLibraryPage from '@/views/process-config/components/BaseProcessLibraryPage.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { PROCESS_LIBRARY_TYPE_OPTIONS_MAP } from '@/views/process-config/types';

const config = {
  title: '设备资产库',
  entityName: '设备资产',
  moduleKey: 'equipment-assets',
  apiBasePath: '/process-config/assets',
  fixedListParams: { asset_class: 'equipment' },
  fixedPayload: { asset_class: 'equipment' },
  enableImportExport: false,
  typeOptions: PROCESS_LIBRARY_TYPE_OPTIONS_MAP['equipment-assets'],
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
