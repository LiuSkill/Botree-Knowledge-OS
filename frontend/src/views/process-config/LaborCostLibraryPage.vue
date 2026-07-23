<script setup lang="ts">
import { PERMISSIONS } from '@/constants/permissions';
import BaseProcessLibraryPage from '@/views/process-config/components/BaseProcessLibraryPage.vue';
import type { ProcessLibraryPageConfig } from '@/views/process-config/types';
import { PROCESS_LIBRARY_TYPE_OPTIONS_MAP } from '@/views/process-config/types';

const config: ProcessLibraryPageConfig = {
  title: '人员成本库',
  entityName: '人员成本',
  moduleKey: 'labor-costs',
  apiBasePath: '/process-config/labor-costs',
  typeOptions: PROCESS_LIBRARY_TYPE_OPTIONS_MAP['labor-costs'],
  permissions: {
    view: PERMISSIONS.PROCESS_CONFIG_LABOR_VIEW,
    create: PERMISSIONS.PROCESS_CONFIG_LABOR_CREATE,
    update: PERMISSIONS.PROCESS_CONFIG_LABOR_UPDATE,
    delete: PERMISSIONS.PROCESS_CONFIG_LABOR_DELETE,
    import: PERMISSIONS.PROCESS_CONFIG_LABOR_CREATE,
    export: PERMISSIONS.PROCESS_CONFIG_LABOR_VIEW,
  },
};
</script>

<template>
  <BaseProcessLibraryPage :config="config" />
</template>
