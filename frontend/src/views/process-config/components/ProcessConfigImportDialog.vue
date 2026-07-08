<script setup lang="ts">
import { DownloadIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import type { UploadFile } from 'tdesign-vue-next';
import { computed, ref, watch } from 'vue';

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

const errorColumns = [
  { colKey: 'sheet', title: 'Sheet', width: 180, ellipsis: true },
  { colKey: 'row', title: '行号', width: 90, align: 'center' as const },
  { colKey: 'field', title: '字段', width: 160, ellipsis: true },
  { colKey: 'message', title: '错误原因', minWidth: 260, ellipsis: true },
];

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
  MessagePlugin.success(`${props.moduleLabel}模板已下载`);
}

async function handleConfirm(): Promise<void> {
  const file = currentFile();
  if (!file) {
    MessagePlugin.warning('请先选择需要导入的 Excel 文件');
    return;
  }

  importing.value = true;
  importErrors.value = [];
  try {
    const result = await importProcessConfigData(props.moduleKey, file);
    MessagePlugin.success(`已导入 ${result.imported_count} 条${props.moduleLabel}数据`);
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
    :header="`${moduleLabel}导入`"
    width="860px"
    :confirm-loading="importing"
    @confirm="handleConfirm"
  >
    <div class="import-dialog-content">
      <div class="import-toolbar">
        <div class="import-toolbar-text">
          <strong>导入说明</strong>
          <span>请先下载模板，按模板字段填写后再上传，系统会先校验再整批入库。</span>
        </div>
        <t-button theme="default" variant="outline" @click="handleDownloadTemplate">
          <template #icon><DownloadIcon /></template>
          下载模板
        </t-button>
      </div>

      <t-upload
        v-model="uploadFiles"
        accept=".xlsx"
        :auto-upload="false"
        :max="1"
        theme="file"
        tips="仅支持 .xlsx 文件。导入时如果存在编码重复、引用不存在或字段格式错误，系统会整批拒绝。"
      />

      <t-alert v-if="importErrors.length" theme="error" message="导入校验未通过，请根据下方错误信息修正 Excel 后重新导入。" />

      <div v-if="importErrors.length" class="error-table-wrap">
        <t-table
          row-key="__rowKey"
          size="small"
          bordered
          table-layout="fixed"
          :data="errorTableData"
          :columns="errorColumns"
          :max-height="320"
          empty="当前没有导入错误"
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
