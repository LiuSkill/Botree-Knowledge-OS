<!--
  Project Document Management Page

  负责：
  1. 按项目目录管理项目资料
  2. 提供资料上传、目录新建、列表筛选与分页
  3. 保持项目资料管理页与系统表格页面的统一视觉
-->
<script setup lang="ts">
import {
  AddIcon,
  AssignmentCheckedIcon,
  BrowseIcon,
  ChevronDownSIcon,
  ChevronRightSIcon,
  CloudUploadIcon,
  DeleteIcon,
  EditIcon,
  PlayCircleIcon,
  RefreshIcon,
  SearchIcon,
} from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, nextTick, onMounted, reactive, ref } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';

import { createDocumentIndexBuildTask, submitDocumentReview } from '@/api/documents';
import {
  createProjectDirectory,
  deleteProjectDirectory,
  getProject,
  listProjectDirectories,
  listProjectDocumentsPage,
  updateProjectDirectory,
  uploadProjectDocument,
} from '@/api/projects';
import PageContainer from '@/components/PageContainer.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { DocumentInfo, KnowledgeCategory, PageResult, ProjectInfo, SecurityLevel } from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { buildCategoryOptions, findCategory } from '@/utils/categories';
import {
  indexStatusOptions as buildIndexStatusOptions,
  indexStatusText as resolveIndexStatusText,
  parseStatusOptions as buildParseStatusOptions,
  parseStatusText as resolveParseStatusText,
} from '@/utils/constants';
import { formatDateTime, formatFileSize } from '@/utils/format';
import { confirmRebuildIndexedDocument, isIndexedIndexStatus } from '@/utils/indexBuildConfirm';
import { clampSecurityLevel, securityLevelLabel, securityLevelOptions, securityLevelTheme } from '@/utils/securityLevels';

interface DirectoryRow {
  id: number | null;
  key: string;
  name: string;
  count: number;
  level: number;
  enabled: boolean;
  children: KnowledgeCategory[];
}

interface PaginationInfo {
  current: number;
  pageSize: number;
}

type CategoryDialogMode = 'create' | 'edit';

const PAGE_SIZE_OPTIONS = [10, 20, 50];
const ALL_DIRECTORY_KEY = 'all';
const SUBMITTABLE_REVIEW_STATUSES = new Set(['draft', 'rejected']);
const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const { t } = useI18n();

const categories = ref<KnowledgeCategory[]>([]);
const documents = ref<DocumentInfo[]>([]);
const documentTotal = ref(0);
const directoryDocumentTotal = ref(0);
const project = ref<ProjectInfo | null>(null);
const activeDirectoryId = ref<number | null>(null);
const expandedDirectoryKeys = ref<string[]>([ALL_DIRECTORY_KEY]);
const loading = ref(false);
const uploading = ref(false);
const currentPage = ref(1);
const pageSize = ref(10);
const uploadDialogVisible = ref(false);
const selectedUploadFiles = ref<File[]>([]);
const uploadInputRef = ref<HTMLInputElement | null>(null);
const categoryDialogVisible = ref(false);
const categoryDialogMode = ref<CategoryDialogMode>('create');
const editingCategoryId = ref<number | null>(null);
const reviewSubmittingId = ref<number | null>(null);
const indexBuildingId = ref<number | null>(null);
const pendingDeleteDirectory = ref<KnowledgeCategory | null>(null);
const deleteDirectoryDialogVisible = ref(false);
const deletingDirectory = ref(false);
const directoryPanelRef = ref<HTMLElement | null>(null);
const directoryPanelHighlighted = ref(false);

const filters = reactive({
  keyword: '',
  document_status: '',
  parse_status: '',
  index_status: '',
  security_level: '' as SecurityLevel | '',
});

const uploadForm = reactive({
  directory_id: null as number | null,
  security_level: clampSecurityLevel('internal', authStore.maxSecurityLevel),
});

const categoryForm = reactive({
  parent_id: null as number | null,
  name: '',
  code: '',
  description: '',
  sort_order: 0,
  enabled: true,
  default_security_level: clampSecurityLevel('internal', authStore.maxSecurityLevel),
});

const projectId = computed(() => Number(route.params.id));
const projectTitle = computed(() => project.value?.project_name || project.value?.name || t('document.detail.projectFallback', { id: projectId.value }));
const categoryOptions = computed(() => buildCategoryOptions(categories.value));
const parseStatusOptions = computed(() => buildParseStatusOptions());
const indexStatusOptions = computed(() => buildIndexStatusOptions());
const documentStatusOptions = computed(() => [
  { label: t('project.detail.document.statusPublished'), value: 'published' },
  { label: t('project.detail.document.statusPendingReview'), value: 'pending_review' },
]);
const canViewDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_VIEW));
const canUploadDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_UPLOAD));
const canCreateDirectories = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DIRECTORY_CREATE));
const canEditDirectories = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DIRECTORY_EDIT));
const canDeleteDirectories = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DIRECTORY_DELETE));
const canSubmitDocumentReview = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_SUBMIT_REVIEW));
const canBuildDocumentIndex = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_RETRY_INDEX));

