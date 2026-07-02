<!--
  Review Detail Page

  负责：
  1. 展示单个审核任务详情与关联文档基础信息
  2. 提供审核通过、驳回与去构建索引入口
  3. 复用文档详情页原始内容预览交互，便于审核人员直接核验内容
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { AssignmentCheckedIcon } from 'tdesign-icons-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue';
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
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { DocumentAssetInfo, DocumentInfo, DocumentPreview, DocumentVersionInfo, ReviewTask } from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { INDEX_STATUS_TEXT, PARSE_STATUS_TEXT, isReviewTaskPending } from '@/utils/constants';
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

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const loading = ref(false);
const previewLoading = ref(false);
const pdfPreviewVisible = ref(false);
const pdfPreviewLoading = ref(false);
const pdfPreviewUrl = ref('');
const pdfPreviewTitle = ref('PDF 预览');
const pdfPreviewError = ref('');

const task = ref<ReviewTask | null>(null);
const documentInfo = ref<DocumentInfo | null>(null);
const previewData = ref<DocumentPreview | null>(null);
const versions = ref<DocumentVersionInfo[]>([]);

const assetUrlMap = reactive<Record<number, string>>({});
const assetPromiseMap = new Map<number, Promise<string>>();

const taskId = computed(() => Number(route.params.id));
const viewedVersionNo = computed(() => task.value?.display_version_no ?? task.value?.version_no ?? documentInfo.value?.version_no ?? null);
const reviewedVersion = computed(() => {
  const versionNo = viewedVersionNo.value;
  return versionNo ? versions.value.find((item) => item.version_no === versionNo) || null : null;
});
const markdownContent = computed(() => previewData.value?.markdown_content?.trim() || '');
const structuredPreviewPages = computed(() => {
  const pages = previewData.value?.pages || [];
  if (!pages.length || collectMarkdownImageSources(markdownContent.value).length > 0) return [];
  return pages.filter((page) => page.page_preview_asset || page.blocks.some((block) => block.image_asset));
});
const documentFileName = computed(() => reviewedVersion.value?.file_name || task.value?.document_file_name || documentInfo.value?.file_name || `文档 #${task.value?.document_id || '-'}`);
const documentProjectName = computed(() => documentInfo.value?.project_name || (documentInfo.value?.project_id ? `项目 #${documentInfo.value.project_id}` : '企业知识'));
const viewedFileSize = computed(() => reviewedVersion.value?.file_size ?? documentInfo.value?.file_size ?? 0);
const viewedFileType = computed(() => reviewedVersion.value?.file_type || documentInfo.value?.file_type || '');
const viewedSecurityLevel = computed(() => reviewedVersion.value?.security_level || documentInfo.value?.security_level || 'internal');
const uploaderLabel = computed(() => {
  return (
    documentInfo.value?.uploader_name ||
    documentInfo.value?.uploader_username ||
    task.value?.uploader_name ||
    task.value?.uploader_username ||
    (documentInfo.value?.upload_user_id ? `用户 #${documentInfo.value.upload_user_id}` : '') ||
    (task.value?.uploader_id ? `用户 #${task.value.uploader_id}` : '-')
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
const pdfPreviewButtonLabel = computed(() => (isPdfFile(documentFileName.value, viewedFileType.value) ? '预览原始 PDF' : '预览转换 PDF'));

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
    await Promise.allSettled((previewData.value?.markdown_image_assets || []).map((asset) => ensureAssetUrl(asset)));
    await Promise.allSettled(
      (previewData.value?.pages || []).flatMap((page) => [
        page.page_preview_asset ? ensureAssetUrl(page.page_preview_asset) : Promise.resolve(''),
        ...page.blocks
          .filter((block) => block.image_asset)
          .map((block) => ensureAssetUrl(block.image_asset)),
      ]),
    );
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
    MessagePlugin.error(error instanceof Error ? error.message : '审核详情加载失败');
  } finally {
    loading.value = false;
  }
}

async function decide(action: 'approve' | 'reject'): Promise<void> {
  if (!task.value) return;
  if (action === 'approve' && !canApproveTask.value) {
    MessagePlugin.warning('当前账号没有审核通过权限');
    return;
  }
  if (action === 'reject' && !canRejectTask.value) {
    MessagePlugin.warning('当前账号没有审核驳回权限');
    return;
  }
  task.value = action === 'approve' ? await approveReviewTask(task.value.id) : await rejectReviewTask(task.value.id);
  MessagePlugin.success('审核已处理');
}

function goBuildIndex(): void {
  router.push(withBreadcrumbContext(route, { path: '/reviews', query: { tab: 'approved' } }));
}

function taskLabel(): string {
  return '资料审核任务';
}

function taskFileLinkText(): string {
  return documentFileName.value;
}

function openReviewedDocument(): void {
  if (!task.value) return;
  router.push(withBreadcrumbContext(route, `/documents/${task.value.document_id}`));
}

function parseStatusText(status: string): string {
  return PARSE_STATUS_TEXT[status] || status || '-';
}

function parseStatusTheme(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (['success', 'parsed'].includes(status)) return 'success';
  if (['parsing', 'unparsed'].includes(status)) return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function indexStatusText(status: string): string {
  return INDEX_STATUS_TEXT[status] || status || '-';
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
    MessagePlugin.warning('无权限预览文档');
    return;
  }

  const sourceText = isPdfFile(documentFileName.value, viewedFileType.value) ? '原始 PDF' : '转换 PDF';
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
      pdfPreviewError.value = error instanceof Error ? error.message : 'PDF 预览加载失败';
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
  revokePdfPreviewUrl();
  resetAssetUrls();
});
</script>

