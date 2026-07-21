<!--
  Document Detail Page

  负责：
  1. 展示文档基础信息、索引状态和最新索引任务
  2. 提供原始内容预览、知识分块、版本历史查看
  3. 支持新版本上传、提交审核、下载和二次确认删除
-->
<script setup lang="ts">
import MarkdownIt from 'markdown-it';
import { MessagePlugin } from 'tdesign-vue-next';
import { AssignmentCheckedIcon, DownloadIcon, FileSearchIcon, PlayCircleIcon, RefreshIcon, UploadIcon } from 'tdesign-icons-vue-next';
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import type { Directive } from 'vue';

import {
  createDocumentIndexBuildTask,
  createDocumentVersion,
  deleteDocument,
  downloadDocumentAsset,
  downloadDocumentPdfPreview,
  downloadDocumentVersion,
  getDocument,
  getDocumentPreview,
  listDocumentChunks,
  listDocumentIndexTasks,
  listDocumentVersions,
  parseDocument,
  submitDocumentReview,
  updateDocumentSecurityLevel,
} from '@/api/documents';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type {
  DocumentAssetInfo,
  DocumentChunk,
  DocumentDeleteResult,
  DocumentInfo,
  DocumentPreview,
  DocumentVersionInfo,
  IndexTaskInfo,
  SecurityLevel,
} from '@/types/api';
import {
  INDEX_TASK_STATUS_TEXT,
  INDEX_TASK_TYPE_TEXT,
  PARSE_STATUS_TEXT,
} from '@/utils/constants';
import { previousBreadcrumbTarget } from '@/utils/breadcrumbContext';
import { formatDateTime, formatFileSize } from '@/utils/format';
import { confirmRebuildIndexedDocument, isIndexedIndexStatus } from '@/utils/indexBuildConfirm';
import { clampSecurityLevel, securityLevelLabel, securityLevelOptions, securityLevelTheme } from '@/utils/securityLevels';

type DetailTab = 'preview' | 'cleaning' | 'chunks' | 'versions';

const SUBMITTABLE_REVIEW_STATUSES = new Set(['draft', 'rejected']);
const VERSION_UPLOAD_ACCEPT = '.txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf';
const VERSION_UPLOAD_INPUT_ID = 'document-version-upload-input';
const IMAGE_PLACEHOLDER_SRC = 'data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==';
const LAZY_ASSET_ROOT_MARGIN = '360px 0px';
const HTML_IMAGE_SRC_PATTERN = /<img\b[^>]*\bsrc\s*=\s*(?:"([^"]+)"|'([^']+)'|([^>\s]+))/gi;
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
const SAFE_MARKDOWN_TAGS = new Set([
  'a',
  'blockquote',
  'br',
  'caption',
  'code',
  'col',
  'colgroup',
  'del',
  'div',
  'em',
  'h1',
  'h2',
  'h3',
  'h4',
  'h5',
  'h6',
  'hr',
  'img',
  'li',
  'ol',
  'p',
  'pre',
  's',
  'span',
  'strong',
  'sub',
  'sup',
  'table',
  'tbody',
  'td',
  'tfoot',
  'th',
  'thead',
  'tr',
  'ul',
]);
const SAFE_TABLE_ATTRS = new Set(['align', 'colspan', 'rowspan']);
const SAFE_COL_ATTRS = new Set(['span', 'width']);
const SAFE_STYLE_PROPERTIES = new Set(['text-align', 'vertical-align', 'width', 'height']);
const LATEX_SYMBOL_REPLACEMENTS: Array<[RegExp, string]> = [
  [/\\geqslant\b|\\geq\b|\\ge\b/g, '≥'],
  [/\\leqslant\b|\\leq\b|\\le\b/g, '≤'],
  [/\\neq\b|\\ne\b/g, '≠'],
  [/\\textgreater\b/g, '>'],
  [/\\textless\b/g, '<'],
  [/\\approx\b/g, '≈'],
  [/\\pm\b/g, '±'],
  [/\\times\b/g, '×'],
  [/\\cdot\b/g, '·'],
  [/\\div\b/g, '÷'],
  [/\\sim\b/g, '~'],
  [/\\degree\b|\\circ\b/g, '°'],
  [/\\mu\b/g, 'μ'],
  [/\\Omega\b/g, 'Ω'],
  [/\\alpha\b/g, 'α'],
  [/\\beta\b/g, 'β'],
  [/\\gamma\b/g, 'γ'],
  [/\\delta\b/g, 'δ'],
  [/\\Delta\b/g, 'Δ'],
  [/\\%/g, '%'],
  [/\\_/g, '_'],
  [/\\&/g, '&'],
  [/\\,/g, ' '],
  [/\\;/g, ' '],
  [/\\:/g, ' '],
  [/\\!/g, ''],
];
const SUBSCRIPT_DIGITS: Record<string, string> = {
  '0': '₀',
  '1': '₁',
  '2': '₂',
  '3': '₃',
  '4': '₄',
  '5': '₅',
  '6': '₆',
  '7': '₇',
  '8': '₈',
  '9': '₉',
  '+': '₊',
  '-': '₋',
};
const SUPERSCRIPT_DIGITS: Record<string, string> = {
  '0': '⁰',
  '1': '¹',
  '2': '²',
  '3': '³',
  '4': '⁴',
  '5': '⁵',
  '6': '⁶',
  '7': '⁷',
  '8': '⁸',
  '9': '⁹',
  '+': '⁺',
  '-': '⁻',
};

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const activeTab = ref<DetailTab>('preview');
const loading = ref(false);
const versionUploading = ref(false);
const previewLoading = ref(false);
const parsing = ref(false);
const buildingIndex = ref(false);
const deleting = ref(false);
const pdfPreviewVisible = ref(false);
const pdfPreviewLoading = ref(false);
const pdfPreviewUrl = ref('');
const pdfPreviewTitle = ref('PDF 预览');
const pdfPreviewError = ref('');
const securityDialogVisible = ref(false);
const securitySaving = ref(false);
const versionDialogVisible = ref(false);

const documentInfo = ref<DocumentInfo | null>(null);
const previewData = ref<DocumentPreview | null>(null);
const chunks = ref<DocumentChunk[]>([]);
const versions = ref<DocumentVersionInfo[]>([]);
const indexTasks = ref<IndexTaskInfo[]>([]);
const selectedVersionFile = ref<File | null>(null);
const selectedVersionNo = ref<number | null>(null);

const versionForm = reactive({
  change_summary: '',
});

const VERSION_STATUS_TEXT: Record<string, string> = {
  draft: '草稿',
  current: '当前版本',
  historical: '历史版本',
  pending_review: '待审核',
  approved: '已通过',
  rejected: '已驳回',
  inactive: '已停用',
};

const securityForm = reactive({
  security_level: clampSecurityLevel('internal', authStore.maxSecurityLevel),
});

const assetUrlMap = reactive<Record<number, string>>({});
const assetPromiseMap = new Map<number, Promise<string>>();
const previewCache = new Map<string, DocumentPreview>();
const chunkCache = new Map<string, DocumentChunk[]>();
const previewPromiseCache = new Map<string, Promise<DocumentPreview>>();
const chunkPromiseCache = new Map<string, Promise<DocumentChunk[]>>();
const observedAssetImages = new Set<HTMLImageElement>();
let assetImageObserver: IntersectionObserver | null = null;
const markdownRenderer = new MarkdownIt({
  html: true,
  linkify: true,
  breaks: true,
});