const documentColumns = computed(() => [
  { colKey: 'document_name', title: t('document.detail.field.fileName'), width: 280, ellipsis: true, fixed: 'left' },
  { colKey: 'directory', title: t('document.detail.field.directory'), width: 140, ellipsis: true },
  { colKey: 'security_level', title: t('document.detail.field.securityLevel'), width: 90, align: 'center' },
  { colKey: 'version', title: t('document.detail.field.version'), width: 80, align: 'center' },
  { colKey: 'file_size', title: t('document.detail.field.fileSize'), width: 100, align: 'center' },
  { colKey: 'review_status', title: t('document.detail.field.reviewStatus'), width: 110, align: 'center' },
  { colKey: 'parse_status', title: t('document.detail.field.parseStatus'), width: 110, align: 'center' },
  { colKey: 'index_status', title: t('document.detail.field.indexStatus'), width: 130, align: 'center' },
  { colKey: 'uploader', title: t('document.detail.field.uploader'), width: 110, ellipsis: true },
  { colKey: 'created_at', title: t('document.detail.field.uploadedAt'), width: 170, ellipsis: true },
  { colKey: 'operation', title: t('document.detail.field.operation'), width: 172, align: 'center', fixed: 'right' },
]);

const directoryRows = computed<DirectoryRow[]>(() => {
  const rows: DirectoryRow[] = [
    {
      id: null,
      key: ALL_DIRECTORY_KEY,
      name: t('project.detail.management.allDocuments'),
      count: directoryDocumentTotal.value,
      level: 0,
      enabled: true,
      children: categories.value,
    },
  ];

  if (!isDirectoryExpanded(ALL_DIRECTORY_KEY)) return rows;

  const walk = (items: KnowledgeCategory[], level: number): void => {
    for (const category of items) {
      rows.push({
        id: category.id,
        key: directoryKey(category.id),
        name: category.name,
        count: category.total_document_count,
        level,
        enabled: category.enabled,
        children: category.children || [],
      });
      if (isDirectoryExpanded(directoryKey(category.id))) {
        walk(category.children || [], level + 1);
      }
    }
  };

  walk(categories.value, 1);
  return rows;
});

const categoryById = computed(() => {
  const map = new Map<number, KnowledgeCategory>();
  const walk = (items: KnowledgeCategory[]): void => {
    items.forEach((item) => {
      map.set(item.id, item);
      walk(item.children || []);
    });
  };
  walk(categories.value);
  return map;
});

const activeDirectory = computed(() => {
  return activeDirectoryId.value ? findCategory(categories.value, activeDirectoryId.value) : undefined;
});

async function loadData(): Promise<void> {
  if (!canViewDocuments.value) return;
  loading.value = true;
  try {
    const [projectResult, directoryResult, documentResult] = await Promise.allSettled([
      getProject(projectId.value),
      listProjectDirectories(projectId.value, directoryFilterParams()),
      listProjectDocumentsPage(projectId.value, documentQueryParams()),
    ]);

    if (projectResult.status === 'fulfilled') {
      project.value = projectResult.value;
    } else {
      project.value = null;
      MessagePlugin.warning(projectResult.reason instanceof Error ? projectResult.reason.message : t('project.detail.message.loadFailed'));
    }

    if (directoryResult.status === 'fulfilled') {
      applyDirectoryTree(directoryResult.value);
    } else {
      categories.value = [];
      MessagePlugin.warning(directoryResult.reason instanceof Error ? directoryResult.reason.message : t('project.detail.message.directoryLoadFailed'));
    }

    if (documentResult.status === 'fulfilled') {
      applyDocumentPage(documentResult.value);
    } else {
      documents.value = [];
      documentTotal.value = 0;
      MessagePlugin.error(documentResult.reason instanceof Error ? documentResult.reason.message : t('project.detail.message.documentsLoadFailed'));
    }
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('project.detail.message.documentsLoadFailed'));
  } finally {
    loading.value = false;
  }
}

async function loadDocuments(): Promise<void> {
  if (!canViewDocuments.value) return;
  loading.value = true;
  try {
    applyDocumentPage(await listProjectDocumentsPage(projectId.value, documentQueryParams()));
  } finally {
    loading.value = false;
  }
}

async function loadDocumentsAndDirectories(): Promise<void> {
  if (!canViewDocuments.value) return;
  loading.value = true;
  try {
    const [documentResult, directoryResult] = await Promise.all([
      listProjectDocumentsPage(projectId.value, documentQueryParams()),
      listProjectDirectories(projectId.value, directoryFilterParams()),
    ]);
    applyDocumentPage(documentResult);
    applyDirectoryTree(directoryResult);
  } finally {
    loading.value = false;
  }
}

function documentQueryParams() {
  return {
    page: currentPage.value,
    page_size: pageSize.value,
    keyword: filters.keyword.trim() || undefined,
    directory_id: activeDirectoryId.value,
    status: filters.document_status || undefined,
    security_level: filters.security_level || undefined,
    parse_status: filters.parse_status || undefined,
    index_status: filters.index_status || undefined,
  };
}

function directoryFilterParams() {
  return {
    keyword: filters.keyword.trim() || undefined,
    status: filters.document_status || undefined,
    security_level: filters.security_level || undefined,
    parse_status: filters.parse_status || undefined,
    index_status: filters.index_status || undefined,
  };
}

function applyDocumentPage(result: PageResult<DocumentInfo>): void {
  documents.value = result.items;
  documentTotal.value = result.total;
  currentPage.value = result.page;
  pageSize.value = result.page_size;
}

function syncExpandedDirectories(items: KnowledgeCategory[]): void {
  const rootKeys = items.map((item) => directoryKey(item.id));
  expandedDirectoryKeys.value = Array.from(new Set([ALL_DIRECTORY_KEY, ...expandedDirectoryKeys.value, ...rootKeys]));
}

function applyDirectoryTree(tree: KnowledgeCategory[]): void {
  categories.value = tree;
  directoryDocumentTotal.value = tree.reduce((total, category) => total + category.total_document_count, 0);
  syncExpandedDirectories(tree);
}

