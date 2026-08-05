<!--
  Review Detail Page

  负责：
  1. 展示单个审核任务详情与关联文档基础信息
  2. 提供审核通过、驳回与去构建索引入口
  3. 复用文档详情页原始内容预览交互，便于审核人员直接核验内容
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { AssignmentCheckedIcon, FullscreenIcon } from 'tdesign-icons-vue-next';
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
import type { Directive } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';

import {
  downloadDocumentAsset,
  downloadDocumentPdfPreview,
  getDocument,
  getDocumentPreview,
  listDocumentVersions,
} from '@/api/documents';
import { approveReviewTask, getReviewTask, rejectReviewTask } from '@/api/reviews';
import ChatRichContent from '@/components/ChatRichContent.vue';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import ZoomPreviewDialog from '@/components/ZoomPreviewDialog.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { DocumentAssetInfo, DocumentInfo, DocumentPreview, DocumentVersionInfo, ReviewTask } from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { indexStatusText as resolveIndexStatusText, parseStatusText as resolveParseStatusText, isReviewTaskPending } from '@/utils/constants';
import { formatDateTime, formatFileSize } from '@/utils/format';
import { securityLevelLabel } from '@/utils/securityLevels';

const MARKDOWN_ASSET_METADATA_KEYS = [
  'original_candidate_value',
  'resolved_local_path',
  'local_path',
  'inline_payload_key',
  'remote_url',
  'image_path',
  'img_path',
  'path',
  'saved_path',
  'file_name',
  'image_name',
  'img_name',
] as const;

const IMAGE_PLACEHOLDER_SRC = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
const PREVIEW_MARKDOWN_SEGMENT_TARGET_CHARS = 12000;
const PREVIEW_MARKDOWN_SEGMENT_MAX_CHARS = 24000;
const INITIAL_PREVIEW_SEGMENT_COUNT = 1;
const PREVIEW_SEGMENT_BATCH_SIZE = 1;
const LAZY_ASSET_ROOT_MARGIN = '360px 0px';

interface RenderedMarkdownSegment {
  id: string;
  content: string;
}

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const { t } = useI18n();

const loading = ref(false);
const previewLoading = ref(false);
const pdfPreviewVisible = ref(false);
const pdfPreviewLoading = ref(false);
const pdfPreviewUrl = ref('');
const pdfPreviewTitle = ref('');
const pdfPreviewError = ref('');
const zoomPreviewVisible = ref(false);

const task = ref<ReviewTask | null>(null);
const documentInfo = ref<DocumentInfo | null>(null);
const previewData = ref<DocumentPreview | null>(null);
const versions = ref<DocumentVersionInfo[]>([]);
const rejectDialogVisible = ref(false);
const rejectSubmitting = ref(false);
const rejectForm = reactive({
  comment: '',
});

const assetUrlMap = reactive<Record<number, string>>({});
const assetPromiseMap = new Map<number, Promise<string>>();
const markdownPreviewSegments = ref<string[]>([]);
const renderedMarkdownSegments = ref<RenderedMarkdownSegment[]>([]);
const markdownPreviewCursor = ref(0);
const markdownPreviewRendering = ref(false);
const observedAssetImages = new Set<HTMLImageElement>();
let assetImageObserver: IntersectionObserver | null = null;
let markdownPreviewGeneration = 0;

const taskId = computed(() => Number(route.params.id));
const viewedVersionNo = computed(() => task.value?.display_version_no ?? task.value?.version_no ?? documentInfo.value?.version_no ?? null);
const reviewedVersion = computed(() => {
  const versionNo = viewedVersionNo.value;
  return versionNo ? versions.value.find((item) => item.version_no === versionNo) || null : null;
});
const markdownContent = computed(() => previewData.value?.markdown_content?.trim() || '');
const markdownPreviewHasMore = computed(() => markdownPreviewCursor.value < markdownPreviewSegments.value.length);
const structuredPreviewPages = computed(() => {
  const pages = previewData.value?.pages || [];
  if (!pages.length || collectMarkdownImageSources(markdownContent.value).length > 0) return [];
  return pages.filter((page) => page.page_preview_asset || page.blocks.some((block) => block.image_asset));
});

