<!--
  FileUploadBox

  负责：
  1. 封装本地文件选择和上传触发
  2. 避免不同页面重复文件输入逻辑
  3. 与后端真实上传接口配合
-->
<script setup lang="ts">
import { ref } from 'vue';
import { useI18n } from 'vue-i18n';

const emit = defineEmits<{
  upload: [file: File];
}>();

const selectedFile = ref<File | null>(null);
const { t } = useI18n();

function handleFileChange(event: Event): void {
  /**
   * 读取用户选择的文件。
   */
  const input = event.target as HTMLInputElement;
  selectedFile.value = input.files?.[0] || null;
}

function submit(): void {
  /**
   * 触发上传事件。
   */
  if (selectedFile.value) {
    emit('upload', selectedFile.value);
  }
}
</script>

<template>
  <div class="upload-box">
    <input type="file" @change="handleFileChange" />
    <span class="muted">{{ selectedFile?.name || t('common.uploadBox.placeholder') }}</span>
    <t-button theme="primary" :disabled="!selectedFile" @click="submit">{{ t('common.uploadBox.upload') }}</t-button>
  </div>
</template>

<style scoped>
.upload-box {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border: 1px dashed #9dbcf8;
  border-radius: 8px;
  background: #f8fbff;
}
</style>