function shouldFocusDirectories(): boolean {
  const focusValue = Array.isArray(route.query.focus) ? route.query.focus[0] : route.query.focus;
  return focusValue === 'directories' || focusValue === 'directory';
}

async function focusDirectoryPanelIfRequested(): Promise<void> {
  if (!shouldFocusDirectories()) return;
  await nextTick();
  directoryPanelRef.value?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  directoryPanelHighlighted.value = true;
  window.setTimeout(() => {
    directoryPanelHighlighted.value = false;
  }, 1400);
}

function directoryKey(id: number): string {
  return `directory-${id}`;
}

function isDirectoryExpanded(key: string): boolean {
  return expandedDirectoryKeys.value.includes(key);
}

function toggleDirectory(row: DirectoryRow): void {
  if (!row.children.length) return;
  expandedDirectoryKeys.value = isDirectoryExpanded(row.key)
    ? expandedDirectoryKeys.value.filter((key) => key !== row.key)
    : [...expandedDirectoryKeys.value, row.key];
}

function selectDirectory(row: DirectoryRow): void {
  activeDirectoryId.value = row.id;
  currentPage.value = 1;
  if (row.children.length && !isDirectoryExpanded(row.key)) {
    expandedDirectoryKeys.value = [...expandedDirectoryKeys.value, row.key];
  }
  void loadDocuments();
}

function directoryName(document: DocumentInfo): string {
  const directoryId = document.directory_id || document.category_id || null;
  return document.category_path || document.category_name || (directoryId ? categoryById.value.get(directoryId)?.name : '') || '-';
}

function documentDisplayName(document: DocumentInfo): string {
  return document.document_name || document.file_name;
}

function documentVersionLabel(document: DocumentInfo): string {
  const version = document.version || document.version_no || '-';
  return String(version).startsWith('v') ? String(version) : `v${version}`;
}

function documentUploader(document: DocumentInfo): string {
  if (document.uploader_name) return document.uploader_name;
  if (document.uploader_username) return document.uploader_username;
  const uploader = document.upload_user_id || document.created_by;
  return uploader ? t('project.detail.userFallback', { id: uploader }) : '-';
}

function documentStatusLabel(document: DocumentInfo): string {
  const status = document.status || document.document_status || document.review_status;
  const map: Record<string, string> = {
    active: 'project.detail.document.statusPublished',
    approved: 'project.detail.document.statusPublished',
    published: 'project.detail.document.statusPublished',
    reviewed: 'project.detail.document.statusPublished',
    pending: 'project.detail.document.statusPendingReview',
    pending_review: 'project.detail.document.statusPendingReview',
    draft: 'project.detail.document.statusPendingReview',
    submitted: 'project.detail.document.statusPendingReview',
  };
  const key = map[status || ''];
  return key ? t(key) : status || '-';
}

function documentStatusTheme(document: DocumentInfo): 'success' | 'warning' | 'default' {
  const status = document.status || document.document_status || document.review_status;
  if (['active', 'approved', 'published', 'reviewed'].includes(status || '')) return 'success';
  if (['pending', 'pending_review', 'draft', 'submitted'].includes(status || '')) return 'warning';
  return 'default';
}

function parseStatusLabel(document: DocumentInfo): string {
  const status = document.parse_status || 'unparsed';
  return resolveParseStatusText(status) || '-';
}

function parseStatusTheme(document: DocumentInfo): 'success' | 'warning' | 'danger' | 'default' {
  const status = document.parse_status || 'unparsed';
  if (status === 'success') return 'success';
  if (status === 'parsing') return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function normalizedIndexStatus(document: DocumentInfo): string {
  const status = document.index_status || '';
  const map: Record<string, string> = {
    indexed: 'indexed',
    success: 'indexed',
    completed: 'indexed',
    parsing: 'parsing',
    indexing: 'indexing',
    running: 'indexing',
    failed: 'failed',
    fail: 'failed',
    pending: 'not_indexed',
    not_indexed: 'not_indexed',
    unindexed: 'not_indexed',
  };
  return map[status] || status || 'not_indexed';
}

function indexStatusLabel(document: DocumentInfo): string {
  const status = normalizedIndexStatus(document);
  return resolveIndexStatusText(status) || '-';
}

function taskStatusTheme(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'indexed') return 'success';
  if (['parsing', 'indexing'].includes(status)) return 'warning';
  if (status === 'failed') return 'danger';
  return 'default';
}

function resetFilters(): void {
  filters.keyword = '';
  filters.document_status = '';
  filters.parse_status = '';
  filters.index_status = '';
  filters.security_level = '';
  currentPage.value = 1;
  void loadDocumentsAndDirectories();
}

function handleSearch(): void {
  currentPage.value = 1;
  void loadDocumentsAndDirectories();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  currentPage.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
  void loadDocuments();
}

function openUploadDialog(): void {
  if (!canUploadDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noUploadPermission'));
    return;
  }
  const fallbackDirectory = categoryOptions.value.find((item) => !item.disabled)?.value || null;
  const activeCategory = activeDirectoryId.value ? findCategory(categories.value, activeDirectoryId.value) : undefined;
  uploadForm.directory_id = activeCategory?.enabled ? activeDirectoryId.value : fallbackDirectory;
  uploadForm.security_level = clampSecurityLevel(activeCategory?.default_security_level, authStore.maxSecurityLevel);
  selectedUploadFiles.value = [];
  uploadDialogVisible.value = true;
}

function browseUploadFiles(): void {
  uploadInputRef.value?.click();
}

function handleFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectedUploadFiles.value = Array.from(input.files || []);
  input.value = '';
}

function removeUploadFile(index: number): void {
  selectedUploadFiles.value = selectedUploadFiles.value.filter((_, itemIndex) => itemIndex !== index);
}

async function confirmUpload(): Promise<void> {
  if (!uploadForm.directory_id) {
    MessagePlugin.warning(t('project.detail.message.selectParentDirectory'));
    return;
  }
  if (!selectedUploadFiles.value.length) {
    MessagePlugin.warning(t('project.detail.message.selectUploadFiles'));
    return;
  }

  uploading.value = true;
  try {
    for (const file of selectedUploadFiles.value) {
      await uploadProjectDocument(projectId.value, file, uploadForm.directory_id, uploadForm.security_level);
    }
    MessagePlugin.success(t('project.detail.message.uploadSuccess', { count: selectedUploadFiles.value.length }));
    uploadDialogVisible.value = false;
    currentPage.value = 1;
    await loadData();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('project.detail.message.uploadFailed'));
  } finally {
    uploading.value = false;
  }
}

function openCreateDirectoryDialog(): void {
  if (!canCreateDirectories.value) {
    MessagePlugin.warning(t('project.detail.message.noCreateDirectoryPermission'));
    return;
  }
  const activeCategory = activeDirectoryId.value ? findCategory(categories.value, activeDirectoryId.value) : undefined;
  categoryDialogMode.value = 'create';
  editingCategoryId.value = null;
  categoryForm.parent_id = activeCategory?.enabled ? activeDirectoryId.value : null;
  categoryForm.name = '';
  categoryForm.code = '';
  categoryForm.description = '';
  categoryForm.sort_order = 0;
  categoryForm.enabled = true;
  categoryForm.default_security_level = clampSecurityLevel(activeCategory?.default_security_level, authStore.maxSecurityLevel);
  categoryDialogVisible.value = true;
}

function openEditActiveDirectoryDialog(): void {
  if (!canEditDirectories.value) {
    MessagePlugin.warning(t('project.detail.message.noEditDirectoryPermission'));
    return;
  }
  const category = activeDirectory.value;
  if (!category) {
    MessagePlugin.warning(t('project.detail.message.selectEditDirectory'));
    return;
  }
  categoryDialogMode.value = 'edit';
  editingCategoryId.value = category.id;
  categoryForm.parent_id = category.parent_id || null;
  categoryForm.name = category.name;
  categoryForm.code = category.code;
  categoryForm.description = category.description || '';
  categoryForm.sort_order = category.sort_order;
  categoryForm.enabled = category.enabled;
  categoryForm.default_security_level = category.default_security_level || 'internal';
  categoryDialogVisible.value = true;
}

function openDeleteActiveDirectoryDialog(): void {
  if (!canDeleteDirectories.value) {
    MessagePlugin.warning(t('project.detail.message.noDeleteDirectoryPermission'));
    return;
  }
  const category = activeDirectory.value;
  if (!category) {
    MessagePlugin.warning(t('project.detail.message.selectDirectoryFirst'));
    return;
  }
  pendingDeleteDirectory.value = category;
  deleteDirectoryDialogVisible.value = true;
}

async function confirmCategoryDialog(): Promise<void> {
  if (categoryDialogMode.value === 'create' && !canCreateDirectories.value) {
    MessagePlugin.warning(t('project.detail.message.noCreateDirectoryPermission'));
    return;
  }
  if (categoryDialogMode.value === 'edit' && !canEditDirectories.value) {
    MessagePlugin.warning(t('project.detail.message.noEditDirectoryPermission'));
    return;
  }
  if (!categoryForm.name.trim()) {
    MessagePlugin.warning(t('project.detail.message.enterDirectoryName'));
    return;
  }

  const payload = {
    parent_id: categoryForm.parent_id,
    name: categoryForm.name.trim(),
    code: categoryForm.code.trim() || `project-${projectId.value}-${Date.now()}`,
    description: categoryForm.description.trim(),
    sort_order: Number(categoryForm.sort_order) || 0,
    enabled: categoryForm.enabled,
    default_security_level: categoryForm.default_security_level,
  };

  const result = categoryDialogMode.value === 'create'
    ? await createProjectDirectory(projectId.value, payload)
    : editingCategoryId.value
      ? await updateProjectDirectory(projectId.value, editingCategoryId.value, payload)
      : null;

  if (result?.tree) {
    applyDirectoryTree(await listProjectDirectories(projectId.value, directoryFilterParams()));
  }
  MessagePlugin.success(t('project.detail.message.directorySaved'));
  categoryDialogVisible.value = false;
}

async function confirmDeleteDirectory(): Promise<void> {
  if (!pendingDeleteDirectory.value) return;
  if (!canDeleteDirectories.value) {
    MessagePlugin.warning(t('project.detail.message.noDeleteDirectoryPermission'));
    return;
  }
  deletingDirectory.value = true;
  try {
    await deleteProjectDirectory(projectId.value, pendingDeleteDirectory.value.id);
    MessagePlugin.success(t('project.detail.message.directoryDeleted'));
    if (activeDirectoryId.value === pendingDeleteDirectory.value.id) {
      activeDirectoryId.value = null;
      currentPage.value = 1;
    }
    pendingDeleteDirectory.value = null;
    deleteDirectoryDialogVisible.value = false;
    applyDirectoryTree(await listProjectDirectories(projectId.value, directoryFilterParams()));
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('project.detail.message.directoryDeleteFailed'));
  } finally {
    deletingDirectory.value = false;
  }
}