<template>
  <PageContainer title="审核详情" subtitle="查看资料审核状态和处理结果">
    <template #actions>
      <div class="detail-action-group">
        <t-button variant="outline" @click="router.push('/reviews')">返回审核中心</t-button>
        <t-button
          v-if="showBuildIndexAction"
          v-permission="PERMISSIONS.REVIEW_BUILD_INDEX"
          theme="primary"
          @click="goBuildIndex"
        >
          <template #icon><AssignmentCheckedIcon /></template>
          去构建索引
        </t-button>
        <t-button
          v-permission="PERMISSIONS.REVIEW_APPROVE"
          theme="success"
          :disabled="!canApproveTask || !isReviewTaskPending(task?.review_status)"
          @click="decide('approve')"
        >
          审核通过
        </t-button>
        <t-button
          v-permission="PERMISSIONS.REVIEW_REJECT"
          theme="danger"
          :disabled="!canRejectTask || !isReviewTaskPending(task?.review_status)"
          @click="decide('reject')"
        >
          审核驳回
        </t-button>
      </div>
    </template>

    <div class="review-detail-page" v-loading="loading">
      <template v-if="task && documentInfo">
        <section class="summary-band">
          <div class="summary-grid">
            <div class="summary-item">
              <div class="summary-label">审核任务</div>
              <div class="summary-value">{{ taskLabel() }}</div>
            </div>
            <div class="summary-item">
              <div class="summary-label">关联文档</div>
              <div class="summary-value file-name-value">
                <t-link theme="primary" @click="openReviewedDocument">{{ taskFileLinkText() }}</t-link>
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">审核状态</div>
              <div class="summary-value">
                <StatusTag type="review" :value="task.review_status" />
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">查看版本</div>
              <div class="summary-value">{{ viewedVersionNo ? `v${viewedVersionNo}` : '-' }}</div>
            </div>
            <div class="summary-item">
              <div class="summary-label">文件大小</div>
              <div class="summary-value">{{ formatFileSize(viewedFileSize) }}</div>
            </div>
            <div class="summary-item">
              <div class="summary-label">解析状态</div>
              <div class="summary-value">
                <t-tag size="small" variant="light" :theme="parseStatusTheme(parseStatusValue)">
                  {{ parseStatusText(parseStatusValue) }}
                </t-tag>
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">索引构建状态</div>
              <div class="summary-value">
                <t-tag size="small" variant="light" :theme="indexStatusTheme(indexStatusValue)">
                  {{ indexStatusText(indexStatusValue) }}
                </t-tag>
              </div>
            </div>
            <div class="summary-item">
              <div class="summary-label">上传人员</div>
              <div class="summary-value">{{ uploaderLabel }}</div>
            </div>
          </div>

          <div class="summary-aside">
            <div class="summary-line">知识范围：{{ documentProjectName }}</div>
            <div class="summary-line">分类：{{ task.document_category_path || task.document_category_name || documentInfo.category_path || documentInfo.category_name || '-' }}</div>
            <div class="summary-line">文档密级：{{ securityLevelLabel(viewedSecurityLevel) }}</div>
            <div class="summary-line">创建时间：{{ formatDateTime(task.created_at) }}</div>
            <div class="summary-line">审核意见：{{ task.review_comment || '暂无意见' }}</div>
          </div>
        </section>

        <section class="main-panel">
          <div class="preview-tabs">
            <div class="preview-tab active">原始内容预览</div>
          </div>

          <section class="tab-panel">
            <div class="preview-toolbar preview-toolbar-main">
              <span class="muted-text">查看版本 {{ viewedVersionNo ? `v${viewedVersionNo}` : '-' }}</span>
              <div class="preview-toolbar-actions">
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
                <span class="muted-text">页数 {{ previewData?.page_count || 0 }}</span>
              </div>
            </div>

            <div class="preview-content-scroll">
              <div v-if="previewLoading" class="empty-panel">正在加载原始内容预览...</div>
              <div v-else-if="!markdownContent" class="empty-panel">当前审核版本还没有可展示的解析结果。</div>
              <template v-else>
                <ChatRichContent class="review-rich-content" :content="markdownContent" :image-source-resolver="resolvePreviewImageSource" />
                <div v-if="structuredPreviewPages.length" class="structured-preview">
                  <article v-for="page in structuredPreviewPages" :key="page.id" class="page-preview-card">
                    <div class="page-preview-title">Page {{ page.page_no }}</div>
                    <img
                      v-if="page.page_preview_asset?.status === 'ready'"
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
      v-model:visible="pdfPreviewVisible"
      :header="pdfPreviewTitle"
      width="min(1120px, 96vw)"
      :footer="false"
      destroy-on-close
      @close="closePdfPreview"
    >
      <div class="pdf-preview-dialog-body">
        <div v-if="pdfPreviewLoading" class="empty-panel">正在加载 PDF 预览...</div>
        <div v-else-if="pdfPreviewError" class="empty-panel pdf-preview-error">{{ pdfPreviewError }}</div>
        <iframe
          v-else-if="pdfPreviewUrl"
          class="pdf-preview-frame"
          :src="pdfPreviewUrl"
          :title="pdfPreviewTitle"
        />
        <div v-else class="empty-panel">暂无可预览 PDF。</div>
      </div>
    </t-dialog>
  </PageContainer>
</template>

<style scoped>
.review-detail-page {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  gap: 16px;
}

.detail-action-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
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
  max-height: calc(100vh - 430px);
  min-height: 320px;
  overflow: auto;
  padding-right: 8px;
}

.review-rich-content {
  width: 100%;
  max-width: 1040px;
  padding: 24px 28px;
  border: 0;
  border-radius: 0;
  background: #fff;
}

.structured-preview {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1040px;
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
