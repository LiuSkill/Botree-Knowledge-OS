<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';

import { createProcessRouteVersion, listProcessRouteVersions } from '@/api/process-config';
import { formatDateTime } from '@/utils/format';
import type { ProcessRouteVersion } from '@/views/process-config/route/types';

const props = withDefaults(
  defineProps<{
    visible: boolean;
    routeId?: number | null;
    routeName?: string;
    canCreate?: boolean;
  }>(),
  {
    routeId: null,
    routeName: '',
    canCreate: false,
  },
);

const emit = defineEmits<{
  'update:visible': [value: boolean];
  created: [value: ProcessRouteVersion];
}>();

const loading = ref(false);
const saving = ref(false);
const versions = ref<ProcessRouteVersion[]>([]);
const form = reactive({
  version_no: undefined as number | undefined,
  change_log: '',
});

const { t } = useI18n();
const visibleProxy = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const dialogHeader = computed(() =>
  props.routeName ? t('process.route.title.versionWithName', { name: props.routeName }) : t('process.route.title.version'),
);

const columns = computed(() => [
  { colKey: 'version_no', title: t('process.route.field.version'), width: 100, align: 'center' as const },
  { colKey: 'node_count', title: t('process.route.field.nodeCount'), width: 100, align: 'center' as const },
  { colKey: 'created_at', title: t('common.field.createdAt'), width: 170 },
  { colKey: 'change_log', title: t('process.route.field.changeLog'), minWidth: 240 },
]);

watch(
  () => [props.visible, props.routeId] as const,
  ([visible, routeId]) => {
    if (!visible || !routeId) return;
    form.version_no = undefined;
    form.change_log = '';
    loadVersions(routeId);
  },
  { immediate: true },
);

async function loadVersions(routeId: number): Promise<void> {
  loading.value = true;
  try {
    versions.value = await listProcessRouteVersions(routeId);
  } finally {
    loading.value = false;
  }
}

async function handleCreateVersion(): Promise<void> {
  if (!props.routeId) return;
  saving.value = true;
  try {
    const version = await createProcessRouteVersion(props.routeId, {
      version_no: form.version_no ?? null,
      change_log: normalizeOptionalText(form.change_log),
    });
    MessagePlugin.success(t('process.route.message.versionSaved'));
    emit('created', version);
    form.version_no = undefined;
    form.change_log = '';
    await loadVersions(props.routeId);
  } finally {
    saving.value = false;
  }
}

function normalizeOptionalText(value?: string | null): string | null {
  const text = value?.trim();
  return text || null;
}

function resolveNodeCount(snapshotJson: string): number {
  try {
    const snapshot = JSON.parse(snapshotJson) as { nodes?: unknown[] };
    return Array.isArray(snapshot?.nodes) ? snapshot.nodes.length : 0;
  } catch {
    return 0;
  }
}
</script>

<template>
  <t-dialog v-model:visible="visibleProxy" :header="dialogHeader" width="960px" :footer="false">
    <div class="route-version-dialog">
      <section v-if="canCreate" class="route-version-dialog__section">
        <div class="route-version-dialog__section-title">{{ t('process.route.section.createVersion') }}</div>
        <div class="route-version-dialog__form">
          <t-form label-align="top">
            <div class="route-version-dialog__form-grid">
              <t-form-item :label="t('process.route.field.version')">
                <t-input-number v-model="form.version_no" :min="1" :step="1" theme="normal" :placeholder="t('process.route.placeholder.versionAuto')" />
              </t-form-item>
              <t-form-item :label="t('process.route.field.changeLog')">
                <t-input v-model="form.change_log" clearable maxlength="300" :placeholder="t('process.route.placeholder.changeLog')" />
              </t-form-item>
            </div>
          </t-form>
          <div class="route-version-dialog__actions">
            <t-button theme="primary" :loading="saving" @click="handleCreateVersion">{{ t('process.route.action.saveVersion') }}</t-button>
          </div>
        </div>
      </section>

      <section class="route-version-dialog__section">
        <div class="route-version-dialog__section-title">{{ t('process.route.section.versionHistory') }}</div>
        <t-loading :loading="loading">
          <t-empty v-if="!versions.length" :description="t('process.route.empty.version')" />
          <div v-else class="route-version-dialog__table">
            <t-table row-key="id" bordered table-layout="fixed" size="small" :columns="columns" :data="versions">
              <template #version_no="{ row }">v{{ row.version_no }}</template>
              <template #node_count="{ row }">{{ resolveNodeCount(row.snapshot_json) }}</template>
              <template #created_at="{ row }">{{ formatDateTime(row.created_at) }}</template>
              <template #change_log="{ row }">{{ row.change_log || '-' }}</template>
            </t-table>
          </div>
        </t-loading>
      </section>
    </div>
  </t-dialog>
</template>

<style scoped>
.route-version-dialog {
  display: grid;
  gap: 16px;
}

.route-version-dialog__section {
  display: grid;
  gap: 12px;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
}

.route-version-dialog__section-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
}

.route-version-dialog__form {
  display: grid;
  gap: 12px;
}

.route-version-dialog__form-grid {
  display: grid;
  grid-template-columns: 180px minmax(0, 1fr);
  gap: 0 16px;
}

.route-version-dialog__actions {
  display: flex;
  justify-content: flex-end;
}

.route-version-dialog__table {
  overflow-x: auto;
}

.route-version-dialog__table :deep(.t-table) {
  min-width: 100%;
}

@media (max-width: 720px) {
  .route-version-dialog__form-grid {
    grid-template-columns: 1fr;
  }
}
</style>