function viewDocument(document: DocumentInfo): void {
  if (!canViewDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noViewDocumentPermission'));
    return;
  }
  router.push(withBreadcrumbContext(route, `/documents/${document.id}`));
}

function canSubmitReview(document: DocumentInfo): boolean {
  return canSubmitDocumentReview.value && SUBMITTABLE_REVIEW_STATUSES.has(document.review_status);
}

function canBuildIndex(document: DocumentInfo): boolean {
  const indexStatus = normalizedIndexStatus(document);
  return canBuildDocumentIndex.value && document.review_status === 'approved' && !['parsing', 'indexing'].includes(indexStatus);
}

async function submitReview(document: DocumentInfo): Promise<void> {
  if (!canSubmitDocumentReview.value) {
    MessagePlugin.warning(t('document.detail.message.noSubmitPermission'));
    return;
  }
  reviewSubmittingId.value = document.id;
  try {
    await submitDocumentReview(document.id);
    MessagePlugin.success(t('document.detail.message.submitted'));
    await loadDocumentsAndDirectories();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('document.detail.message.submitFailed'));
  } finally {
    reviewSubmittingId.value = null;
  }
}

async function createIndexBuild(document: DocumentInfo): Promise<void> {
  if (!canBuildDocumentIndex.value) {
    MessagePlugin.warning(t('document.detail.message.noBuildPermission'));
    return;
  }
  if (isIndexedIndexStatus(normalizedIndexStatus(document))) {
    const confirmed = await confirmRebuildIndexedDocument(documentDisplayName(document));
    if (!confirmed) return;
  }
  indexBuildingId.value = document.id;
  try {
    await createDocumentIndexBuildTask(document.id, document.version_no);
    MessagePlugin.success(t('document.detail.message.indexTaskCreated'));
    await loadDocumentsAndDirectories();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('document.detail.message.indexTaskCreateFailed'));
  } finally {
    indexBuildingId.value = null;
  }
}

onMounted(async () => {
  await loadData();
  await focusDirectoryPanelIfRequested();
});
</script>