const documentId = computed(() => Number(route.params.id));
const isProjectDocument = computed(() => documentInfo.value?.knowledge_type === 'project');
const viewDocumentPermission = computed(() => (isProjectDocument.value ? PERMISSIONS.PROJECT_VIEW : PERMISSIONS.KNOWLEDGE_VIEW));
const previewDocumentPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_DOCUMENT_PREVIEW : PERMISSIONS.KNOWLEDGE_VIEW,
);
const downloadDocumentPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_DOCUMENT_DOWNLOAD : PERMISSIONS.KNOWLEDGE_DOWNLOAD,
);
const submitReviewPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_SUBMIT_REVIEW : PERMISSIONS.KNOWLEDGE_SUBMIT_REVIEW,
);
const deleteDocumentPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_DOCUMENT_DELETE : PERMISSIONS.KNOWLEDGE_DELETE,
);
const uploadVersionPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_DOCUMENT_VERSION_CREATE : PERMISSIONS.KNOWLEDGE_UPLOAD,
);
const editSecurityPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_DOCUMENT_SECURITY_UPDATE : PERMISSIONS.KNOWLEDGE_EDIT,
);
const parseDocumentPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_DOCUMENT_RETRY_PARSE : PERMISSIONS.REVIEW_BUILD_INDEX,
);
const buildIndexPermission = computed(() =>
  isProjectDocument.value ? PERMISSIONS.PROJECT_DOCUMENT_RETRY_INDEX : PERMISSIONS.REVIEW_BUILD_INDEX,
);
const canPreviewDocument = computed(() => authStore.hasActionPermission(previewDocumentPermission.value));
const canDownloadDocument = computed(() => authStore.hasActionPermission(downloadDocumentPermission.value));
const canUploadVersion = computed(() => authStore.hasActionPermission(uploadVersionPermission.value));
const canDeleteDocument = computed(() => authStore.hasActionPermission(deleteDocumentPermission.value));
const canParseDocument = computed(() => authStore.hasActionPermission(parseDocumentPermission.value));
const canBuildDocumentIndex = computed(() => authStore.hasActionPermission(buildIndexPermission.value));
const canEditDocumentSecurity = computed(() => authStore.hasActionPermission(editSecurityPermission.value));
const backPath = computed(() => {
  /**
   * 优先沿访问来源返回；直接打开文档时再根据知识范围返回上级页面。
   */
  const sourceTarget = previousBreadcrumbTarget(route);
  if (sourceTarget) return sourceTarget;
  if (documentInfo.value?.knowledge_type === 'project' && documentInfo.value.project_id) {
    return `/projects/${documentInfo.value.project_id}/documents`;
  }
  return '/knowledge';
});
const markdownContent = computed(() => previewData.value?.markdown_content?.trim() || '');
const renderedMarkdownHtml = computed(() => renderMarkdown(markdownContent.value));
const latestIndexTask = computed(() => indexTasks.value[0] || null);
const viewedVersionNo = computed(() => selectedVersionNo.value || documentInfo.value?.version_no || null);
const viewedVersion = computed(() => {
  const versionNo = viewedVersionNo.value;
  return versionNo ? versions.value.find((version) => version.version_no === versionNo) || null : null;
});
const viewedFileName = computed(() => viewedVersion.value?.file_name || documentInfo.value?.file_name || '-');
const viewedFileType = computed(() => viewedVersion.value?.file_type || documentInfo.value?.file_type || '');
const viewedFileSize = computed(() => viewedVersion.value?.file_size ?? documentInfo.value?.file_size ?? 0);
const isViewedPdfFile = computed(() => isPdfFile(viewedFileName.value, viewedFileType.value));
const pdfPreviewButtonLabel = computed(() => (isViewedPdfFile.value ? '预览原始 PDF' : '预览转换 PDF'));
const viewedReviewStatus = computed(() => viewedVersion.value?.review_status || documentInfo.value?.review_status || 'draft');
const viewedReviewComment = computed(() => (viewedVersion.value?.review_comment || documentInfo.value?.review_comment || '').trim());
const showRejectReason = computed(() => viewedReviewStatus.value === 'rejected' && viewedReviewComment.value.length > 0);
const viewedParseStatus = computed(() => viewedVersion.value?.parse_status || documentInfo.value?.parse_status || 'unparsed');
const viewedIndexStatus = computed(() => viewedVersion.value?.index_status || documentInfo.value?.index_status || 'not_indexed');
const documentSecurityLevel = computed<SecurityLevel>(() => (documentInfo.value?.security_level || 'internal') as SecurityLevel);
const documentProjectName = computed(() => documentInfo.value?.project_name || (documentInfo.value?.project_id ? `项目 #${documentInfo.value.project_id}` : '企业知识'));
const canSubmitReview = computed(() => {
  return SUBMITTABLE_REVIEW_STATUSES.has(viewedReviewStatus.value);
});
const activeBuildTask = computed(() =>
  indexTasks.value.find(
    (task) =>
      task.version_no === viewedVersionNo.value &&
      task.task_type === 'full_build' &&
      ['pending', 'running'].includes(task.status),
  ) || null,
);
const canParseVersion = computed(() =>
  canParseDocument.value &&
  Boolean(documentInfo.value) &&
  viewedParseStatus.value !== 'parsing' &&
  !parsing.value,
);
const canBuildIndex = computed(() =>
  canBuildDocumentIndex.value &&
  Boolean(documentInfo.value) &&
  viewedReviewStatus.value === 'approved' &&
  !activeBuildTask.value &&
  !['parsing', 'indexing'].includes(viewedIndexStatus.value) &&
  !buildingIndex.value,
);
const viewedVersionLabel = computed(() => (viewedVersionNo.value ? `v${viewedVersionNo.value}` : '-'));
const structuredPreviewPages = computed(() => {
  const pages = previewData.value?.pages || [];
  if (!pages.length || collectMarkdownImageSources(markdownContent.value).length > 0) return [];
  return pages.filter((page) => page.page_preview_asset || page.blocks.some((block) => block.image_asset));
});

markdownRenderer.renderer.rules.image = (tokens, idx) => {
  const token = tokens[idx];
  const rawSrc = token.attrGet('src') || '';
  const alt = token.content || token.attrGet('alt') || '';
  const title = token.attrGet('title') || '';
  if (!rawSrc.trim()) {
    return escapeHtml(alt || basenameFromPath(rawSrc));
  }
  return [
    '<img',
    ` src="${escapeHtml(rawSrc.trim())}"`,
    ` alt="${escapeHtml(alt)}"`,
    title ? ` title="${escapeHtml(title)}"` : '',
    ' loading="lazy" decoding="async" />',
  ].join('');
};

function resetAssetUrls(): void {
  /**
   * 释放当前页面已创建的 Blob URL，避免页面停留过久导致浏览器内存上涨。
   */
  resetAssetImageObservers();
  for (const url of Object.values(assetUrlMap)) {
    URL.revokeObjectURL(url);
  }
  for (const key of Object.keys(assetUrlMap)) {
    delete assetUrlMap[Number(key)];
  }
  assetPromiseMap.clear();
}

function resetAssetImageObservers(): void {
  assetImageObserver?.disconnect();
  assetImageObserver = null;
  observedAssetImages.clear();
}

function cacheKeyForVersion(versionNo: number | null = selectedVersionNo.value): string {
  return `${documentId.value}:${versionNo || 'current'}`;
}

function invalidateDetailCache(): void {
  previewCache.clear();
  chunkCache.clear();
  previewPromiseCache.clear();
  chunkPromiseCache.clear();
  resetAssetUrls();
}

function collectPreviewAssets(): DocumentAssetInfo[] {
  const preview = previewData.value;
  if (!preview) return [];
  const assets: DocumentAssetInfo[] = [...preview.markdown_image_assets];
  for (const page of preview.pages) {
    if (page.page_preview_asset) assets.push(page.page_preview_asset);
    for (const block of page.blocks) {
      if (block.image_asset) assets.push(block.image_asset);
    }
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

function getAssetImageObserver(): IntersectionObserver | null {
  if (typeof window === 'undefined' || !('IntersectionObserver' in window)) return null;
  if (!assetImageObserver) {
    assetImageObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const element = entry.target as HTMLImageElement;
          const assetId = Number(element.dataset.documentAssetId);
          const asset = Number.isFinite(assetId) ? findPreviewAssetById(assetId) : null;
          unobserveAssetImage(element);
          if (asset) {
            void loadAssetImageElement(element, asset);
          }
        }
      },
      { rootMargin: LAZY_ASSET_ROOT_MARGIN },
    );
  }
  return assetImageObserver;
}

async function loadAssetImageElement(element: HTMLImageElement, asset: DocumentAssetInfo): Promise<void> {
  if (element.dataset.documentAssetLoading === String(asset.id)) return;
  const cachedUrl = assetUrlMap[asset.id];
  if (cachedUrl) {
    element.src = cachedUrl;
    element.classList.remove('asset-image-loading');
    return;
  }

  element.dataset.documentAssetLoading = String(asset.id);
  element.classList.add('asset-image-loading');
  try {
    const url = await ensureAssetUrl(asset);
    if (url && element.dataset.documentAssetId === String(asset.id)) {
      element.src = url;
      element.classList.remove('asset-image-loading');
    }
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : `资产 #${asset.id} 预览加载失败`);
  } finally {
    if (element.dataset.documentAssetLoading === String(asset.id)) {
      delete element.dataset.documentAssetLoading;
    }
  }
}

function bindAssetImageElement(element: HTMLImageElement, asset: DocumentAssetInfo | null | undefined): void {
  unobserveAssetImage(element);
  if (!asset || asset.status !== 'ready') return;

  element.dataset.documentAssetId = String(asset.id);
  const cachedUrl = assetUrlMap[asset.id];
  if (cachedUrl) {
    element.src = cachedUrl;
    element.classList.remove('asset-image-loading');
    return;
  }

  element.src = IMAGE_PLACEHOLDER_SRC;
  element.classList.add('asset-image-loading');
  const observer = getAssetImageObserver();
  if (!observer) {
    void loadAssetImageElement(element, asset);
    return;
  }
  observer.observe(element);
  observedAssetImages.add(element);
}

