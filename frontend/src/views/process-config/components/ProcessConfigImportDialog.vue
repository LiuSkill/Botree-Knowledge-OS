<script setup lang="ts">
import { DownloadIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import type { UploadFile } from 'tdesign-vue-next';
import { computed, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';

import { downloadProcessConfigTemplate, importProcessConfigData } from '@/api/process-config';
import type {
  ProcessConfigImportError,
  ProcessConfigImportResult,
  ProcessConfigModuleKey,
} from '@/views/process-config/types';
import { buildProcessConfigTemplateFileName, triggerBlobDownload } from '@/views/process-config/utils';

type ImportErrorRow = ProcessConfigImportError & {
  __rowKey: string;
};

const props = defineProps<{
  visible: boolean;
  moduleKey: ProcessConfigModuleKey;
  moduleLabel: string;
}>();

const emit = defineEmits<{
  'update:visible': [value: boolean];
  success: [result: ProcessConfigImportResult];
}>();

const importing = ref(false);
const { t } = useI18n();
const uploadFiles = ref<UploadFile[]>([]);
const importErrors = ref<ProcessConfigImportError[]>([]);

const dialogVisible = computed({
  get: () => props.visible,
  set: (value: boolean) => emit('update:visible', value),
});

const errorTableData = computed<ImportErrorRow[]>(() =>
  importErrors.value.map((item, index) => ({
    ...item,
    __rowKey: `${item.sheet}-${item.row}-${item.field}-${index}`,
  })),
);

const errorColumns = computed(() => [
  { colKey: 'sheet', title: 'Sheet', width: 180, ellipsis: true },
  { colKey: 'row', title: t('process.field.rowNumber'), width: 90, align: 'center' as const },
  { colKey: 'field', title: t('process.field.importField'), width: 160, ellipsis: true },
  { colKey: 'message', title: t('process.field.importReason'), minWidth: 260, ellipsis: true },
]);

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      resetState();
    }
  },
);

function resetState(): void {
  uploadFiles.value = [];
  importErrors.value = [];
  importing.value = false;
}

function currentFile(): File | null {
  return uploadFiles.value[0]?.raw || null;
}

function extractImportErrors(error: unknown): ProcessConfigImportError[] {
  const payload = (error as { response?: { data?: { data?: { errors?: unknown } } } })?.response?.data?.data?.errors;
  if (!Array.isArray(payload)) {
    return [];
  }
  return payload
    .map((item) => {
      if (!item || typeof item !== 'object') return null;
      const current = item as Record<string, unknown>;
      return {
        sheet: String(current.sheet || ''),
        row: Number(current.row || 0),
        field: String(current.field || ''),
        message: String(current.message || ''),
      } satisfies ProcessConfigImportError;
    })
    .filter((item): item is ProcessConfigImportError => Boolean(item));
}

async function handleDownloadTemplate(): Promise<void> {
  const blob = await downloadProcessConfigTemplate(props.moduleKey);
  triggerBlobDownload(blob, buildProcessConfigTemplateFileName(props.moduleKey));
  MessagePlugin.success(t('process.message.templateDownloaded', { module: props.moduleLabel }));
}

async function handleConfirm(): Promise<void> {
  const file = currentFile();
  if (!file) {
    MessagePlugin.warning(t('process.message.importFileRequired'));
    return;
  }

  importing.value = true;
  importErrors.value = [];
  try {
    const result = await importProcessConfigData(props.moduleKey, file);
    MessagePlugin.success(t('process.message.importDone', { count: result.imported_count, module: props.moduleLabel }));
    emit('success', result);
    dialogVisible.value = false;
  } catch (error) {
    importErrors.value = extractImportErrors(error);
  } finally {
    importing.value = false;
  }
}
</script>

<template>
  <t-dialog
    v-model:visible="dialogVisible"
    :header="t('process.import.title', { module: moduleLabel })"
    width="860px"
    :confirm-loading="importing"
    @confirm="handleConfirm"
  >
    <div class="import-dialog-content">
      <div class="import-toolbar">
        <div class="import-toolbar-text">
          <strong>{{ t('process.import.guideTitle') }}</strong>
          <span>{{ t('process.import.guideText') }}</span>
        </div>
        <t-button theme="default" variant="outline" @click="handleDownloadTemplate">
          <template #icon><DownloadIcon /></template>
          {{ t('process.action.downloadTemplate') }}
        </t-button>
      </div>

      <t-upload
        v-model="uploadFiles"
        accept=".xlsx"
        :auto-upload="false"
        :max="1"
        theme="file"
        :tips="t('process.import.tips')"
      />

      <t-alert v-if="importErrors.length" theme="error" :message="t('process.import.invalidAlert')" />

      <div v-if="importErrors.length" class="error-table-wrap">
        <t-table
          row-key="__rowKey"
          size="small"
          bordered
          table-layout="fixed"
          :data="errorTableData"
          :columns="errorColumns"
          :max-height="320"
          :empty="t('process.empty.importErrors')"
        />
      </div>
    </div>
  </t-dialog>
</template>

<style scoped>
.import-dialog-content {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.import-toolbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #f8fafc;
}

.import-toolbar-text {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 4px;
}

.import-toolbar-text strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
}

.import-toolbar-text span {
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.error-table-wrap {
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  overflow: hidden;
}

@media (max-width: 720px) {
  .import-toolbar {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