<template>
  <PageContainer class="project-document-page" :title="t('project.detail.management.title')" :subtitle="t('project.detail.management.subtitle')">
    <div v-if="!canViewDocuments" class="document-state">
      <t-empty :description="t('project.detail.management.noAccess')" />
    </div>

    <div v-else class="project-document-manager">
      <aside ref="directoryPanelRef" class="directory-panel" :class="{ 'is-highlighted': directoryPanelHighlighted }">
        <div class="directory-title">
          <span>{{ projectTitle }}</span>
          <t-button
            v-if="canCreateDirectories"
            class="directory-create-button"
            size="small"
            variant="text"
            @click="openCreateDirectoryDialog"
          >
            <template #icon><AddIcon /></template>
          </t-button>
        </div>

        <div class="directory-tree">
          <t-button
            v-for="row in directoryRows"
            :key="row.key"
            class="directory-row"
            :class="{ active: activeDirectoryId === row.id, disabled: !row.enabled }"
            block
            variant="text"
            :style="{ paddingLeft: `${10 + row.level * 18}px` }"
            @click="selectDirectory(row)"
          >
            <span class="directory-row-main">
              <span
                v-if="row.children.length"
                class="directory-toggle"
                @click.stop="toggleDirectory(row)"
              >
                <ChevronDownSIcon v-if="isDirectoryExpanded(row.key)" />
                <ChevronRightSIcon v-else />
              </span>
              <span v-else class="directory-toggle-placeholder"></span>
              <span class="directory-name">{{ row.name }}</span>
            </span>
            <span class="directory-count">{{ row.count }}</span>
          </t-button>
        </div>

        <div v-if="canEditDirectories || canDeleteDirectories" class="directory-tools">
          <t-button
            v-if="canEditDirectories"
            class="directory-tool-button"
            size="small"
            variant="outline"
            :disabled="activeDirectoryId === null"
            @click="openEditActiveDirectoryDialog"
          >
            <template #icon><EditIcon /></template>
            {{ t('project.detail.management.editDirectory') }}
          </t-button>
          <t-button
            v-if="canDeleteDirectories"
            class="directory-tool-button danger"
            size="small"
            variant="outline"
            theme="danger"
            :disabled="activeDirectoryId === null"
            @click="openDeleteActiveDirectoryDialog"
          >
            <template #icon><DeleteIcon /></template>
            {{ t('project.detail.management.deleteDirectory') }}
          </t-button>
        </div>
      </aside>

      <main class="document-panel">
        <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
          <t-form-item :label="t('project.field.keyword')">
            <t-input
              v-model="filters.keyword"
              class="filter-input document-keyword-input"
              clearable
              :placeholder="t('review.placeholder.searchDocument')"
              @enter="handleSearch"
            >
              <template #prefix-icon><SearchIcon /></template>
            </t-input>
          </t-form-item>
          <t-form-item :label="t('document.detail.field.status')">
            <t-select v-model="filters.document_status" class="filter-select" clearable :placeholder="t('review.placeholder.allStatus')" @change="handleSearch">
              <t-option v-for="item in documentStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('document.detail.field.parseStatus')">
            <t-select v-model="filters.parse_status" class="filter-select" clearable :placeholder="t('review.placeholder.allStatus')" @change="handleSearch">
              <t-option v-for="item in parseStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('document.detail.field.indexStatus')">
            <t-select v-model="filters.index_status" class="filter-select" clearable :placeholder="t('review.placeholder.allStatus')" @change="handleSearch">
              <t-option v-for="item in indexStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('document.detail.field.securityLevel')">
            <t-select v-model="filters.security_level" class="filter-select" clearable :placeholder="t('project.placeholder.allSecurityLevel')" @change="handleSearch">
              <t-option v-for="item in securityLevelOptions(authStore.maxSecurityLevel)" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
          <t-form-item>
            <t-space>
              <t-button theme="primary" :loading="loading" @click="handleSearch">{{ t('common.action.search') }}</t-button>
              <t-button @click="resetFilters">{{ t('common.action.reset') }}</t-button>
            </t-space>
          </t-form-item>
        </t-form>

        <div class="system-section-head">
          <div class="system-section-title">
            <h2>{{ t('project.detail.management.documentList') }}</h2>
            <span>{{ t('project.detail.management.count', { count: documentTotal }) }}</span>
          </div>
          <t-space>
            <t-button variant="outline" @click="router.push(`/projects/${projectId}`)">{{ t('project.detail.management.backOverview') }}</t-button>
            <t-button theme="default" variant="outline" :loading="loading" @click="loadData">
              <template #icon><RefreshIcon /></template>
              {{ t('common.action.refresh') }}
            </t-button>
            <t-button theme="primary" :disabled="!canUploadDocuments" @click="openUploadDialog">
              <template #icon><CloudUploadIcon /></template>
              {{ t('project.detail.upload.title') }}
            </t-button>
          </t-space>
        </div>

        <div class="table-scroll">
          <t-table
            row-key="id"
            bordered
            table-layout="fixed"
            :data="documents"
            :columns="documentColumns"
            :loading="loading"
            :empty="t('project.detail.management.empty')"
          >
            <template #document_name="{ row }">
              <t-link class="document-name-link" theme="primary" @click="viewDocument(row)">
                {{ documentDisplayName(row) }}
              </t-link>
            </template>
            <template #directory="{ row }">
              {{ directoryName(row) }}
            </template>
            <template #security_level="{ row }">
              <t-tag size="small" variant="light" :theme="securityLevelTheme(row.security_level)">
                {{ securityLevelLabel(row.security_level) }}
              </t-tag>
            </template>
            <template #version="{ row }">
              {{ documentVersionLabel(row) }}
            </template>
            <template #file_size="{ row }">
              {{ formatFileSize(row.file_size) }}
            </template>
            <template #uploader="{ row }">
              {{ documentUploader(row) }}
            </template>
            <template #review_status="{ row }">
              <t-tag size="small" variant="light" :theme="documentStatusTheme(row)">{{ documentStatusLabel(row) }}</t-tag>
            </template>
            <template #parse_status="{ row }">
              <t-tag size="small" variant="light" :theme="parseStatusTheme(row)">{{ parseStatusLabel(row) }}</t-tag>
            </template>
            <template #index_status="{ row }">
              <t-tag size="small" variant="light" :theme="taskStatusTheme(normalizedIndexStatus(row))">
                {{ indexStatusLabel(row) }}
              </t-tag>
            </template>
            <template #created_at="{ row }">
              {{ formatDateTime(row.created_at) }}
            </template>
            <template #operation="{ row }">
              <div class="document-operation-actions">
                <t-button
                  :aria-label="t('common.action.view')"
                  :title="t('common.action.view')"
                  shape="square"
                  size="small"
                  variant="text"
                  @click="viewDocument(row)"
                >
                  <template #icon><BrowseIcon /></template>
                </t-button>
                <t-button
                  v-if="canSubmitDocumentReview"
                  :aria-label="t('document.detail.action.submitReview')"
                  :title="t('document.detail.action.submitReview')"
                  shape="square"
                  size="small"
                  theme="primary"
                  variant="text"
                  :disabled="!canSubmitReview(row)"
                  :loading="reviewSubmittingId === row.id"
                  @click="submitReview(row)"
                >
                  <template #icon><AssignmentCheckedIcon /></template>
                </t-button>
                <t-button
                  v-if="canBuildDocumentIndex"
                  :aria-label="t('review.tab.approved')"
                  :title="t('review.tab.approved')"
                  shape="square"
                  size="small"
                  theme="primary"
                  variant="text"
                  :disabled="!canBuildIndex(row)"
                  :loading="indexBuildingId === row.id"
                  @click="createIndexBuild(row)"
                >
                  <template #icon><PlayCircleIcon /></template>
                </t-button>
              </div>
            </template>
          </t-table>
        </div>

        <div class="system-pagination">
          <t-pagination
            :current="currentPage"
            :page-size="pageSize"
            :total="documentTotal"
            :page-size-options="PAGE_SIZE_OPTIONS"
            show-jumper
            @change="handlePaginationChange"
          />
        </div>
      </main>
    </div>

    <t-dialog
      v-model:visible="uploadDialogVisible"
      :header="t('project.detail.upload.title')"
      width="620px"
      :confirm-btn="{ content: t('common.action.upload'), loading: uploading }"
      @confirm="confirmUpload"
    >
      <div class="upload-dialog-body">
        <div class="upload-form-grid">
          <t-form-item :label="t('document.detail.field.directory')" required-mark>
            <t-select v-model="uploadForm.directory_id" :placeholder="t('project.detail.message.selectDirectory')">
              <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('project.detail.upload.security')" required-mark>
            <t-select v-model="uploadForm.security_level">
              <t-option v-for="item in securityLevelOptions(authStore.maxSecurityLevel)" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
        </div>

        <t-form-item :label="t('project.detail.upload.file')" required-mark>
          <input ref="uploadInputRef" class="hidden-file-input" type="file" multiple @change="handleFileChange" />
          <button type="button" class="upload-dropzone" @click="browseUploadFiles">
            <CloudUploadIcon />
            <strong>{{ t('project.detail.management.clickChooseFile') }}</strong>
            <span>{{ t('project.detail.management.uploadHint') }}</span>
          </button>

          <div v-if="selectedUploadFiles.length" class="upload-file-list">
            <div v-for="(file, index) in selectedUploadFiles" :key="`${file.name}-${file.size}-${index}`">
              <span>{{ file.name }}</span>
              <small>{{ formatFileSize(file.size) }}</small>
              <t-button size="small" variant="text" theme="danger" @click="removeUploadFile(index)">{{ t('project.detail.upload.remove') }}</t-button>
            </div>
          </div>
        </t-form-item>
      </div>
    </t-dialog>

    <t-dialog
      v-model:visible="categoryDialogVisible"
      :header="categoryDialogMode === 'create' ? t('project.detail.directory.createTitle') : t('project.detail.directory.editTitle')"
      width="560px"
      @confirm="confirmCategoryDialog"
    >
      <t-form :data="categoryForm" label-align="top">
        <t-form-item :label="t('project.detail.directory.parent')">
          <t-select v-model="categoryForm.parent_id" clearable :placeholder="t('project.detail.directory.root')">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.value === editingCategoryId" />
          </t-select>
        </t-form-item>
        <t-form-item :label="t('project.detail.directory.name')" required-mark><t-input v-model="categoryForm.name" /></t-form-item>
        <t-form-item :label="t('project.detail.directory.code')"><t-input v-model="categoryForm.code" :placeholder="t('project.detail.directory.autoCode')" /></t-form-item>
        <div class="upload-form-grid">
          <t-form-item :label="t('project.detail.directory.sort')"><t-input v-model="categoryForm.sort_order" type="number" /></t-form-item>
          <t-form-item :label="t('project.detail.directory.defaultSecurity')">
            <t-select v-model="categoryForm.default_security_level">
              <t-option
                v-for="item in securityLevelOptions(authStore.maxSecurityLevel, categoryForm.default_security_level)"
                :key="item.value"
                :value="item.value"
                :label="item.label"
                :disabled="item.disabled"
              />
            </t-select>
          </t-form-item>
        </div>
        <t-form-item :label="t('project.detail.directory.description')"><t-textarea v-model="categoryForm.description" /></t-form-item>
        <div class="directory-switch-row">
          <t-checkbox v-model="categoryForm.enabled">{{ t('project.detail.directory.enabled') }}</t-checkbox>
        </div>
      </t-form>
    </t-dialog>

    <t-dialog
      v-model:visible="deleteDirectoryDialogVisible"
      :header="t('project.detail.management.deleteDirectoryTitle')"
      theme="warning"
      width="480px"
      :confirm-btn="{ content: t('project.detail.deleteFile.confirm'), theme: 'danger', loading: deletingDirectory }"
      @confirm="confirmDeleteDirectory"
    >
      <div class="delete-directory-confirm">
        {{ t('project.detail.management.deleteDirectoryBody', { name: pendingDeleteDirectory?.name || '-' }) }}
      </div>
    </t-dialog>
  </PageContainer>