function bindLazyMarkdownImages(): void {
  const elements = window.document.querySelectorAll<HTMLImageElement>('img[data-document-asset-id]');
  for (const element of Array.from(elements)) {
    const assetId = Number(element.dataset.documentAssetId);
    const asset = Number.isFinite(assetId) ? findPreviewAssetById(assetId) : null;
    bindAssetImageElement(element, asset);
  }
}

const vAssetLazy: Directive<HTMLImageElement, DocumentAssetInfo | null | undefined> = {
  mounted(element, binding) {
    bindAssetImageElement(element, binding.value);
  },
  updated(element, binding) {
    if (binding.value?.id !== binding.oldValue?.id) {
      bindAssetImageElement(element, binding.value);
    } else if (binding.value) {
      bindAssetImageElement(element, binding.value);
    }
  },
  unmounted(element) {
    unobserveAssetImage(element);
  },
};

function revokePdfPreviewUrl(): void {
  if (!pdfPreviewUrl.value) return;
  URL.revokeObjectURL(pdfPreviewUrl.value);
  pdfPreviewUrl.value = '';
}

function triggerBlobDownload(blob: Blob, fileName: string): void {
  /**
   * 统一触发浏览器下载，避免页面上散落重复的 a 标签逻辑。
   */
  const url = URL.createObjectURL(blob);
  const anchor = window.document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  window.document.body.appendChild(anchor);
  anchor.click();
  window.document.body.removeChild(anchor);
  URL.revokeObjectURL(url);
}