const admissionLabel = (status: string) => ({
  text_indexed: t('document.detail.indexAdmission.textIndexed'),
  visual_indexed: t('document.detail.indexAdmission.visualIndexed'),
  metadata_only: t('document.detail.indexAdmission.metadataOnly'),
  waiting_correction: t('document.detail.indexAdmission.waitingCorrection'),
}[status] || status);
const documentFileName = computed(() => reviewedVersion.value?.file_name || task.value?.document_file_name || documentInfo.value?.file_name || t('review.scope.documentFallback', { id: task.value?.document_id || '-' }));
const documentProjectName = computed(() => documentInfo.value?.project_name || (documentInfo.value?.project_id ? t('review.scope.projectFallback', { id: documentInfo.value.project_id }) : t('review.scope.base')));
const viewedFileSize = computed(() => reviewedVersion.value?.file_size ?? documentInfo.value?.file_size ?? 0);
const viewedFileType = computed(() => reviewedVersion.value?.file_type || documentInfo.value?.file_type || '');
const viewedSecurityLevel = computed(() => reviewedVersion.value?.security_level || documentInfo.value?.security_level || 'internal');
const uploaderLabel = computed(() => {
  return (
    documentInfo.value?.uploader_name ||
    documentInfo.value?.uploader_username ||
    task.value?.uploader_name ||
    task.value?.uploader_username ||
    (documentInfo.value?.upload_user_id ? t('review.scope.userFallback', { id: documentInfo.value.upload_user_id }) : '') ||
    (task.value?.uploader_id ? t('review.scope.userFallback', { id: task.value.uploader_id }) : '-')
  );
});
const parseStatusValue = computed(() => reviewedVersion.value?.parse_status || documentInfo.value?.parse_status || 'unparsed');
const indexStatusValue = computed(() => reviewedVersion.value?.index_status || documentInfo.value?.index_status || 'not_indexed');
const canApproveTask = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_APPROVE));
const canRejectTask = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_REJECT));
const canBuildIndex = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_BUILD_INDEX));
const canPreviewDocument = computed(() => {
  const info = documentInfo.value;
  if (!info) return false;
  const permission = info.knowledge_type === 'project' ? PERMISSIONS.PROJECT_DOCUMENT_PREVIEW : PERMISSIONS.KNOWLEDGE_VIEW;
  return authStore.hasActionPermission(permission);
});
const showBuildIndexAction = computed(() => task.value?.review_status === 'approved' && canBuildIndex.value);
const pdfPreviewButtonLabel = computed(() => (isPdfFile(documentFileName.value, viewedFileType.value) ? t('document.detail.originalPdf') : t('document.detail.convertedPdf')));

async function loadTask(): Promise<void> {
  task.value = await getReviewTask(taskId.value);
}

async function loadDocument(): Promise<void> {
  if (!task.value) return;
  documentInfo.value = await getDocument(task.value.document_id);
}

async function loadVersions(): Promise<void> {
  if (!task.value) return;
  versions.value = await listDocumentVersions(task.value.document_id);
}

async function loadPreview(): Promise<void> {
  if (!task.value) return;
  previewLoading.value = true;
  try {
    previewData.value = await getDocumentPreview(task.value.document_id, viewedVersionNo.value);
    resetRenderedMarkdown(markdownContent.value);
    await renderNextMarkdownSegments(INITIAL_PREVIEW_SEGMENT_COUNT);
  } finally {
    previewLoading.value = false;
  }
}

async function loadData(): Promise<void> {
  loading.value = true;
  try {
    await loadTask();
    await Promise.all([loadDocument(), loadVersions()]);
    await loadPreview();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('review.message.detailLoadFailed'));
  } finally {
    loading.value = false;
  }
}

async function decide(action: 'approve' | 'reject'): Promise<void> {
  if (!task.value) return;
  if (action === 'approve' && !canApproveTask.value) {
    MessagePlugin.warning(t('review.message.noApprovePermission'));
    return;
  }
  if (action === 'reject' && !canRejectTask.value) {
    MessagePlugin.warning(t('review.message.noRejectPermission'));
    return;
  }
  if (action === 'reject') {
    openRejectDialog();
    return;
  }
  task.value = await approveReviewTask(task.value.id);
  await Promise.all([loadDocument(), loadVersions()]);
  MessagePlugin.success(t('review.message.reviewDone'));
}

function openRejectDialog(): void {
  rejectForm.comment = '';
  rejectDialogVisible.value = true;
}

function closeRejectDialog(): void {
  if (rejectSubmitting.value) return;
  rejectDialogVisible.value = false;
  rejectForm.comment = '';
}

async function confirmRejectTask(): Promise<void> {
  if (!task.value) return;
  const comment = rejectForm.comment.trim();
  if (!comment) {
    MessagePlugin.warning(t('review.message.rejectReasonRequired'));
    return;
  }

  rejectSubmitting.value = true;
  try {
    task.value = await rejectReviewTask(task.value.id, comment);
    await Promise.all([loadDocument(), loadVersions()]);
    MessagePlugin.success(t('review.message.rejected'));
    rejectDialogVisible.value = false;
    rejectForm.comment = '';
  } finally {
    rejectSubmitting.value = false;
  }
}

function goBuildIndex(): void {
  router.push(withBreadcrumbContext(route, { path: '/reviews', query: { tab: 'approved' } }));
}

function taskLabel(): string {
  return t('review.tab.tasks');
}

function taskFileLinkText(): string {
  return documentFileName.value;
}

function openReviewedDocument(): void {
  if (!task.value) return;
  router.push(withBreadcrumbContext(route, `/documents/${task.value.document_id}`));
}

function parseStatusText(status: string): string {
  return resolveParseStatusText(status) || '-';
}