</template>

<style scoped>
.project-document-page {
  padding-top: 16px;
}

.project-document-page :deep(.toolbar) {
  display: none;
}

.document-state {
  display: grid;
  height: 100%;
  min-height: 360px;
  place-items: center;
}

.project-document-manager {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: 256px minmax(0, 1fr);
  overflow: hidden;
  background: #f4f7fb;
}

.directory-panel {
  display: flex;
  height: 100%;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #e5e7eb;
  background: #fff;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease;
}

.directory-panel.is-highlighted {
  border-color: #8bb7ff;
  box-shadow: inset 0 0 0 1px #8bb7ff;
}

.directory-title {
  display: flex;
  flex: 0 0 auto;
  height: 52px;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-bottom: 1px solid #eef2f7;
  color: #111827;
  font-size: 16px;
  font-weight: 700;
  padding: 0 16px;
}

.directory-title span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.directory-create-button {
  width: 28px;
  height: 28px;
  flex: 0 0 auto;
  border-radius: 6px;
  color: #2563eb;
  font-weight: 600;
  padding: 0;
}

.directory-create-button:hover {
  background: #eff6ff;
}

.directory-tree {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 14px 16px;
}

.directory-row {
  display: flex;
  width: 100%;
  height: auto;
  min-height: 34px;
  align-items: center;
  justify-content: space-between;
  border-radius: 6px;
  color: #475569;
  font-size: 14px;
  gap: 8px;
  padding: 0 10px;
  text-align: left;
}