function escapeHtml(value: string): string {
  /**
   * 对 Markdown 文本进行 HTML 转义，避免 MinerU 原始结果中的异常内容进入 DOM。
   */
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function looksLikeLatexMath(expression: string): boolean {
  return /\\[a-zA-Z%_&]|[_^][{\w+-]|\\[,:;!]|[{}]/.test(expression);
}

function toScriptText(value: string, dictionary: Record<string, string>): string {
  return value
    .replace(/[{}]/g, '')
    .split('')
    .map((char) => dictionary[char] || char)
    .join('');
}

function unwrapLatexTextCommands(value: string): string {
  return value
    .replace(/\\(?:mathrm|mathbf|text|operatorname)\s*\{([^{}]*)\}/g, '$1')
    .replace(/\\(?:rm|bf|it)\s+/g, '');
}

function renderLatexToPlainText(expression: string): string {
  /**
   * 将 MinerU 表格中常见的 LaTeX 片段转成可读文本，避免展示 $\leqslant$ 这类原始命令。
   */
  let normalized = unwrapLatexTextCommands(expression.trim());
  for (const [pattern, replacement] of LATEX_SYMBOL_REPLACEMENTS) {
    normalized = normalized.replace(pattern, replacement);
  }

  normalized = normalized
    .replace(/([A-Za-z)])\s*\{\s*([0-9+-]+)\s*\}/g, (_match, prefix: string, value: string) =>
      `${prefix}${toScriptText(value, SUBSCRIPT_DIGITS)}`,
    )
    .replace(/_\{([^{}]+)\}/g, (_match, value: string) => toScriptText(value, SUBSCRIPT_DIGITS))
    .replace(/_([0-9+-])/g, (_match, value: string) => toScriptText(value, SUBSCRIPT_DIGITS))
    .replace(/\^\{([^{}]+)\}/g, (_match, value: string) => toScriptText(value, SUPERSCRIPT_DIGITS))
    .replace(/\^([0-9+-])/g, (_match, value: string) => toScriptText(value, SUPERSCRIPT_DIGITS))
    .replace(/\\[a-zA-Z]+\s*/g, '')
    .replace(/[{}]/g, '')
    .replace(/\s+%/g, '%')
    .replace(/\s{2,}/g, ' ')
    .trim();

  return normalized;
}

function normalizeLatexText(value: string): string {
  return value
    .replace(/\$\$([\s\S]+?)\$\$/g, (match, expression: string) =>
      looksLikeLatexMath(expression) ? renderLatexToPlainText(expression) : match,
    )
    .replace(/\\\[([\s\S]+?)\\\]/g, (match, expression: string) =>
      looksLikeLatexMath(expression) ? renderLatexToPlainText(expression) : match,
    )
    .replace(/\\\(([\s\S]+?)\\\)/g, (match, expression: string) =>
      looksLikeLatexMath(expression) ? renderLatexToPlainText(expression) : match,
    )
    .replace(/\$([^$\n]+?)\$/g, (match, expression: string) =>
      looksLikeLatexMath(expression) ? renderLatexToPlainText(expression) : match,
    );
}

function isInsideCodeElement(node: Node): boolean {
  return Boolean(node.parentElement?.closest('code, pre'));
}

function normalizeAssetKey(value: string): string {
  /**
   * 统一图片路径格式，兼容 MinerU 的 images/xxx 相对路径和 Windows 路径。
   */
  return value
    .trim()
    .replace(/^['"]|['"]$/g, '')
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .toLowerCase();
}

function basenameFromPath(value: string): string {
  /**
   * 提取路径文件名，用于 Markdown 图片引用和资产文件名的兜底匹配。
   */
  const normalized = normalizeAssetKey(value);
  return normalized.split('/').filter(Boolean).pop() || normalized;
}

function isPdfFile(fileName: string, fileType?: string | null): boolean {
  const normalizedType = (fileType || '').toLowerCase().replace(/^\./, '');
  return normalizedType === 'pdf' || fileName.toLowerCase().endsWith('.pdf');
}

function parseAssetMetadata(asset: DocumentAssetInfo): Record<string, unknown> {
  /**
   * 解析资产元数据；异常元数据不影响整篇 Markdown 预览。
   */
  if (!asset.metadata_json) return {};
  try {
    const parsed = JSON.parse(asset.metadata_json);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function collectAssetLookupKeys(asset: DocumentAssetInfo): string[] {
  /**
   * 收集图片资产可用于匹配 Markdown 引用的候选键。
   */
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
  /**
   * 根据 Markdown 图片路径查找后端受控资产，避免前端直接读取共享卷或 MinIO。
   */
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
  /**
   * 判断 Markdown 图片是否可以直接交给浏览器加载；受控派生资产需要走带鉴权的懒加载下载。
   */
  return /^(https?:|data:|blob:)/i.test(src.trim());
}

function decodeAllowedHtmlEntities(value: string): string {
  /**
   * 只为表格和图片标签恢复常见 HTML 实体，避免 MinerU 把结构标签作为纯文本展示。
   */
  return value
    .replace(/&(amp;)?quot;/gi, '"')
    .replace(/&(amp;)?#39;/gi, "'")
    .replace(/&(amp;)?amp;/gi, '&');
}

function restoreAllowedEncodedHtml(markdown: string): string {
  /**
   * MinerU 偶尔会输出 &lt;td&gt; 这类实体化表格标签，这里只恢复白名单标签。
   */
  return markdown.replace(
    /&(amp;)?lt;(\/?)(table|thead|tbody|tfoot|tr|td|th|br|colgroup|col|caption|img)\b([\s\S]*?)&(amp;)?gt;/gi,
    (_match, _ltAmp: string, slash: string, tag: string, attrs: string) =>
      `<${slash}${tag.toLowerCase()}${decodeAllowedHtmlEntities(attrs)}>`,
  );
}

function buildOrphanTableRow(line: string): string {
  /**
   * 修复只有连续 <td>/<th>、缺少 <tr>/<table> 的 MinerU 表格行。
   */
  const matches = Array.from(line.matchAll(/<(td|th)\b([^>]*)>/gi));
  if (!matches.length) return line;

  const cells = matches.map((match, index) => {
    const tag = match[1].toLowerCase();
    const attrs = match[2] || '';
    const contentStart = (match.index || 0) + match[0].length;
    const contentEnd = index + 1 < matches.length ? matches[index + 1].index || line.length : line.length;
    const content = line.slice(contentStart, contentEnd).replace(/<\/(?:td|th)>\s*$/i, '').trim();
    return `<${tag}${attrs}>${content}</${tag}>`;
  });

  return `<tr>${cells.join('')}</tr>`;
}

function normalizeOrphanTableRows(markdown: string): string {
  /**
   * 将连续的孤立单元格行合并成一个表格，提升历史解析产物的可读性。
   */
  const output: string[] = [];
  const tableRows: string[] = [];
  let inCodeBlock = false;
  let rawTableDepth = 0;

  const flushTableRows = () => {
    if (!tableRows.length) return;
    output.push(`<table><tbody>${tableRows.join('\n')}</tbody></table>`);
    tableRows.length = 0;
  };

  for (const line of markdown.replace(/\r\n/g, '\n').split('\n')) {
    const trimmedLine = line.trim();
    if (trimmedLine.startsWith('```')) {
      flushTableRows();
      output.push(line);
      inCodeBlock = !inCodeBlock;
      continue;
    }

    if (!inCodeBlock && rawTableDepth === 0 && /^<(td|th)\b/i.test(trimmedLine) && !/^<tr\b/i.test(trimmedLine)) {
      tableRows.push(buildOrphanTableRow(trimmedLine));
      continue;
    }

    flushTableRows();
    output.push(line);
    if (!inCodeBlock) {
      const openingTables = (trimmedLine.match(/<table\b/gi) || []).length;
      const closingTables = (trimmedLine.match(/<\/table>/gi) || []).length;
      rawTableDepth = Math.max(0, rawTableDepth + openingTables - closingTables);
    }
  }

  flushTableRows();
  return output.join('\n');
}

function preprocessMarkdown(markdown: string): string {
  return normalizeOrphanTableRows(restoreAllowedEncodedHtml(markdown));
}

function sanitizeStyle(styleValue: string): string {
  const safeDeclarations = styleValue
    .split(';')
    .map((item) => item.trim())
    .filter(Boolean)
    .filter((item) => {
      const [property, value] = item.split(':').map((part) => part?.trim() || '');
      return SAFE_STYLE_PROPERTIES.has(property.toLowerCase()) && !/url\s*\(|expression\s*\(/i.test(value);
    });
  return safeDeclarations.join('; ');
}

function sanitizeElementAttributes(element: HTMLElement, tagName: string): void {
  for (const attribute of Array.from(element.attributes)) {
    const attrName = attribute.name.toLowerCase();
    const attrValue = attribute.value.trim();
    let keepAttribute = false;

    if (tagName === 'a' && attrName === 'href') {
      keepAttribute = /^(https?:|mailto:|tel:|#|\/)/i.test(attrValue);
    } else if (tagName === 'a' && attrName === 'title') {
      keepAttribute = true;
    } else if (tagName === 'img' && ['src', 'alt', 'title', 'loading', 'decoding'].includes(attrName)) {
      keepAttribute = true;
    } else if (['td', 'th'].includes(tagName) && SAFE_TABLE_ATTRS.has(attrName)) {
      keepAttribute = attrName === 'align' || /^\d{1,3}$/.test(attrValue);
    } else if (['table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th', 'col', 'colgroup'].includes(tagName) && attrName === 'style') {
      const safeStyle = sanitizeStyle(attrValue);
      if (safeStyle) {
        element.setAttribute('style', safeStyle);
        keepAttribute = true;
      }
    } else if (['col', 'colgroup'].includes(tagName) && SAFE_COL_ATTRS.has(attrName)) {
      keepAttribute = /^[\w.% -]{1,20}$/.test(attrValue);
    }

    if (!keepAttribute) {
      element.removeAttribute(attribute.name);
    }
  }
}

function rewriteImageElement(element: HTMLElement): void {
  const rawSrc = element.getAttribute('src') || '';
  const externalUrl = isExternalImageSource(rawSrc) ? rawSrc.trim() : '';
  const asset = externalUrl ? null : findMarkdownImageAsset(rawSrc);
  if (!externalUrl && !asset) {
    element.replaceWith(window.document.createTextNode(element.getAttribute('alt') || basenameFromPath(rawSrc)));
    return;
  }

  element.setAttribute('src', externalUrl || IMAGE_PLACEHOLDER_SRC);
  if (asset) {
    element.setAttribute('data-document-asset-id', String(asset.id));
  }
  element.setAttribute('loading', 'lazy');
  element.setAttribute('decoding', 'async');
  element.className = `markdown-image${asset ? ' asset-image-loading' : ''}`;
}

function sanitizeNode(node: Node): void {
  if (node.nodeType === Node.TEXT_NODE) {
    if (!isInsideCodeElement(node)) {
      node.textContent = normalizeLatexText(node.textContent || '');
    }
    return;
  }
  if (node.nodeType !== Node.ELEMENT_NODE) {
    node.parentNode?.removeChild(node);
    return;
  }

  const element = node as HTMLElement;
  const tagName = element.tagName.toLowerCase();
  if (!SAFE_MARKDOWN_TAGS.has(tagName)) {
    const parent = element.parentNode;
    if (!parent) return;
    const movedChildren = Array.from(element.childNodes);
    while (element.firstChild) {
      parent.insertBefore(element.firstChild, element);
    }
    parent.removeChild(element);
    for (const child of movedChildren) {
      sanitizeNode(child);
    }
    return;
  }

  sanitizeElementAttributes(element, tagName);
  if (tagName === 'a') {
    element.setAttribute('target', '_blank');
    element.setAttribute('rel', 'noopener noreferrer');
  }
  if (tagName === 'img') {
    rewriteImageElement(element);
  }

  for (const child of Array.from(element.childNodes)) {
    sanitizeNode(child);
  }
}

function sanitizeMarkdownHtml(html: string): string {
  const template = window.document.createElement('template');
  template.innerHTML = html;
  for (const child of Array.from(template.content.childNodes)) {
    sanitizeNode(child);
  }
  return template.innerHTML;
}

function collectMarkdownImageSources(markdown: string): string[] {
  if (!markdown.trim()) return [];
  const normalizedMarkdown = preprocessMarkdown(markdown);
  const sources = new Set<string>();
  const tokens = markdownRenderer.parse(normalizedMarkdown, {});

  const visitTokens = (items: typeof tokens) => {
    for (const token of items) {
      if (token.type === 'image') {
        const src = token.attrGet('src');
        if (src) sources.add(src);
      }
      if (token.children?.length) {
        visitTokens(token.children);
      }
    }
  };

  visitTokens(tokens);
  for (const match of normalizedMarkdown.matchAll(HTML_IMAGE_SRC_PATTERN)) {
    const src = match[1] || match[2] || match[3];
    if (src) sources.add(src);
  }
  return Array.from(sources);
}

function renderMarkdown(markdown: string): string {
  /**
   * 使用标准 Markdown 渲染器处理表格、列表、代码块，再通过白名单清洗 HTML。
   */
  if (!markdown.trim()) return '';
  return sanitizeMarkdownHtml(markdownRenderer.render(preprocessMarkdown(markdown)));
}

async function ensureAssetUrl(asset: DocumentAssetInfo | null | undefined): Promise<string> {
  /**
   * 懒加载单个预览资产，保证图片只在真正需要展示时才下载。
   */
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

async function bindRenderedAssetImages(): Promise<void> {
  await nextTick();
  bindLazyMarkdownImages();
}

function assetBlobUrl(asset: DocumentAssetInfo | null | undefined): string {
  if (!asset) return '';
  return assetUrlMap[asset.id] || '';
}

async function openDocumentPdfPreview(version?: DocumentVersionInfo): Promise<void> {
  /**
   * 在弹窗中预览当前版本 PDF：PDF 原文件直接展示，非 PDF 展示后端转换后的 PDF。
   */
  if (!documentInfo.value || pdfPreviewLoading.value) return;
  if (!canPreviewDocument.value) {
    MessagePlugin.warning('无权限预览文档');
    return;
  }

  const versionNo = version?.version_no ?? viewedVersionNo.value;
  const fileName = version?.file_name || viewedFileName.value;
  const fileType = version?.file_type || viewedFileType.value;
  const sourceText = isPdfFile(fileName, fileType) ? '原始 PDF' : '转换 PDF';

  revokePdfPreviewUrl();
  pdfPreviewError.value = '';
  pdfPreviewTitle.value = `${fileName} · ${sourceText}`;
  pdfPreviewVisible.value = true;
  pdfPreviewLoading.value = true;

  try {
    const blob = await downloadDocumentPdfPreview(documentInfo.value.id, versionNo);
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

async function loadPreview(): Promise<void> {
  /**
   * 加载当前版本完整 Markdown 预览；图片资产只在进入可视区域时下载。
   */
  previewLoading.value = true;
  let loaded = false;
  try {
    const cacheKey = cacheKeyForVersion();
    let preview = previewCache.get(cacheKey);
    if (!preview) {
      let previewPromise = previewPromiseCache.get(cacheKey);
      if (!previewPromise) {
        previewPromise = getDocumentPreview(documentId.value, selectedVersionNo.value).finally(() => {
          previewPromiseCache.delete(cacheKey);
        });
        previewPromiseCache.set(cacheKey, previewPromise);
      }
      preview = await previewPromise;
      previewCache.set(cacheKey, preview);
    }
    previewData.value = preview;
    loaded = true;
  } finally {
    previewLoading.value = false;
  }
  if (loaded) {
    await bindRenderedAssetImages();
  }
}

async function loadChunks(): Promise<void> {
  const cacheKey = cacheKeyForVersion();
  let chunkItems = chunkCache.get(cacheKey);
  if (!chunkItems) {
    let chunkPromise = chunkPromiseCache.get(cacheKey);
    if (!chunkPromise) {
      chunkPromise = listDocumentChunks(documentId.value, selectedVersionNo.value).finally(() => {
        chunkPromiseCache.delete(cacheKey);
      });
      chunkPromiseCache.set(cacheKey, chunkPromise);
    }
    chunkItems = await chunkPromise;
    chunkCache.set(cacheKey, chunkItems);
  }
  chunks.value = chunkItems;
  await bindRenderedAssetImages();
}

async function loadData(force = false): Promise<void> {
  /**
   * 统一加载文档详情页所需的基础数据，避免多处刷新时出现字段不同步。
   */
  loading.value = true;
  try {
    if (force) {
      invalidateDetailCache();
    }
    const [documentResult, versionResult, taskResult] = await Promise.all([
      getDocument(documentId.value),
      listDocumentVersions(documentId.value),
      listDocumentIndexTasks(documentId.value),
    ]);
    documentInfo.value = documentResult;
    versions.value = versionResult;
    indexTasks.value = taskResult;
    if (activeTab.value === 'preview' || activeTab.value === 'cleaning') {
      await loadPreview();
    } else if (activeTab.value === 'chunks') {
      await loadChunks();
    }
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '文档详情加载失败');
  } finally {
    loading.value = false;
  }
}

async function refreshActiveTab(): Promise<void> {
  /**
   * 切换页签时按需刷新，避免预览图片被频繁重复请求。
   */
  if (activeTab.value === 'preview' || activeTab.value === 'cleaning') {
    await loadPreview();
    return;
  }
  if (activeTab.value === 'chunks') {
    await loadChunks();
    return;
  }
  if (!versions.value.length) {
    versions.value = await listDocumentVersions(documentId.value);
  }
}

function handleTabChange(value: unknown): void {
  /**
   * 统一处理页签切换，避免在模板中直接写复杂赋值表达式。
   */
  activeTab.value = value as DetailTab;
}

function handleVersionFileChange(event: Event): void {
  /**
   * 读取新版本文件，等待用户确认上传。
   */
  const input = event.target as HTMLInputElement;
  selectedVersionFile.value = input.files?.[0] || null;
}

function canSubmitVersion(version: DocumentVersionInfo): boolean {
  return authStore.hasActionPermission(submitReviewPermission.value) && SUBMITTABLE_REVIEW_STATUSES.has(version.review_status);
}

async function submitReview(versionNo: number | null = viewedVersionNo.value): Promise<void> {
  /**
   * 将当前查看版本送审；新版本送审前不会影响旧版本检索。
   */
  if (!documentInfo.value) return;
  if (!authStore.hasActionPermission(submitReviewPermission.value)) {
    MessagePlugin.warning('无权限提交审核');
    return;
  }
  await submitDocumentReview(documentInfo.value.id, '提交审核', versionNo);
  MessagePlugin.success('已提交审核');
  await loadData(true);
}

async function runParse(versionNo: number | null = viewedVersionNo.value): Promise<void> {
  /**
   * 审核前允许解析，供审核人员查看预览、页级内容和知识分块。
   */
  if (!documentInfo.value || parsing.value) return;
  if (!canParseDocument.value) {
    MessagePlugin.warning('无权限执行解析');
    return;
  }
  parsing.value = true;
  try {
    await parseDocument(documentInfo.value.id, versionNo);
    MessagePlugin.success('解析完成');
    activeTab.value = 'preview';
    await loadData(true);
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '解析失败');
  } finally {
    parsing.value = false;
  }
}

async function createIndexBuild(versionNo: number | null = viewedVersionNo.value): Promise<void> {
  /**
   * 审核通过后创建后台任务；任务会按需先解析再发布索引。
   */
  if (!documentInfo.value || buildingIndex.value) return;
  if (!canBuildDocumentIndex.value) {
    MessagePlugin.warning('无权限构建索引');
    return;
  }
  if (isIndexedIndexStatus(viewedIndexStatus.value)) {
    const confirmed = await confirmRebuildIndexedDocument(viewedFileName.value);
    if (!confirmed) return;
  }
  buildingIndex.value = true;
  try {
    const task = await createDocumentIndexBuildTask(documentInfo.value.id, versionNo);
    indexTasks.value = [task, ...indexTasks.value.filter((item) => item.id !== task.id)];
    MessagePlugin.success('解析与索引构建任务已创建');
    await loadData(true);
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '索引任务创建失败');
  } finally {
    buildingIndex.value = false;
  }
}

async function uploadNewVersion(): Promise<void> {
  /**
   * 上传新版本原始文件，并刷新当前详情页的版本、状态和预览。
   */
  if (!documentInfo.value) return;
  if (!canUploadVersion.value) {
    MessagePlugin.warning('无权限上传新版本');
    return;
  }
  if (!selectedVersionFile.value) {
    MessagePlugin.warning('请先选择新版本文件');
    return;
  }

  versionUploading.value = true;
  try {
    const version = await createDocumentVersion(documentInfo.value.id, selectedVersionFile.value, {
      change_summary: versionForm.change_summary.trim() || undefined,
    });
    MessagePlugin.success('新版本上传成功');
    selectedVersionNo.value = version.version_no;
    activeTab.value = 'preview';
    selectedVersionFile.value = null;
    versionForm.change_summary = '';
    versionDialogVisible.value = false;
    await loadData(true);
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '新版本上传失败');
  } finally {
    versionUploading.value = false;
  }
}

function closeVersionDialog(): void {
  versionDialogVisible.value = false;
  selectedVersionFile.value = null;
  versionForm.change_summary = '';
  const input = document.getElementById(VERSION_UPLOAD_INPUT_ID) as HTMLInputElement | null;
  if (input) {
    input.value = '';
  }
}

async function downloadVersion(version: DocumentVersionInfo): Promise<void> {
  /**
   * 下载指定版本的原始文件，便于与解析预览结果进行对照。
   */
  if (!canDownloadDocument.value) {
    MessagePlugin.warning('无权限下载文档');
    return;
  }
  const blob = await downloadDocumentVersion(version.document_id, version.version_no);
  triggerBlobDownload(blob, version.file_name);
}

async function viewVersion(version: DocumentVersionInfo): Promise<void> {
  if (!authStore.hasActionPermission(viewDocumentPermission.value)) {
    MessagePlugin.warning('无权限查看文档版本');
    return;
  }
  selectedVersionNo.value = version.version_no;
  activeTab.value = 'preview';
  chunks.value = [];
  await loadPreview();
}

async function viewCurrentVersion(): Promise<void> {
  selectedVersionNo.value = null;
  await refreshActiveTab();
}

function openSecurityDialog(): void {
  /**
   * 文档密级是文档及其版本、分块、页索引的统一上限，前端只允许在文档维度修改。
   */
  if (!documentInfo.value) return;
  if (!canEditDocumentSecurity.value) {
    MessagePlugin.warning('无权限修改文档密级');
    return;
  }
  securityForm.security_level = documentInfo.value.security_level;
  securityDialogVisible.value = true;
}

async function confirmSecurityDialog(): Promise<void> {
  if (!documentInfo.value || securitySaving.value) return;
  if (!canEditDocumentSecurity.value) {
    MessagePlugin.warning('无权限修改文档密级');
    return;
  }
  securitySaving.value = true;
  try {
    await updateDocumentSecurityLevel(documentInfo.value.id, securityForm.security_level);
    MessagePlugin.success('文档密级已更新，相关索引状态已同步');
    securityDialogVisible.value = false;
    await loadData(true);
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '文档密级更新失败');
  } finally {
    securitySaving.value = false;
  }
}

function taskStatusText(task: IndexTaskInfo | null): string {
  /**
   * 将索引任务状态统一映射成前端显示文案。
   */
  if (!task) return '-';
  return INDEX_TASK_STATUS_TEXT[task.status] || task.status;
}

function taskTypeText(taskType: string): string {
  /**
   * 将后端任务类型转换为业务人员可理解的中文描述。
   */
  return INDEX_TASK_TYPE_TEXT[taskType] || taskType;
}

function parseStatusText(status: string): string {
  return PARSE_STATUS_TEXT[status] || status;
}

function parseStatusTheme(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (['success', 'parsed'].includes(status)) return 'success';
  if (['parsing', 'unparsed'].includes(status)) return 'warning';
  if (['failed'].includes(status)) return 'danger';
  return 'default';
}

function versionStatusText(version: DocumentVersionInfo): string {
  const rawStatus = version.version_status || (version.is_current ? 'current' : '');
  return VERSION_STATUS_TEXT[rawStatus] || rawStatus || '-';
}

function openVersionDialog(): void {
  if (!documentInfo.value) return;
  if (!canUploadVersion.value) {
    MessagePlugin.warning('无权限上传新版本');
    return;
  }
  versionForm.change_summary = '';
  selectedVersionFile.value = null;
  versionDialogVisible.value = true;
}

function buildDeleteMessage(result: DocumentDeleteResult): string {
  /**
   * 组织删除完成反馈，让用户知道哪些检索数据已经被清理。
   */
  const messages = [
    '文档已删除',
    `Chunk ${result.document_chunks} 条`,
    `页 ${result.document_pages} 条`,
    `图谱 ${result.graph_entities} 条`,
    `引用 ${result.chat_citations} 条`,
    `检索审计 ${result.retrieval_traces} 条`,
  ];
  if (result.external_cleanup_queued) {
    messages.push(
      `外部资源后台清理中：向量 ${result.pending_vector_count || 0} 条、文件 ${result.pending_file_count || 0} 个、对象 ${result.pending_asset_object_count || 0} 个`,
    );
  }
  return messages.join('，');
}

async function removeDocument(): Promise<void> {
  /**
   * 在前端二次确认后删除文档，并清理全部检索相关数据。
   */
  if (!documentInfo.value || deleting.value) return;
  const confirmed = window.confirm(`确认删除文档“${documentInfo.value.file_name}”吗？删除后将立即清理数据库检索数据，外部文件和向量会在后台回收。`);
  if (!confirmed) return;

  deleting.value = true;
  try {
    const result = await deleteDocument(documentInfo.value.id);
    MessagePlugin.success(buildDeleteMessage(result));
    await router.replace(backPath.value);
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '文档删除失败');
  } finally {
    deleting.value = false;
  }
}

watch(activeTab, () => {
  void refreshActiveTab();
});

watch(pdfPreviewVisible, (visible) => {
  if (!visible) {
    pdfPreviewError.value = '';
    revokePdfPreviewUrl();
  }
});

onMounted(() => {
  void loadData();
});

onBeforeUnmount(() => {
  resetAssetUrls();
  revokePdfPreviewUrl();
});
</script>

<template>
  <PageContainer :title="documentInfo?.file_name || '文档详情'" subtitle="查看当前版本原始解析内容、知识分块、版本历史和索引状态">
    <template #actions>
      <div class="detail-action-group">
        <t-button
          variant="outline"
          :disabled="!documentInfo"
          @click="router.push(backPath)"
        >
          返回
        </t-button>
        <t-button
          v-permission="editSecurityPermission"
          v-if="canEditDocumentSecurity"
          variant="outline"
          :disabled="!documentInfo"
          @click="openSecurityDialog"
        >
          修改密级
        </t-button>
        <t-button v-permission="submitReviewPermission" v-if="canSubmitReview" theme="primary" @click="submitReview()">提交审核</t-button>
        <t-button
          v-permission="parseDocumentPermission"
          theme="primary"
          variant="outline"
          :disabled="!canParseVersion"
          :loading="parsing"
          @click="runParse()"
        >
          <template #icon><FileSearchIcon /></template>
          {{ viewedParseStatus === 'success' ? '重新解析' : '执行解析' }}
        </t-button>
        <t-button
          v-permission="buildIndexPermission"
          theme="primary"
          variant="outline"
          :disabled="!canBuildIndex"
          :loading="buildingIndex"
          @click="createIndexBuild()"
        >
          <template #icon><PlayCircleIcon /></template>
          解析并构建索引
        </t-button>
        <t-button
          v-permission="uploadVersionPermission"
          theme="primary"
          :disabled="!canUploadVersion"
          @click="openVersionDialog"
        >
          <template #icon><UploadIcon /></template>
          版本更新
        </t-button>
        <t-button v-permission="deleteDocumentPermission" v-if="canDeleteDocument" theme="danger" variant="outline" :loading="deleting" @click="removeDocument">删除文档</t-button>
      </div>
    </template>

    <div class="detail-page" v-loading="loading">
      <section class="summary-band">
        <div class="summary-grid">
          <div class="summary-item">
            <div class="summary-label">文件名</div>
            <div class="summary-value file-name-value">
              <t-link theme="primary" :disabled="!documentInfo || !canPreviewDocument" @click="openDocumentPdfPreview()">{{ viewedFileName }}</t-link>
            </div>
          </div>
          <div class="summary-item">
            <div class="summary-label">查看版本</div>
            <div class="summary-value">{{ viewedVersionLabel }}</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">文件大小</div>
            <div class="summary-value">{{ formatFileSize(viewedFileSize) }}</div>
          </div>
          <div class="summary-item">
            <div class="summary-label">审核状态</div>
            <div class="summary-value"><StatusTag type="review" :value="viewedReviewStatus" /></div>
          </div>
          <div class="summary-item">
            <div class="summary-label">解析状态</div>
            <div class="summary-value"><t-tag size="small" variant="light" :theme="parseStatusTheme(viewedParseStatus)">{{ parseStatusText(viewedParseStatus) }}</t-tag></div>
          </div>
          <div class="summary-item">
            <div class="summary-label">索引状态</div>
            <div class="summary-value"><StatusTag type="index" :value="viewedIndexStatus" /></div>
          </div>
          <div class="summary-item">
            <div class="summary-label">文档密级</div>
            <div class="summary-value">
              <t-tag size="small" variant="light" :theme="securityLevelTheme(documentSecurityLevel)">
                {{ securityLevelLabel(documentSecurityLevel) }}
              </t-tag>
            </div>
          </div>
          <div class="summary-item">
            <div class="summary-label">上传人</div>
            <div class="summary-value">{{ documentInfo?.uploader_name || documentInfo?.uploader_username || documentInfo?.upload_user_id || '-' }}</div>
          </div>
        </div>

        <div class="summary-aside">
          <div class="summary-line">知识范围：{{ documentProjectName }}</div>
          <div class="summary-line">分类：{{ documentInfo?.category_path || documentInfo?.category_name || '-' }}</div>
          <div class="summary-line">最新任务：{{ taskStatusText(latestIndexTask) }}</div>
          <div class="summary-line">更新时间：{{ formatDateTime(documentInfo?.updated_at) }}</div>
          <div v-if="showRejectReason" class="reject-reason-panel">
            <div class="reject-reason-title">驳回原因</div>
            <div class="reject-reason-content">{{ viewedReviewComment }}</div>
          </div>
          <div v-if="documentInfo?.build_error" class="error-text">构建错误：{{ documentInfo.build_error }}</div>
        </div>
      </section>

      <section class="workspace-grid">
        <div class="main-panel">
          <t-tabs :value="activeTab" @change="handleTabChange">
            <t-tab-panel value="preview" label="原始内容预览" />
            <t-tab-panel value="cleaning" label="解析清洗" />
            <t-tab-panel value="chunks" label="知识分块" />
            <t-tab-panel value="versions" label="版本历史" />
          </t-tabs>

          <section v-if="activeTab === 'preview'" class="tab-panel">
            <div class="preview-toolbar preview-toolbar-main">
              <span class="muted-text">查看版本 {{ viewedVersionLabel }}</span>
              <div class="preview-toolbar-actions">
                <t-button
                  v-if="selectedVersionNo"
                  size="small"
                  variant="text"
                  class="preview-toolbar-link"
                  @click="viewCurrentVersion"
                >
                  回到当前版本
                </t-button>
                <t-button
                  v-if="documentInfo && canPreviewDocument"
                  size="small"
                  variant="text"
                  class="preview-toolbar-link"
                  :loading="pdfPreviewLoading"
                  @click="openDocumentPdfPreview()"
                >
                  {{ pdfPreviewButtonLabel }}
                </t-button>
                <span class="muted-text">页数 {{ previewData?.page_count || 0 }}</span>
              </div>
            </div>

            <div v-if="previewLoading" class="empty-panel">正在加载原始内容预览...</div>
            <div v-else-if="!markdownContent" class="empty-panel">当前版本还没有可展示的解析结果。</div>
            <template v-else>
              <article class="markdown-preview" v-html="renderedMarkdownHtml" />
              <div v-if="structuredPreviewPages.length" class="structured-preview">
                <article v-for="page in structuredPreviewPages" :key="page.id" class="page-preview-card">
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
            </template>
          </section>

          <section v-else-if="activeTab === 'cleaning'" class="tab-panel">
            <div class="preview-toolbar">
              <span class="muted-text">查看版本 {{ viewedVersionLabel }}</span>
              <span class="muted-text">页数 {{ previewData?.page_count || 0 }}</span>
              <t-button v-if="selectedVersionNo" size="small" variant="text" class="preview-toolbar-link" @click="viewCurrentVersion">回到当前版本</t-button>
            </div>

            <div v-if="previewLoading" class="empty-panel">正在加载解析清洗结果...</div>
            <div v-else-if="!previewData?.pages.length" class="empty-panel">当前版本还没有解析清洗结果。</div>
            <div v-else class="cleaning-page-list">
              <article v-for="page in previewData.pages" :key="`clean-${page.id}`" class="cleaning-page">
                <div class="cleaning-page-header">
                  <span>Page {{ page.page_no }}</span>
                  <span v-if="page.page_title" class="muted-text">{{ page.page_title }}</span>
                </div>
                <div class="cleaning-columns">
                  <section class="cleaning-column">
                    <div class="cleaning-column-title">原始解析内容</div>
                    <pre>{{ page.page_text || '-' }}</pre>
                  </section>
                  <section class="cleaning-column">
                    <div class="cleaning-column-title">清洗后内容</div>
                    <pre>{{ page.clean_content || '-' }}</pre>
                  </section>
                  <section class="cleaning-column">
                    <div class="cleaning-column-title">被过滤内容</div>
                    <pre>{{ page.filtered_content || '-' }}</pre>
                  </section>
                </div>
                <details v-if="page.blocks.some((block) => block.filter_status === 'filtered')" class="filtered-blocks">
                  <summary>被过滤块 {{ page.blocks.filter((block) => block.filter_status === 'filtered').length }}</summary>
                  <pre
                    v-for="block in page.blocks.filter((item) => item.filter_status === 'filtered')"
                    :key="block.id"
                  >{{ block.text || block.filter_reason || '-' }}</pre>
                </details>
              </article>
            </div>
          </section>

          <section v-else-if="activeTab === 'chunks'" class="tab-panel">
            <div class="preview-toolbar">
              <span class="muted-text">查看版本 {{ viewedVersionLabel }}</span>
              <t-button v-if="selectedVersionNo" size="small" variant="text" class="preview-toolbar-link" @click="viewCurrentVersion">回到当前版本</t-button>
            </div>
            <div v-if="!chunks.length" class="empty-panel">当前版本还没有知识分块。</div>
            <div v-else class="table-scroll">
              <table class="plain-table chunk-table">
                <thead>
                  <tr>
                    <th>序号</th>
                    <th>页码</th>
                    <th>密级</th>
                    <th>章节</th>
                    <th>内容</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="chunk in chunks" :key="chunk.id">
                    <td>{{ chunk.chunk_index }}</td>
                    <td>{{ chunk.page_number || '-' }}</td>
                    <td>
                      <t-tag size="small" variant="light" :theme="securityLevelTheme(chunk.security_level)">
                        {{ securityLevelLabel(chunk.security_level) }}
                      </t-tag>
                    </td>
                    <td>{{ chunk.section_title || '-' }}</td>
                    <td class="content-cell">
                      <div class="chunk-markdown" v-html="renderMarkdown(chunk.content)" />
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>

          <section v-else class="tab-panel">
            <div v-if="!versions.length" class="empty-panel">当前文档还没有版本记录。</div>
            <div v-else class="table-scroll">
              <table class="plain-table version-table">
                <thead>
                  <tr>
                    <th>版本</th>
                    <th>文件名</th>
                    <th>密级</th>
                    <th>版本状态</th>
                    <th>解析状态</th>
                    <th>状态</th>
                    <th>变更说明</th>
                    <th>创建时间</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="version in versions" :key="version.id">
                    <td>v{{ version.version_no }}</td>
                    <td><t-link theme="primary" :disabled="!canPreviewDocument" @click="openDocumentPdfPreview(version)">{{ version.file_name }}</t-link></td>
                    <td>
                      <t-tag size="small" variant="light" :theme="securityLevelTheme(version.security_level)">
                        {{ securityLevelLabel(version.security_level) }}
                      </t-tag>
                    </td>
                    <td>{{ versionStatusText(version) }}</td>
                    <td><t-tag size="small" variant="light" :theme="parseStatusTheme(version.parse_status || '')">{{ parseStatusText(version.parse_status || '') }}</t-tag></td>
                    <td>
                      <div class="status-inline">
                        <StatusTag type="review" :value="version.review_status" />
                        <StatusTag type="index" :value="version.index_status" />
                      </div>
                    </td>
                    <td>{{ version.change_summary || '-' }}</td>
                    <td>{{ formatDateTime(version.created_at) }}</td>
                    <td>
                      <div class="row-actions">
                        <TableActionButton
                          v-if="canSubmitVersion(version)"
                          label="提交审核"
                          :permission="submitReviewPermission"
                          theme="primary"
                          @click="submitReview(version.version_no)"
                        >
                          <AssignmentCheckedIcon />
                        </TableActionButton>
                        <TableActionButton label="查看" :permission="viewDocumentPermission" @click="viewVersion(version)">
                          <FileSearchIcon />
                        </TableActionButton>
                        <TableActionButton label="下载" :permission="downloadDocumentPermission" @click="downloadVersion(version)">
                          <DownloadIcon />
                        </TableActionButton>
                      </div>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <aside class="side-panel">
          <section class="tool-panel">
            <div class="tool-header">
              <div class="tool-title">索引任务</div>
              <t-button class="task-refresh-button" variant="text" size="small" @click="loadData(true)">
                <template #icon><RefreshIcon /></template>
              </t-button>
            </div>
            <div v-if="!indexTasks.length" class="muted-text">暂无索引任务</div>
            <div v-else class="task-list">
              <article v-for="task in indexTasks.slice(0, 5)" :key="task.id" class="task-item">
                <div class="task-header">
                  <div class="task-title">
                    <strong>{{ taskTypeText(task.task_type) }}</strong>
                  </div>
                  <span class="task-status">{{ taskStatusText(task) }}</span>
                </div>
                <div class="task-meta">
                  <span>进度 {{ task.progress }}%</span>
                  <span>更新时间 {{ formatDateTime(task.updated_at) }}</span>
                </div>
                <div v-if="task.error_message" class="error-text">{{ task.error_message }}</div>
              </article>
            </div>
          </section>
        </aside>
      </section>

      <t-dialog
        v-model:visible="versionDialogVisible"
        header="版本更新"
        width="620px"
        :confirm-loading="versionUploading"
        destroy-on-close
        @confirm="uploadNewVersion"
        @close="closeVersionDialog"
      >
        <t-form label-align="top">
          <t-form-item label="新版本文件">
            <div class="file-picker-row">
              <input
                :id="VERSION_UPLOAD_INPUT_ID"
                class="file-input"
                type="file"
                :accept="VERSION_UPLOAD_ACCEPT"
                @change="handleVersionFileChange"
              />
              <label class="file-select-button" :for="VERSION_UPLOAD_INPUT_ID">
                <UploadIcon />
                <span>选择文件</span>
              </label>
              <span class="file-name" :class="{ empty: !selectedVersionFile }">{{ selectedVersionFile?.name || '未选择文件' }}</span>
            </div>
          </t-form-item>
          <t-form-item label="变更说明">
            <t-textarea v-model="versionForm.change_summary" :autosize="{ minRows: 3, maxRows: 5 }" />
          </t-form-item>
          <div class="dialog-hint">上传后会生成新版本，并保持当前版本历史可回溯。</div>
        </t-form>
      </t-dialog>

      <t-dialog
        v-model:visible="securityDialogVisible"
        header="修改文档密级"
        width="480px"
        :confirm-loading="securitySaving"
        @confirm="confirmSecurityDialog"
      >
        <t-form :data="securityForm" label-align="top">
          <t-form-item label="文档密级">
            <t-select v-model="securityForm.security_level">
              <t-option
                v-for="item in securityLevelOptions(authStore.maxSecurityLevel, securityForm.security_level)"
                :key="item.value"
                :value="item.value"
                :label="item.label"
                :disabled="item.disabled"
              />
            </t-select>
          </t-form-item>
          <div class="dialog-hint">修改后会同步当前文档的版本、分块和页索引；已发布索引需要重新构建后生效。</div>
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
    </div>
  </PageContainer>
</template>

<style scoped>
.detail-page {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  gap: 16px;
  overflow: hidden;
}

.summary-band {
  display: grid;
  flex: 0 0 auto;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
}

.summary-grid,
.summary-aside,
.main-panel,
.side-panel,
.tool-panel {
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

.detail-action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
  justify-content: flex-end;
}

.file-name-value {
  min-width: 0;
  word-break: break-word;
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

.error-text {
  color: #dc2626;
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

.reject-reason-panel {
  padding: 10px 12px;
  border: 1px solid #fecaca;
  border-radius: 6px;
  background: #fef2f2;
}

.reject-reason-title {
  margin-bottom: 6px;
  color: #b91c1c;
  font-size: 13px;
  font-weight: 700;
}

.reject-reason-content {
  color: #7f1d1d;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.workspace-grid {
  display: grid;
  flex: 1;
  min-height: 0;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  overflow: hidden;
}

.main-panel {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  padding: 16px;
}

.tab-panel {
  flex: 1;
  min-height: 0;
  margin-top: 16px;
  overflow: auto;
}

.main-panel :deep(.t-tabs) {
  flex: 0 0 auto;
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

.markdown-preview {
  width: 100%;
  max-width: 1040px;
  padding: 24px 28px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  color: #1f2937;
  font-size: 14px;
  line-height: 1.75;
  overflow-x: auto;
}

.markdown-preview :deep(h1),
.markdown-preview :deep(h2),
.markdown-preview :deep(h3),
.markdown-preview :deep(h4),
.markdown-preview :deep(h5),
.markdown-preview :deep(h6) {
  margin: 22px 0 12px;
  color: #0f172a;
  font-weight: 700;
  letter-spacing: 0;
}

.markdown-preview :deep(h1) {
  font-size: 24px;
}

.markdown-preview :deep(h2) {
  font-size: 20px;
}

.markdown-preview :deep(h3) {
  font-size: 17px;
}

.markdown-preview :deep(p),
.markdown-preview :deep(blockquote),
.markdown-preview :deep(ul),
.markdown-preview :deep(ol),
.markdown-preview :deep(pre),
.markdown-preview :deep(table) {
  margin: 0 0 14px;
}

.markdown-preview :deep(table) {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}

.markdown-preview :deep(th),
.markdown-preview :deep(td) {
  padding: 8px 10px;
  border: 1px solid #cbd5e1;
  vertical-align: top;
}

.markdown-preview :deep(th) {
  background: #f8fafc;
  color: #0f172a;
  font-weight: 600;
}

.markdown-preview :deep(blockquote) {
  padding: 10px 14px;
  border-left: 3px solid #1683e6;
  background: #f8fafc;
  color: #475569;
}

.markdown-preview :deep(code) {
  padding: 2px 5px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 13px;
}

.markdown-preview :deep(pre) {
  padding: 14px;
  border-radius: 8px;
  background: #0f172a;
  overflow-x: auto;
}

.markdown-preview :deep(pre code) {
  padding: 0;
  background: transparent;
  color: #e2e8f0;
}

.markdown-preview :deep(a) {
  color: #0f62fe;
  text-decoration: none;
}

.markdown-preview :deep(a:hover) {
  text-decoration: underline;
}

.markdown-preview :deep(.markdown-image) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 12px 0 18px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.markdown-preview :deep(.markdown-image.asset-image-loading) {
  width: 100%;
  min-height: 180px;
  object-fit: contain;
  background: #f8fafc;
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
  border: 1px solid #e5e7eb;
  border-radius: 8px;
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

.page-preview-image.asset-image-loading {
  width: 100%;
  min-height: 360px;
  object-fit: contain;
  background: #f8fafc;
}

.block-preview-image.asset-image-loading {
  width: 100%;
  min-height: 160px;
  object-fit: contain;
  background: #f8fafc;
}

.block-image-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.cleaning-page-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.cleaning-page {
  padding: 16px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.cleaning-page-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
}

.cleaning-columns {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.cleaning-column {
  min-width: 0;
}

.cleaning-column-title {
  margin-bottom: 8px;
  color: #475569;
  font-size: 12px;
  font-weight: 600;
}

.cleaning-column pre,
.filtered-blocks pre {
  min-height: 160px;
  max-height: 420px;
  margin: 0;
  padding: 12px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #f8fafc;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  line-height: 1.6;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
}

.filtered-blocks {
  margin-top: 12px;
  color: #475569;
  font-size: 13px;
}

.filtered-blocks summary {
  cursor: pointer;
  font-weight: 600;
}

.filtered-blocks pre {
  min-height: 0;
  max-height: 180px;
  margin-top: 8px;
}

.tool-title {
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
}

.tool-panel {
  position: relative;
}

.tool-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.task-refresh-button {
  margin-right: -6px;
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

.dialog-readonly-line {
  min-height: 32px;
  color: #334155;
  font-size: 13px;
  line-height: 32px;
  word-break: break-word;
}

.dialog-hint {
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
}

.chunk-table .content-cell {
  max-width: 680px;
  white-space: normal;
  word-break: break-word;
}

.chunk-markdown {
  color: #1f2937;
  font-size: 13px;
  line-height: 1.65;
}

.chunk-markdown :deep(p),
.chunk-markdown :deep(blockquote),
.chunk-markdown :deep(ul),
.chunk-markdown :deep(ol),
.chunk-markdown :deep(pre),
.chunk-markdown :deep(table) {
  margin: 0 0 10px;
}

.chunk-markdown :deep(p:last-child),
.chunk-markdown :deep(table:last-child) {
  margin-bottom: 0;
}

.chunk-markdown :deep(table) {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}

.chunk-markdown :deep(th),
.chunk-markdown :deep(td) {
  padding: 6px 8px;
  border: 1px solid #cbd5e1;
  vertical-align: top;
}

.chunk-markdown :deep(th) {
  background: #f8fafc;
  color: #0f172a;
  font-weight: 600;
}

.chunk-markdown :deep(code) {
  padding: 2px 4px;
  border-radius: 4px;
  background: #f1f5f9;
  color: #0f172a;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
}

.chunk-markdown :deep(pre) {
  padding: 10px;
  border-radius: 6px;
  background: #0f172a;
  overflow-x: auto;
}

.chunk-markdown :deep(pre code) {
  padding: 0;
  background: transparent;
  color: #e2e8f0;
}

.chunk-markdown :deep(.markdown-image) {
  display: block;
  max-width: 100%;
  height: auto;
  margin: 8px 0;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

@media (max-width: 1180px) {
  .cleaning-columns {
    grid-template-columns: 1fr;
  }
}

.status-inline {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.side-panel {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 16px;
  overflow: auto;
}

.tool-panel {
  padding: 16px;
}

.tool-field {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 14px;
}

.tool-field label {
  color: #475569;
  font-size: 13px;
  font-weight: 500;
}

.status-detail-list,
.tool-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 14px;
}

.status-detail-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.tool-action-button {
  height: 34px;
  border-radius: 6px;
  font-weight: 600;
}

.tool-action-button.secondary {
  border-color: #d8e3f0;
  background: #fff;
  color: #334155;
}

.tool-action-button.secondary:hover {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}

.tool-action-button.primary {
  box-shadow: none;
}

.tool-action-button.ghost {
  color: #334155;
}

.tool-action-button.ghost:hover {
  background: #f1f5f9;
  color: #1d4ed8;
}

.tool-action-button:disabled {
  border-color: #e5e7eb;
  background: #f8fafc;
  color: #94a3b8;
}

.file-picker-row {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
}

.file-input {
  position: absolute;
  width: 1px;
  height: 1px;
  opacity: 0;
  pointer-events: none;
}

.file-select-button {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 6px;
  height: 32px;
  padding: 0 12px;
  border: 1px solid #d8e3f0;
  border-radius: 6px;
  background: #fff;
  color: #334155;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
}

.file-select-button:hover {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}

.file-select-button svg {
  width: 14px;
  height: 14px;
}

.file-name {
  min-width: 0;
  overflow: hidden;
  flex: 1;
  color: #475569;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-name.empty {
  color: #94a3b8;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-top: 12px;
}

.task-item {
  padding: 12px;
  border: 1px solid #eef2f7;
  border-radius: 8px;
  background: #fff;
}

.task-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.task-title {
  min-width: 0;
}

.task-title strong {
  display: block;
  overflow: hidden;
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-status {
  flex: 0 0 auto;
  color: #0f172a;
  font-size: 13px;
  font-weight: 600;
}

.task-meta {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-top: 8px;
  color: #64748b;
  font-size: 12px;
}

.task-meta span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

@media (max-width: 1180px) {
  .summary-band,
  .workspace-grid {
    grid-template-columns: 1fr;
  }
}
</style>
