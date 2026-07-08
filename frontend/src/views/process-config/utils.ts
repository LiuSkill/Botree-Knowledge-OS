import { getProcessConfigModuleMeta, type ProcessConfigModuleKey } from '@/views/process-config/types';

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

function buildTimestamp(): string {
  const now = new Date();
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}`;
}

export function buildProcessConfigTemplateFileName(moduleKey: ProcessConfigModuleKey): string {
  return `${getProcessConfigModuleMeta(moduleKey).filenamePrefix}-template.xlsx`;
}

export function buildProcessConfigExportFileName(moduleKey: ProcessConfigModuleKey): string {
  return `${getProcessConfigModuleMeta(moduleKey).filenamePrefix}-export-${buildTimestamp()}.xlsx`;
}

export function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  window.document.body.appendChild(anchor);
  anchor.click();
  window.document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}