function parseStatusTheme(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (['success', 'parsed'].includes(status)) return 'success';
  if (['parsing', 'unparsed'].includes(status)) return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function indexStatusText(status: string): string {
  return resolveIndexStatusText(status) || '-';
}

function indexStatusTheme(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (['indexed'].includes(status)) return 'success';
  if (['parsing', 'parsed', 'parsed_pending_review', 'indexing', 'not_indexed'].includes(status)) return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function normalizeAssetKey(value: string): string {
  return value
    .trim()
    .replace(/^['"]|['"]$/g, '')
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .toLowerCase();
}

function basenameFromPath(value: string): string {
  const normalized = normalizeAssetKey(value);
  return normalized.split('/').filter(Boolean).pop() || normalized;
}

function parseAssetMetadata(asset: DocumentAssetInfo): Record<string, unknown> {
  if (!asset.metadata_json) return {};
  try {
    const parsed = JSON.parse(asset.metadata_json);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function collectAssetLookupKeys(asset: DocumentAssetInfo): string[] {
  const metadata = parseAssetMetadata(asset);
  const rawValues = [
    asset.file_name,
    ...MARKDOWN_ASSET_METADATA_KEYS.map((key) => metadata[key]),
  ].filter((item): item is string => typeof item === 'string' && item.trim().length > 0);

  const keys = new Set<string>();
  for (const value of rawValues) {
    const normalized = normalizeAssetKey(value);
    keys.add(normalized);
    keys.add(basenameFromPath(normalized));
  }
  return Array.from(keys);
}

function findMarkdownImageAsset(src: string): DocumentAssetInfo | null {
  const normalizedSrc = normalizeAssetKey(src);
  const basename = basenameFromPath(normalizedSrc);
  const assets = previewData.value?.markdown_image_assets || [];
  return (
    assets.find((asset) => {
      const keys = collectAssetLookupKeys(asset);
      return keys.includes(normalizedSrc) || keys.includes(basename);
    }) || null
  );
}

function isExternalImageSource(src: string): boolean {
  return /^(https?:|data:|blob:)/i.test(src.trim());
}

function collectMarkdownImageSources(markdown: string): string[] {
  const sources = new Set<string>();
  markdown.replace(/!\[[^\]]*]\(([^)\s]+)(?:\s+"[^"]*")?\)/g, (_match, src: string) => {
    if (src) sources.add(src);
    return _match;
  });
  markdown.replace(/<img\b[^>]*\bsrc\s*=\s*(?:"([^"]+)"|'([^']+)')/gi, (_match, srcA: string, srcB: string) => {
    const src = srcA || srcB;
    if (src) sources.add(src);
    return _match;
  });
  return Array.from(sources);
}

function splitOversizedMarkdownBlock(block: string): string[] {
  if (block.length <= PREVIEW_MARKDOWN_SEGMENT_MAX_CHARS) return [block];
  const segments: string[] = [];
  for (let start = 0; start < block.length; start += PREVIEW_MARKDOWN_SEGMENT_TARGET_CHARS) {
    segments.push(block.slice(start, start + PREVIEW_MARKDOWN_SEGMENT_TARGET_CHARS));
  }
  return segments;
}

function splitHtmlTableRows(tableHtml: string): string[] {
  const openMatch = tableHtml.match(/^<table\b[^>]*>/i);
  const closeMatch = tableHtml.match(/<\/table>\s*$/i);
  const openTag = openMatch?.[0] || '<table>';
  const closeTag = closeMatch?.[0].trim() || '</table>';
  const body = tableHtml.slice(openMatch?.[0].length || 0, closeMatch?.index ?? tableHtml.length);
  const rows = body.match(/<tr\b[\s\S]*?<\/tr>/gi);
  if (!rows?.length) return splitOversizedMarkdownBlock(tableHtml);

  const segments: string[] = [];
  let currentRows: string[] = [];
  let currentLength = openTag.length + closeTag.length;
  const flushRows = () => {
    if (!currentRows.length) return;
    segments.push(`${openTag}${currentRows.join('')}${closeTag}`);
    currentRows = [];
    currentLength = openTag.length + closeTag.length;
  };
  for (const row of rows) {
    if (currentRows.length && currentLength + row.length > PREVIEW_MARKDOWN_SEGMENT_TARGET_CHARS) flushRows();
    currentRows.push(row);
    currentLength += row.length;
    if (currentLength >= PREVIEW_MARKDOWN_SEGMENT_MAX_CHARS) flushRows();
  }
  flushRows();
  return segments;
}

function splitDenseHtmlTable(markdown: string): string[] {
  const segments: string[] = [];
  const tablePattern = /<table\b[\s\S]*?<\/table>/gi;
  let cursor = 0;
  for (const match of markdown.matchAll(tablePattern)) {
    const start = match.index || 0;
    if (start > cursor) segments.push(markdown.slice(cursor, start));
    segments.push(...(match[0].length <= PREVIEW_MARKDOWN_SEGMENT_MAX_CHARS ? [match[0]] : splitHtmlTableRows(match[0])));
    cursor = start + match[0].length;
  }
  if (cursor < markdown.length) segments.push(markdown.slice(cursor));
  return segments.filter((segment) => segment.trim());
}

function splitMarkdownPlainText(markdown: string): string[] {
  const segments: string[] = [];
  const buffer: string[] = [];
  let bufferLength = 0;
  let fenceMarker: string | null = null;
  const flushBuffer = () => {
    const value = buffer.join('\n').trim();
    if (value) segments.push(...splitOversizedMarkdownBlock(value));
    buffer.length = 0;
    bufferLength = 0;
  };

  for (const line of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const trimmedLine = line.trim();
    const fenceMatch = trimmedLine.match(/^(```|~~~)/);
    if (fenceMatch) fenceMarker = fenceMarker ? null : fenceMatch[1];
    if (!fenceMarker && !trimmedLine && bufferLength >= PREVIEW_MARKDOWN_SEGMENT_TARGET_CHARS) {
      flushBuffer();
      continue;
    }
    if (!fenceMarker && bufferLength >= PREVIEW_MARKDOWN_SEGMENT_TARGET_CHARS && /^(#{1,6}\s+|[-*]\s+|\d+\.\s+)/.test(trimmedLine)) {
      flushBuffer();
    }
    buffer.push(line);
    bufferLength += line.length + 1;
    if (!fenceMarker && bufferLength >= PREVIEW_MARKDOWN_SEGMENT_MAX_CHARS) flushBuffer();
  }
  flushBuffer();
  return segments;
}

function splitMarkdownForPreview(markdown: string): string[] {
  if (!markdown.trim()) return [];
  return splitDenseHtmlTable(markdown).flatMap((segment) =>
    /^<table\b[\s\S]*<\/table>$/i.test(segment.trim()) ? [segment.trim()] : splitMarkdownPlainText(segment),
  );
}

function resetRenderedMarkdown(markdown: string): void {
  markdownPreviewGeneration += 1;
  renderedMarkdownSegments.value = [];
  markdownPreviewSegments.value = splitMarkdownForPreview(markdown);
  markdownPreviewCursor.value = 0;
  markdownPreviewRendering.value = false;
}

function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => window.requestAnimationFrame(() => resolve()));
}

async function renderNextMarkdownSegments(count = PREVIEW_SEGMENT_BATCH_SIZE): Promise<void> {
  const generation = markdownPreviewGeneration;
  if (markdownPreviewRendering.value || !markdownPreviewHasMore.value) return;
  markdownPreviewRendering.value = true;
  try {
    const end = Math.min(markdownPreviewCursor.value + count, markdownPreviewSegments.value.length);
    while (markdownPreviewCursor.value < end) {
      const index = markdownPreviewCursor.value;
      const content = markdownPreviewSegments.value[index];
      renderedMarkdownSegments.value.push({ id: `${generation}-${index}`, content });
      markdownPreviewCursor.value = index + 1;
      const assets = collectMarkdownImageSources(content)
        .map((source) => findMarkdownImageAsset(source))
        .filter((asset): asset is DocumentAssetInfo => Boolean(asset));
      void Promise.allSettled(assets.map((asset) => ensureAssetUrl(asset)));
      await nextTick();
      await yieldToBrowser();
      if (generation !== markdownPreviewGeneration) return;
    }
  } finally {
    if (generation === markdownPreviewGeneration) markdownPreviewRendering.value = false;
  }
}

function collectPreviewAssets(): DocumentAssetInfo[] {
  const preview = previewData.value;
  if (!preview) return [];
  const assets = [...preview.markdown_image_assets];
  for (const page of preview.pages) {
    if (page.page_preview_asset) assets.push(page.page_preview_asset);
    for (const block of page.blocks) if (block.image_asset) assets.push(block.image_asset);
  }
  return Array.from(new Map(assets.map((asset) => [asset.id, asset])).values());
}

function findPreviewAssetById(assetId: number): DocumentAssetInfo | null {
  return collectPreviewAssets().find((asset) => asset.id === assetId) || null;
}

function unobserveAssetImage(element: HTMLImageElement): void {
  assetImageObserver?.unobserve(element);
  observedAssetImages.delete(element);
}

async function loadAssetImageElement(element: HTMLImageElement, asset: DocumentAssetInfo): Promise<void> {
  if (element.dataset.documentAssetLoading === String(asset.id)) return;
  element.dataset.documentAssetLoading = String(asset.id);
  try {
    const url = await ensureAssetUrl(asset);
    if (url && element.dataset.documentAssetId === String(asset.id)) element.src = url;
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : t('document.detail.assetPreviewFailed', { id: asset.id }));
  } finally {
    delete element.dataset.documentAssetLoading;
  }
}

function getAssetImageObserver(): IntersectionObserver | null {
  if (typeof window === 'undefined' || !('IntersectionObserver' in window)) return null;
  if (!assetImageObserver) {
    assetImageObserver = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        const element = entry.target as HTMLImageElement;
        const asset = findPreviewAssetById(Number(element.dataset.documentAssetId));
        unobserveAssetImage(element);
        if (asset) void loadAssetImageElement(element, asset);
      }
    }, { rootMargin: LAZY_ASSET_ROOT_MARGIN });
  }
  return assetImageObserver;
}

function bindAssetImageElement(element: HTMLImageElement, asset: DocumentAssetInfo | null | undefined): void {
  unobserveAssetImage(element);
  if (!asset || asset.status !== 'ready') return;
  element.dataset.documentAssetId = String(asset.id);
  const cachedUrl = assetUrlMap[asset.id];
  if (cachedUrl) {
    element.src = cachedUrl;
    return;
  }
  element.src = IMAGE_PLACEHOLDER_SRC;
  const observer = getAssetImageObserver();
  if (observer) {
    observer.observe(element);
    observedAssetImages.add(element);
  } else {
    void loadAssetImageElement(element, asset);
  }
}

const vAssetLazy: Directive<HTMLImageElement, DocumentAssetInfo | null | undefined> = {
  mounted(element, binding) {
    bindAssetImageElement(element, binding.value);
  },
  updated(element, binding) {
    bindAssetImageElement(element, binding.value);
  },
  unmounted: unobserveAssetImage,
};

async function ensureAssetUrl(asset: DocumentAssetInfo | null | undefined): Promise<string> {
  if (!asset || asset.status !== 'ready') return '';
  if (assetUrlMap[asset.id]) return assetUrlMap[asset.id];
  const pendingPromise = assetPromiseMap.get(asset.id);
  if (pendingPromise) return pendingPromise;

  const promise = (async () => {
    const blob = await downloadDocumentAsset(asset.id);
    const url = URL.createObjectURL(blob);
    assetUrlMap[asset.id] = url;
    assetPromiseMap.delete(asset.id);
    return url;
  })().catch((error) => {
    assetPromiseMap.delete(asset.id);
    throw error;
  });

  assetPromiseMap.set(asset.id, promise);
  return promise;
}

function assetBlobUrl(asset: DocumentAssetInfo | null | undefined): string {
  if (!asset) return '';
  return assetUrlMap[asset.id] || '';
}

function resolvePreviewImageSource(src: string): string | null {
  if (isExternalImageSource(src)) return src.trim();
  const asset = findMarkdownImageAsset(src);
  if (!asset) return null;
  return assetBlobUrl(asset) || null;
}

function revokePdfPreviewUrl(): void {
  if (!pdfPreviewUrl.value) return;
  URL.revokeObjectURL(pdfPreviewUrl.value);
  pdfPreviewUrl.value = '';
}

function resetAssetUrls(): void {
  for (const url of Object.values(assetUrlMap)) {
    URL.revokeObjectURL(url);
  }
  for (const key of Object.keys(assetUrlMap)) {
    delete assetUrlMap[Number(key)];
  }
  assetPromiseMap.clear();
}

function isPdfFile(fileName: string, fileType?: string | null): boolean {
  const normalizedType = (fileType || '').toLowerCase().replace(/^\./, '');
  return normalizedType === 'pdf' || fileName.toLowerCase().endsWith('.pdf');
}

async function openDocumentPdfPreview(): Promise<void> {
  if (!task.value || !documentInfo.value || pdfPreviewLoading.value) return;
  if (!canPreviewDocument.value) {
    MessagePlugin.warning(t('document.detail.message.noPreviewPermission'));
    return;
  }

  const sourceText = isPdfFile(documentFileName.value, viewedFileType.value) ? t('document.detail.pdfOriginal') : t('document.detail.pdfConverted');
  revokePdfPreviewUrl();
  pdfPreviewError.value = '';
  pdfPreviewTitle.value = `${documentFileName.value} · ${sourceText}`;
  pdfPreviewVisible.value = true;
  pdfPreviewLoading.value = true;

  try {
    const blob = await downloadDocumentPdfPreview(task.value.document_id, viewedVersionNo.value);
    const previewUrl = URL.createObjectURL(new Blob([blob], { type: 'application/pdf' }));
    if (pdfPreviewVisible.value) {
      pdfPreviewUrl.value = previewUrl;
    } else {
      URL.revokeObjectURL(previewUrl);
    }
  } catch (error) {
    if (pdfPreviewVisible.value) {
      pdfPreviewError.value = error instanceof Error ? error.message : t('document.detail.pdfPreviewLoadFailed');
    }
  } finally {
    pdfPreviewLoading.value = false;
  }
}

function closePdfPreview(): void {
  pdfPreviewVisible.value = false;
  pdfPreviewError.value = '';
  revokePdfPreviewUrl();
}

onMounted(loadData);

onBeforeUnmount(() => {
  assetImageObserver?.disconnect();
  observedAssetImages.clear();
  revokePdfPreviewUrl();
  resetAssetUrls();
});
</script>

<template>
  <PageContainer :title="t('review.title.detail')" :subtitle="t('review.subtitle.detail')">
    <template #actions>
      <div class="detail-action-group">
        <t-button variant="outline" @click="router.push('/reviews')">{{ t('review.action.backToCenter') }}</t-button>
        <t-button
          v-if="showBuildIndexAction"
          v-permission="PERMISSIONS.REVIEW_BUILD_INDEX"
          theme="primary"
          @click="goBuildIndex"
        >
          <template #icon><AssignmentCheckedIcon /></template>
          {{ t('review.action.goBuildIndex') }}
        </t-button>
        <t-button
          v-permission="PERMISSIONS.REVIEW_APPROVE"
          theme="success"
          :disabled="!canApproveTask || !isReviewTaskPending(task?.review_status)"
          @click="decide('approve')"
        >
          {{ t('review.action.approve') }}
        </t-button>
        <t-button
          v-permission="PERMISSIONS.REVIEW_REJECT"
          theme="danger"
          :disabled="!canRejectTask || !isReviewTaskPending(task?.review_status)"
          @click="decide('reject')"
        >
          {{ t('review.action.reject') }}
        </t-button>
      </div>
    </template>

    <div class="review-detail-page" v-loading="loading">
      <template v-if="task && documentInfo">
        <section class="summary-band">
          <div class="summary-grid">
            <div class="summary-item">
              <div class="summary-label">{{ t('review.tab.tasks') }}</div>
              <div class="summary-value">{{ taskLabel() }}</div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('review.field.document') }}</div>
              <div class="summary-value file-name-value">
                <t-link theme="primary" @click="openReviewedDocument">{{ taskFileLinkText() }}</t-link>
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('review.field.reviewStatus') }}</div>
              <div class="summary-value">
                <StatusTag type="review" :value="task.review_status" />
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('document.detail.field.viewedVersion') }}</div>
              <div class="summary-value">{{ viewedVersionNo ? `v${viewedVersionNo}` : '-' }}</div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('document.detail.field.fileSize') }}</div>
              <div class="summary-value">{{ formatFileSize(viewedFileSize) }}</div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('document.detail.field.parseStatus') }}</div>
              <div class="summary-value">
                <t-tag size="small" variant="light" :theme="parseStatusTheme(parseStatusValue)">
                  {{ parseStatusText(parseStatusValue) }}
                </t-tag>
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('review.field.buildStatus') }}</div>
              <div class="summary-value">
                <t-tag size="small" variant="light" :theme="indexStatusTheme(indexStatusValue)">
                  {{ indexStatusText(indexStatusValue) }}
                </t-tag>
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">{{ t('review.field.uploader') }}</div>
              <div class="summary-value">{{ uploaderLabel }}</div>
            </div>
          </div>

          <div class="summary-aside">
            <div class="summary-line">{{ t('document.detail.field.knowledgeScope') }}: {{ documentProjectName }}</div>
            <div class="summary-line">{{ t('review.field.category') }}: {{ task.document_category_path || task.document_category_name || documentInfo.category_path || documentInfo.category_name || '-' }}</div>
            <div class="summary-line">{{ t('document.detail.field.securityLevel') }}: {{ securityLevelLabel(viewedSecurityLevel) }}</div>
            <div class="summary-line">{{ t('document.detail.field.createdAt') }}: {{ formatDateTime(task.created_at) }}</div>
            <div class="summary-line">{{ t('review.field.comment') }}: {{ task.review_comment || t('review.detail.noComment') }}</div>
          </div>
        </section>

        <section class="main-panel">
          <div class="preview-tabs">
            <div class="preview-tab active">{{ t('document.detail.tab.preview') }}</div>
          </div>

          <section class="tab-panel">
            <div class="preview-toolbar preview-toolbar-main">
              <span class="muted-text">{{ t('document.detail.field.viewedVersion') }} {{ viewedVersionNo ? `v${viewedVersionNo}` : '-' }}</span>
              <div class="preview-toolbar-actions">
                <t-button
                  size="small"
                  variant="text"
                  class="preview-toolbar-link"
                  :disabled="previewLoading || !markdownContent"
                  @click="zoomPreviewVisible = true"
                >
                  <template #icon><FullscreenIcon /></template>
                  {{ t('document.detail.action.zoomPreview') }}
                </t-button>
                <t-button
                  v-if="documentInfo && canPreviewDocument"
                  size="small"
                  variant="text"
                  class="preview-toolbar-link"
                  :loading="pdfPreviewLoading"
                  @click="openDocumentPdfPreview"
                >
                  {{ pdfPreviewButtonLabel }}
                </t-button>
                <span class="muted-text">{{ t('document.detail.field.pageCount') }} {{ previewData?.page_count || 0 }}</span>
              </div>
            </div>

            <div class="preview-content-scroll">
              <div v-if="previewLoading" class="empty-panel">{{ t('document.detail.empty.loadingPreview') }}</div>
              <div v-else-if="!markdownContent" class="empty-panel">{{ t('review.detail.noPreview') }}</div>
              <template v-else>
                <div class="markdown-preview-stream">
                  <ChatRichContent
                    v-for="segment in renderedMarkdownSegments"
                    :key="segment.id"
                    class="review-rich-content"
                    :content="segment.content"
                    :image-source-resolver="resolvePreviewImageSource"
                  />
                  <div v-if="markdownPreviewHasMore" class="preview-load-more">
                    <t-button
                      size="small"
                      variant="outline"
                      :loading="markdownPreviewRendering"
                      @click="renderNextMarkdownSegments()"
                    >
                      {{ t('document.detail.action.loadMorePreview') }}
                    </t-button>
                  </div>
                </div>
                <div v-if="structuredPreviewPages.length" class="structured-preview">
                  <article v-for="page in structuredPreviewPages" :key="page.id" class="page-preview-card">
                    <div class="page-preview-title">
                      Page {{ page.page_no }}
                      <t-tag size="small" variant="light">{{ admissionLabel(page.index_admission_status) }}</t-tag>
                    </div>
                    <img
                      v-if="page.page_preview_asset?.status === 'ready'"
                      v-asset-lazy="page.page_preview_asset"
                      class="page-preview-image"
                      :src="assetBlobUrl(page.page_preview_asset) || IMAGE_PLACEHOLDER_SRC"
                      :alt="`Page ${page.page_no}`"
                      loading="lazy"
                      decoding="async"
                    />
                    <div v-if="page.blocks.some((block) => block.image_asset?.status === 'ready')" class="block-image-grid">
                      <img
                        v-for="block in page.blocks.filter((item) => item.image_asset?.status === 'ready')"
                        :key="block.id"
                        v-asset-lazy="block.image_asset"
                        class="block-preview-image"
                        :src="assetBlobUrl(block.image_asset) || IMAGE_PLACEHOLDER_SRC"
                        :alt="block.text || `Block ${block.block_index}`"
                        loading="lazy"
                        decoding="async"
                      />
                    </div>
                  </article>
                </div>
              </template>
            </div>
          </section>
        </section>
      </template>
    </div>

    <t-dialog
      v-model:visible="rejectDialogVisible"
      :header="t('review.rejectDialog.singleTitle')"
      width="520px"
      :confirm-btn="{ content: t('review.rejectDialog.confirm'), theme: 'danger', loading: rejectSubmitting }"
      :cancel-btn="{ content: t('common.action.cancel'), disabled: rejectSubmitting }"
      :close-on-overlay-click="!rejectSubmitting"
      @confirm="confirmRejectTask"
      @close="closeRejectDialog"
    >
      <t-form label-align="top">
        <t-form-item :label="t('review.field.rejectTarget')">
          <span class="reject-document-name">{{ documentFileName }}</span>
        </t-form-item>
        <t-form-item :label="t('review.field.rejectReason')">
          <t-textarea
            v-model="rejectForm.comment"
            :placeholder="t('review.placeholder.rejectReason')"
            :autosize="{ minRows: 4, maxRows: 6 }"
            :maxlength="500"
            show-limit-number
          />
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog
      v-model:visible="pdfPreviewVisible"
      :header="pdfPreviewTitle"
      width="min(1120px, 96vw)"
      :footer="false"
      destroy-on-close
      @close="closePdfPreview"
    >
      <div class="pdf-preview-dialog-body">
        <div v-if="pdfPreviewLoading" class="empty-panel">{{ t('document.detail.empty.loadingPdf') }}</div>
        <div v-else-if="pdfPreviewError" class="empty-panel pdf-preview-error">{{ pdfPreviewError }}</div>
        <iframe
          v-else-if="pdfPreviewUrl"
          class="pdf-preview-frame"
          :src="pdfPreviewUrl"
          :title="pdfPreviewTitle"
        />
        <div v-else class="empty-panel">{{ t('document.detail.empty.noPdf') }}</div>
      </div>
    </t-dialog>

    <ZoomPreviewDialog
      v-model:visible="zoomPreviewVisible"
      :title="documentFileName"
      :version-label="viewedVersionNo ? `v${viewedVersionNo}` : '-'"
    >
      <div class="markdown-preview-stream">
        <ChatRichContent
          v-for="segment in renderedMarkdownSegments"
          :key="`zoom-${segment.id}`"
          class="review-rich-content"
          :content="segment.content"
          :image-source-resolver="resolvePreviewImageSource"
        />
        <div v-if="markdownPreviewHasMore" class="preview-load-more">
          <t-button
            size="small"
            variant="outline"
            :loading="markdownPreviewRendering"
            @click="renderNextMarkdownSegments()"
          >
            {{ t('document.detail.action.loadMorePreview') }}
          </t-button>
        </div>
      </div>
      <div v-if="structuredPreviewPages.length" class="structured-preview">
        <article v-for="page in structuredPreviewPages" :key="`zoom-${page.id}`" class="page-preview-card">
          <div class="page-preview-title">Page {{ page.page_no }}</div>
          <img
            v-if="page.page_preview_asset?.status === 'ready'"
            v-asset-lazy="page.page_preview_asset"
            class="page-preview-image"
            :src="assetBlobUrl(page.page_preview_asset) || IMAGE_PLACEHOLDER_SRC"
            :alt="`Page ${page.page_no}`"
            loading="lazy"
            decoding="async"
          />
          <div v-if="page.blocks.some((block) => block.image_asset?.status === 'ready')" class="block-image-grid">
            <img
              v-for="block in page.blocks.filter((item) => item.image_asset?.status === 'ready')"
              :key="block.id"
              v-asset-lazy="block.image_asset"
              class="block-preview-image"
              :src="assetBlobUrl(block.image_asset) || IMAGE_PLACEHOLDER_SRC"
              :alt="block.text || `Block ${block.block_index}`"
              loading="lazy"
              decoding="async"
            />
          </div>
        </article>
      </div>
    </ZoomPreviewDialog>
  </PageContainer>
</template>

<style scoped>
.review-detail-page {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  gap: 16px;
  overflow: auto;
  padding-right: 8px;
}

.detail-action-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
}

.reject-document-name {
  color: #0f172a;
  font-weight: 600;
  line-height: 1.5;
  word-break: break-word;
}

.summary-band {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
}

.summary-grid,
.summary-aside,
.main-panel {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.summary-item {
  padding: 16px 18px;
  border-right: 1px solid #eef2f7;
  border-bottom: 1px solid #eef2f7;
}

.summary-item:nth-child(4n) {
  border-right: 0;
}

.summary-item:nth-last-child(-n + 4) {
  border-bottom: 0;
}

.summary-label {
  color: #64748b;
  font-size: 12px;
}

.summary-value {
  margin-top: 6px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
}

.summary-aside {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 16px;
}

.summary-line,
.muted-text {
  color: #64748b;
  font-size: 13px;
}

.file-name-value {
  min-width: 0;
  word-break: break-word;
}

.main-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  padding: 16px;
}

.preview-tabs {
  display: flex;
  align-items: center;
  border-bottom: 1px solid #e5e7eb;
  margin-bottom: 16px;
}

.preview-tab {
  position: relative;
  padding: 12px 14px;
  color: #111827;
  font-size: 14px;
}

.preview-tab.active {
  color: #0f62fe;
  font-weight: 600;
}

.preview-tab.active::after {
  content: '';
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 3px;
  background: #0f62fe;
}

.tab-panel {
  min-height: 0;
}

.preview-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 16px;
}

.preview-toolbar-main {
  justify-content: flex-start;
  gap: 16px;
}

.preview-toolbar-actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  margin-left: auto;
}

.preview-toolbar-link {
  min-width: 0;
  height: auto;
  padding: 0;
  color: #2563eb;
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.preview-toolbar-link:hover {
  color: #1d4ed8;
}

.preview-toolbar-link.t-is-disabled,
.preview-toolbar-link[disabled] {
  color: #93c5fd;
}

.preview-content-scroll {
  min-height: 320px;
  overflow: visible;
  padding-right: 8px;
}

.review-rich-content {
  width: 100%;
  max-width: none;
  padding: 24px 28px;
  border: 0;
  border-radius: 0;
  background: #fff;
}

.markdown-preview-stream .review-rich-content {
  padding-top: 8px;
  padding-bottom: 8px;
}

.markdown-preview-stream .review-rich-content:first-child {
  padding-top: 24px;
}

.preview-load-more {
  display: flex;
  justify-content: center;
  padding: 16px 0 24px;
}

/* 审核页空间充足时完整铺开表格，单元格换行以避免内容被横向截断。 */
.review-rich-content :deep(table) {
  display: table;
  width: 100%;
  max-width: none;
  table-layout: auto;
  white-space: normal;
}

.review-rich-content :deep(th),
.review-rich-content :deep(td) {
  overflow-wrap: anywhere;
}

.structured-preview {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: none;
  margin-top: 16px;
}

.page-preview-card {
  padding: 18px;
  border: 0;
  border-radius: 0;
  background: #fff;
}

.page-preview-title {
  margin-bottom: 12px;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
}

.page-preview-image,
.block-preview-image {
  display: block;
  max-width: 100%;
  height: auto;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.block-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.empty-panel {
  display: grid;
  min-height: 96px;
  place-items: center;
  border: 1px dashed #d8dee8;
  border-radius: 8px;
  color: #64748b;
  font-size: 14px;
}

.pdf-preview-dialog-body {
  min-height: min(74vh, 780px);
}

.pdf-preview-frame {
  display: block;
  width: 100%;
  height: min(74vh, 780px);
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.pdf-preview-error {
  color: #dc2626;
}

@media (max-width: 1400px) {
  .summary-band {
    grid-template-columns: minmax(0, 1fr);
  }
}

@media (max-width: 1100px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .summary-item:nth-child(4n) {
    border-right: 1px solid #eef2f7;
  }

  .summary-item:nth-child(2n) {
    border-right: 0;
  }

  .summary-item:nth-last-child(-n + 4) {
    border-bottom: 1px solid #eef2f7;
  }

  .summary-item:nth-last-child(-n + 2) {
    border-bottom: 0;
  }
}
</style>