.directory-row :deep(.t-button__text) {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.directory-row.active {
  background: #eaf4ff;
  color: #0474d8;
  font-weight: 700;
}

.directory-row.disabled {
  color: #94a3b8;
}

.directory-row-main {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
}

.directory-toggle,
.directory-toggle-placeholder {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  place-items: center;
  color: #94a3b8;
}

.directory-name {
  min-width: 0;
  overflow: hidden;
  font-weight: 400;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.directory-count {
  flex: 0 0 auto;
  color: #94a3b8;
  font-size: 12px;
  font-weight: 500;
}

.directory-tools {
  display: flex;
  gap: 8px;
  border-top: 1px solid #eef2f7;
  background: #fbfdff;
  padding: 12px 16px;
}

.directory-tool-button {
  flex: 1;
  height: 32px;
  border-color: #d8e3f0;
  border-radius: 6px;
  color: #334155;
  font-weight: 600;
}

.directory-tool-button:hover {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}

.directory-tool-button.danger {
  border-color: #fecaca;
}

.directory-tool-button.danger:hover {
  border-color: #fca5a5;
  background: #fff1f2;
}

.directory-tool-button:disabled {
  border-color: #e5e7eb;
  background: #f8fafc;
  color: #94a3b8;
}

.document-panel {
  display: flex;
  min-width: 0;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  background: #fff;
  padding: 16px;
}

.system-filter-form {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  align-items: center;
  gap: 12px 14px;
  margin-bottom: 18px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow-x: auto;
  padding: 14px 16px;
}

.system-filter-form :deep(.t-form__item) {
  flex: 0 0 auto;
  margin: 0;
}

.system-filter-form :deep(.t-form__label) {
  width: auto !important;
  padding-right: 8px;
}

.system-filter-form :deep(.t-form__controls) {
  margin-left: 0 !important;
}

.filter-input {
  width: 280px;
}

.document-keyword-input {
  width: 165px;
}

.filter-select {
  width: 150px;
}

.system-section-head {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 10px;
}

.system-section-title {
  display: flex;
  align-items: baseline;
  gap: 22px;
}

.system-section-title h2 {
  margin: 0;
  color: #0f172a;
  font-size: 18px;
  font-weight: 700;
}

.system-section-title span {
  color: #64748b;
  font-size: 13px;
}

.table-scroll {
  flex: 1 1 0;
  min-height: 240px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow: auto;
  scrollbar-gutter: auto;
}

.table-scroll :deep(.t-table) {
  --td-table-border-color: #edf2f7;
  min-width: 1480px;
  color: #1f2a44;
  font-size: 14px;
}

.table-scroll :deep(.t-table th) {
  height: 48px;
  background: #f8fafc;
  color: #0f172a;
  font-weight: 700;
}

.table-scroll :deep(.t-table td) {
  height: 48px;
}

.table-scroll :deep(.t-table th),
.table-scroll :deep(.t-table td),
.table-scroll :deep(.t-table__cell) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.table-scroll :deep(.t-table__content) {
  border-radius: 6px;
}

.table-scroll :deep(.t-table__body tr:hover td) {
  background: #f8fbff;
}

.table-scroll :deep(.t-table th:last-child),
.table-scroll :deep(.t-table td:last-child),
.table-scroll :deep(.t-table td:last-child .t-table__cell) {
  overflow: visible;
  text-overflow: clip;
}

.table-scroll :deep(.t-table th:first-child),
.table-scroll :deep(.t-table td:first-child),
.table-scroll :deep(.t-table td:first-child .t-table__cell) {
  position: sticky;
  left: 0;
  z-index: 3;
  background: #fff;
}

.table-scroll :deep(.t-table th:first-child) {
  z-index: 4;
  background: #f8fafc;
}

.table-scroll :deep(.t-table th:last-child) {
  right: 0;
  z-index: 4;
  background: #f8fafc;
}

.table-scroll :deep(.t-table td:last-child) {
  position: sticky;
  right: 0;
  z-index: 3;
  background: #fff;
}

.table-scroll :deep(.t-table td:last-child .t-table__cell) {
  overflow: visible;
}

.document-operation-actions {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-width: 132px;
  white-space: nowrap;
}

.table-scroll :deep(.document-operation-actions .t-button__text) {
  overflow: visible;
  text-overflow: clip;
}

.document-name-link {
  display: inline-block;
  max-width: 100%;
}

.system-pagination {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  min-height: 48px;
  margin-top: 12px;
  border-top: 1px solid #edf2f7;
  background: #fff;
  padding-top: 12px;
}


.upload-dialog-body {
  display: grid;
  gap: 16px;
}

.upload-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.hidden-file-input {
  display: none;
}

.upload-dropzone {
  display: grid;
  min-height: 130px;
  place-items: center;
  gap: 6px;
  border: 1px dashed #b8c7dc;
  border-radius: 8px;
  background: #f8fbff;
  color: #53627d;
  cursor: pointer;
  font: inherit;
  padding: 18px;
}

.upload-dropzone:hover {
  border-color: #1d6ff2;
  background: #f3f8ff;
}

.upload-dropzone :deep(svg) {
  width: 30px;
  height: 30px;
  color: #1d6ff2;
}

.upload-dropzone strong {
  color: #0f172a;
  font-size: 15px;
}

.upload-dropzone span {
  color: #64748b;
  font-size: 13px;
}

.upload-file-list {
  display: grid;
  max-height: 180px;
  gap: 8px;
  overflow: auto;
}

.upload-file-list div {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 10px;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  padding: 8px 10px;
}

.upload-file-list span {
  min-width: 0;
  overflow: hidden;
  color: #0f172a;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-file-list small {
  color: #64748b;
}

.directory-switch-row {
  display: flex;
  flex-wrap: wrap;
  gap: 18px;
}

.delete-directory-confirm {
  color: #334155;
  font-size: 14px;
  line-height: 1.7;
}

@media (max-width: 1180px) {
  .document-keyword-input {
    width: 130px;
  }
}

@media (max-width: 820px) {
  .project-document-manager {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .directory-panel {
    max-height: 320px;
    border-right: 0;
    border-bottom: 1px solid #e2e8f0;
  }

  .document-panel {
    min-height: 620px;
  }

  .system-section-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .system-filter-form {
    flex-wrap: wrap;
    overflow-x: visible;
  }

  .document-keyword-input,
  .filter-input,
  .filter-select {
    width: 100%;
  }

  .upload-form-grid {
    grid-template-columns: 1fr;
  }

  .system-pagination {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
