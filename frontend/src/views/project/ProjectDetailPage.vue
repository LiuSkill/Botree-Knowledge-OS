<!--
  Project Detail Page

  负责：
  1. 展示项目基础信息、项目资料目录树和项目成员。
  2. 项目资料按项目内目录隔离，上传时强制选择目录。
  3. 项目资料页只负责提交审核，解析与索引统一进入审核中心构建流程。
-->
<script setup lang="ts">
import {
  AddIcon,
  ChatBubbleHelpIcon,
  ChevronDownSIcon,
  ChevronRightSIcon,
  DownloadIcon,
  EditIcon,
  FileExcelFilledIcon,
  FilePdfFilledIcon,
  FilePowerpointFilledIcon,
  FileSearchIcon,
  FileWordFilledIcon,
  FolderIcon,
  RefreshIcon,
  TaskCheckedIcon,
} from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref, type Component } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';

import {
  downloadDocumentVersion,
} from '@/api/documents';
import {
  createProjectDirectory,
  createProjectDocumentVersion,
  deleteProjectDirectory,
  deleteProjectDocument,
  getProjectOverview,
  listProjectDirectories,
  listProjectDocuments,
  listProjectDocumentVersions,
  listProjectMembers,
  publishProjectDocument,
  retryIndexProjectDocument,
  retryParseProjectDocument,
  setProjectDocumentCurrentVersion,
  updateProject,
  updateProjectDirectory,
  updateProjectDocument,
  updateProjectDocumentSecurityLevel,
  uploadProjectDocument,
  type ProjectPayload,
} from '@/api/projects';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { ROUTE_PATHS } from '@/shared/constants/routes';
import { useAuthStore } from '@/stores/auth';
import type {
  DocumentInfo,
  DocumentVersionInfo,
  KnowledgeCategory,
  ProjectOverviewInfo,
  ProjectRecentDocumentSummary,
  ProjectStatus,
  SecurityLevel,
} from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { buildCategoryOptions, collectCategoryIds, findCategory } from '@/utils/categories';
import { indexStatusText, parseStatusText, REVIEW_TASK_STATUS } from '@/utils/constants';
import { formatDateTime, formatFileSize } from '@/utils/format';
import { clampSecurityLevel, securityLevelLabel, securityLevelOptions, securityLevelTheme } from '@/utils/securityLevels';
import ProjectFormDrawer from '@/views/project/ProjectFormDrawer.vue';

type CategoryDialogMode = 'create' | 'edit';
type DrawerTab = 'basic' | 'versions' | 'parse' | 'index';

interface CategoryRow {
  category: KnowledgeCategory;
  level: number;
}

interface DirectoryTemplateNode {
  code: string;
  nameKey: string;
  children: DirectoryTemplateNode[];
}

interface OverviewDirectoryNode {
  key: string;
  code: string;
  name: string;
  count: number;
  enabled: boolean;
  children: OverviewDirectoryNode[];
}

interface OverviewDirectoryRow extends OverviewDirectoryNode {
  level: number;
}

interface RecentDocumentDisplayItem {
  id: number;
  name: string;
  fileType: string;
  fileSize: string;
  uploadedAt: string;
  uploader: string;
  icon: Component;
  tone: 'blue' | 'green' | 'orange' | 'red' | 'gray';
}

const SUBMITTABLE_REVIEW_STATUSES = new Set(['draft', 'rejected']);
const DOCUMENT_TYPE_OPTIONS = [
  '合同文件',
  '程序文件',
  '组织通讯录',
  'WBS文件',
  '进度计划',
  '月报',
  '会议纪要',
  '设计输入',
  '设计基础',
  '设计成品',
  '厂商资料',
  '图纸',
  '设备资料',
  '采购文件',
  '其他',
];
const DISCIPLINE_OPTIONS = ['工艺', '管道', '设备', '仪表', '电气', '结构', '造价', '拆解', '采购', '项目管理', '其他'];
const DOCUMENT_TYPE_KEY_MAP: Record<string, string> = {
  合同文件: 'project.detail.documentType.contract',
  程序文件: 'project.detail.documentType.procedure',
  组织通讯录: 'project.detail.documentType.directory',
  WBS文件: 'project.detail.documentType.wbs',
  进度计划: 'project.detail.documentType.schedule',
  月报: 'project.detail.documentType.monthlyReport',
  会议纪要: 'project.detail.documentType.meetingMinutes',
  设计输入: 'project.detail.documentType.designInput',
  设计基础: 'project.detail.documentType.designBasis',
  设计成品: 'project.detail.documentType.designOutput',
  厂商资料: 'project.detail.documentType.vendorData',
  图纸: 'project.detail.documentType.drawing',
  设备资料: 'project.detail.documentType.equipmentData',
  采购文件: 'project.detail.documentType.procurement',
  其他: 'project.detail.documentType.other',
};
const DISCIPLINE_KEY_MAP: Record<string, string> = {
  工艺: 'project.detail.discipline.process',
  管道: 'project.detail.discipline.piping',
  设备: 'project.detail.discipline.equipment',
  仪表: 'project.detail.discipline.instrument',
  电气: 'project.detail.discipline.electrical',
  结构: 'project.detail.discipline.structure',
  造价: 'project.detail.discipline.cost',
  拆解: 'project.detail.discipline.dismantling',
  采购: 'project.detail.discipline.procurement',
  项目管理: 'project.detail.discipline.projectManagement',
  其他: 'project.detail.discipline.other',
};
const ACCEPTED_UPLOAD_EXTENSIONS = new Set(['txt', 'md', 'csv', 'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'odt', 'odp', 'ods', 'rtf', 'zip', 'rar']);
const RECENT_UPLOAD_DOCUMENT_LIMIT = 5;
const DEFAULT_PROJECT_DIRECTORY_TEMPLATE: DirectoryTemplateNode[] = [
  {
    code: 'A',
    nameKey: 'project.detail.defaultDirectory.projectManagement',
    children: [
      { code: 'A01', nameKey: 'project.detail.defaultDirectory.projectContract', children: [] },
      { code: 'A02', nameKey: 'project.detail.defaultDirectory.projectProcedure', children: [] },
      { code: 'A03', nameKey: 'project.detail.defaultDirectory.projectOrganization', children: [] },
      { code: 'A04', nameKey: 'project.detail.defaultDirectory.wbs', children: [] },
      { code: 'A05', nameKey: 'project.detail.defaultDirectory.projectTemplate', children: [] },
      { code: 'A06', nameKey: 'project.detail.defaultDirectory.projectSchedule', children: [] },
      { code: 'A07', nameKey: 'project.detail.defaultDirectory.monthlyReport', children: [] },
      { code: 'A08', nameKey: 'project.detail.defaultDirectory.meetingMinutes', children: [] },
    ],
  },
  {
    code: 'E',
    nameKey: 'project.detail.defaultDirectory.designData',
    children: [
      { code: 'E01', nameKey: 'project.detail.defaultDirectory.designInput', children: [] },
      { code: 'E02', nameKey: 'project.detail.defaultDirectory.designBasis', children: [] },
      { code: 'E03', nameKey: 'project.detail.defaultDirectory.designOutput', children: [] },
      { code: 'E04', nameKey: 'project.detail.defaultDirectory.vendorData', children: [] },
    ],
  },
  {
    code: 'D',
    nameKey: 'project.detail.defaultDirectory.disciplineData',
    children: [
      { code: '00', nameKey: 'project.detail.defaultDirectory.projectGeneralRules', children: [] },
      { code: '01', nameKey: 'project.detail.defaultDirectory.process', children: [] },
      { code: '02', nameKey: 'project.detail.defaultDirectory.piping', children: [] },
      { code: '03', nameKey: 'project.detail.defaultDirectory.equipment', children: [] },
      { code: '04', nameKey: 'project.detail.defaultDirectory.instrument', children: [] },
      { code: '05', nameKey: 'project.detail.defaultDirectory.electrical', children: [] },
      { code: '06', nameKey: 'project.detail.defaultDirectory.structure', children: [] },
      { code: '07', nameKey: 'project.detail.defaultDirectory.cost', children: [] },
      { code: '08', nameKey: 'project.detail.defaultDirectory.dismantling', children: [] },
    ],
  },
  {
    code: 'P',
    nameKey: 'project.detail.defaultDirectory.procurementData',
    children: [
      { code: '01', nameKey: 'project.detail.defaultDirectory.mainContract', children: [] },
      { code: '02', nameKey: 'project.detail.defaultDirectory.procurementManagement', children: [] },
      { code: '03', nameKey: 'project.detail.defaultDirectory.procurementContract', children: [] },
      { code: '04', nameKey: 'project.detail.defaultDirectory.inspectionSubmission', children: [] },
      { code: '05', nameKey: 'project.detail.defaultDirectory.transportation', children: [] },
      { code: '06', nameKey: 'project.detail.defaultDirectory.siteProcurement', children: [] },
      { code: '07', nameKey: 'project.detail.defaultDirectory.statusSheet', children: [] },
      { code: '08', nameKey: 'project.detail.defaultDirectory.spareParts', children: [] },
      { code: '09', nameKey: 'project.detail.defaultDirectory.vendorData', children: [] },
      { code: '10', nameKey: 'project.detail.defaultDirectory.procurementRequired', children: [] },
      { code: '11', nameKey: 'project.detail.defaultDirectory.internalProcurementContract', children: [] },
    ],
  },
];

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const { t, locale } = useI18n();
const project = ref<ProjectOverviewInfo | null>(null);
const documents = ref<DocumentInfo[]>([]);
const selectedDocument = ref<DocumentInfo | null>(null);
const documentDetailVisible = ref(false);
const documentVersions = ref<DocumentVersionInfo[]>([]);
const drawerTab = ref<DrawerTab>('basic');
const versionDialogVisible = ref(false);
const selectedVersionFile = ref<File | null>(null);
const selectedUploadFiles = ref<File[]>([]);
const selectedDocumentIds = ref<number[]>([]);
const members = ref<Array<Record<string, unknown>>>([]);
const categories = ref<KnowledgeCategory[]>([]);
const activeCategoryId = ref<number | null>(null);
const expandedCategoryIds = ref<number[]>([]);
const expandedOverviewDirectoryKeys = ref<string[]>([]);
const loading = ref(false);
const documentsLoading = ref(false);
const uploading = ref(false);
const uploadDialogVisible = ref(false);
const uploadInputRef = ref<HTMLInputElement | null>(null);
const deleteDialogVisible = ref(false);
const deleteSubmitting = ref(false);
const deleteTargetDocuments = ref<DocumentInfo[]>([]);
const projectDialogVisible = ref(false);
const projectSaving = ref(false);
const categoryDialogVisible = ref(false);
const categoryDialogMode = ref<CategoryDialogMode>('create');
const editingCategoryId = ref<number | null>(null);

const projectId = computed(() => Number(route.params.id));
const categoryOptions = computed(() => buildCategoryOptions(categories.value));
const documentStatusOptions = computed(() => [
  { label: t('project.detail.document.statusPendingReview'), value: '待审核' },
  { label: t('project.detail.document.statusPublished'), value: '已发布' },
]);
const documentTypeOptions = computed(() => DOCUMENT_TYPE_OPTIONS.map((value) => ({ label: t(DOCUMENT_TYPE_KEY_MAP[value]), value })));
const disciplineOptions = computed(() => DISCIPLINE_OPTIONS.map((value) => ({ label: t(DISCIPLINE_KEY_MAP[value]), value })));
const canViewProjectDetail = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_VIEW));
const canEditProject = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_EDIT));
const canViewDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_VIEW));
const canUploadDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_UPLOAD));
const canPreviewDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_PREVIEW));
const canDownloadDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_DOWNLOAD));
const canPublishDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_SUBMIT_REVIEW));
const canDeleteDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_DELETE));
const canRetryParseDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_RETRY_PARSE));
const canRetryIndexDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_RETRY_INDEX));
const canUpdateDocumentSecurity = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_SECURITY_UPDATE));
const canUpdateDocumentMetadata = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_EDIT));
const canCreateDocumentVersion = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_VERSION_CREATE));
const canSetCurrentDocumentVersion = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_VERSION_SET_CURRENT));
const canViewDocumentVersions = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DOCUMENT_VERSION_VIEW));
const canViewDirectories = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_VIEW));
const canCreateCategories = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DIRECTORY_CREATE));
const canEditCategories = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DIRECTORY_EDIT));
const canDeleteCategories = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DIRECTORY_DELETE));
const canAskProjectChat = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_CHAT));
const canUseProjectChat = computed(() => canAskProjectChat.value && (project.value?.project_chat_enabled ?? true));
const currentProjectId = computed(() => normalizeProjectId(project.value?.id) ?? normalizeProjectId(projectId.value));
const canOpenProjectDocuments = computed(() => canViewDocuments.value && authStore.hasMenuPermission(PERMISSIONS.PROJECT) && currentProjectId.value !== null);
const canOpenProjectChat = computed(
  () =>
    canUseProjectChat.value &&
    authStore.hasMenuPermission(PERMISSIONS.AI_PROJECT_CHAT) &&
    authStore.hasActionPermission(PERMISSIONS.AI_PROJECT_CHAT_VIEW) &&
    currentProjectId.value !== null,
);
const canOpenPendingReviewDocuments = computed(
  () =>
    authStore.hasMenuPermission(PERMISSIONS.REVIEW) &&
    authStore.hasActionPermission(PERMISSIONS.REVIEW_VIEW) &&
    currentProjectId.value !== null,
);

const uploadForm = reactive({
  category_id: null as number | null,
  security_level: clampSecurityLevel('internal', authStore.maxSecurityLevel),
  document_type: '',
  discipline: '',
  remark: '',
});

const documentFilters = reactive({
  keyword: '',
  document_status: '',
  security_level: '' as SecurityLevel | '',
  parse_status: '',
  index_status: '',
  document_type: '',
  discipline: '',
  version: '',
  upload_user_id: '',
  updated_range: [] as string[],
});

const batchForm = reactive({
  security_level: clampSecurityLevel('internal', authStore.maxSecurityLevel),
});

const metadataForm = reactive({
  document_name: '',
  directory_id: null as number | null,
  document_type: '',
  discipline: '',
  version: '',
  remark: '',
});

const versionForm = reactive({
  directory_id: null as number | null,
  version_note: '',
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

const visibleCategoryRows = computed<CategoryRow[]>(() => {
  /**
   * 根据展开状态生成左侧可见目录行，支持无限层级。
   */
  const rows: CategoryRow[] = [];
  const walk = (items: KnowledgeCategory[], level: number): void => {
    for (const category of items) {
      rows.push({ category, level });
      if (expandedCategoryIds.value.includes(category.id)) {
        walk(category.children || [], level + 1);
      }
    }
  };
  walk(categories.value, 0);
  return rows;
});

const filteredDocuments = computed(() => {
  /**
   * 目录筛选包含当前目录及其所有子目录，保证树形筛选符合用户直觉。
   */
  const activeCategory = findCategory(categories.value, activeCategoryId.value);
  const categoryIds = collectCategoryIds(activeCategory);
  const keyword = documentFilters.keyword.trim().toLowerCase();
  return documents.value.filter((document) => {
    const directoryId = documentDirectoryId(document);
    if (categoryIds.length && !categoryIds.includes(Number(directoryId))) return false;
    if (keyword) {
      const haystack = [
        document.document_name,
        document.file_name,
        document.category_name,
        document.category_path,
        document.document_type,
        document.discipline,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase();
      if (!haystack.includes(keyword)) return false;
    }
    if (documentFilters.document_status && documentStatusText(document) !== documentFilters.document_status) return false;
    if (documentFilters.security_level && document.security_level !== documentFilters.security_level) return false;
    if (documentFilters.parse_status && documentParseStatus(document) !== documentFilters.parse_status) return false;
    if (documentFilters.index_status && documentIndexStatus(document) !== documentFilters.index_status) return false;
    if (documentFilters.document_type && document.document_type !== documentFilters.document_type) return false;
    if (documentFilters.discipline && document.discipline !== documentFilters.discipline) return false;
    if (documentFilters.version) {
      const version = String(document.version || document.version_no || '').toLowerCase();
      if (!version.includes(documentFilters.version.trim().toLowerCase())) return false;
    }
    if (documentFilters.upload_user_id) {
      const uploader = String(document.upload_user_id || document.created_by || '');
      if (!uploader.includes(documentFilters.upload_user_id.trim())) return false;
    }
    if (documentFilters.updated_range.length === 2) {
      const updatedAt = (document.updated_at || document.created_at || '').slice(0, 10);
      const [startedAt, endedAt] = documentFilters.updated_range;
      if (updatedAt && (updatedAt < startedAt || updatedAt > endedAt)) return false;
    }
    return true;
  });
});

const overviewDirectoryTree = computed<OverviewDirectoryNode[]>(() => {
  locale.value;
  if (categories.value.length) {
    return categories.value.map(toOverviewDirectoryNode);
  }
  return DEFAULT_PROJECT_DIRECTORY_TEMPLATE.map(toDefaultDirectoryNode);
});

const overviewDirectoryRows = computed<OverviewDirectoryRow[]>(() => {
  const rows: OverviewDirectoryRow[] = [];
  const walk = (items: OverviewDirectoryNode[], level: number): void => {
    for (const item of items) {
      rows.push({ ...item, level });
      if (isOverviewDirectoryExpanded(item.key)) {
        walk(item.children, level + 1);
      }
    }
  };
  walk(overviewDirectoryTree.value, 0);
  return rows;
});

const recentUploadDocuments = computed<RecentDocumentDisplayItem[]>(() => {
  locale.value;
  return (project.value?.recent_documents || []).slice(0, RECENT_UPLOAD_DOCUMENT_LIMIT).map((document) => {
    const fileMeta = recentDocumentFileMeta(document);
    return {
      id: document.id,
      name: document.document_name || document.file_name,
      fileType: recentDocumentFileType(document),
      fileSize: formatFileSize(document.file_size),
      uploadedAt: formatDateTime(document.created_at),
      uploader: recentDocumentUploader(document),
      icon: fileMeta.icon,
      tone: fileMeta.tone,
    };
  });
});

const selectedDocuments = computed(() => documents.value.filter((document) => selectedDocumentIds.value.includes(document.id)));

function normalizeProjectId(value: unknown): number | null {
  const projectIdValue = Number(value);
  return Number.isInteger(projectIdValue) && projectIdValue > 0 ? projectIdValue : null;
}

async function loadData(): Promise<void> {
  /**
   * 加载项目概览和资料目录。详情页首屏只展示概览，完整资料管理后续在独立页面承接。
   */
  if (!canViewProjectDetail.value) {
    loading.value = false;
    project.value = null;
    categories.value = [];
    documents.value = [];
    documentsLoading.value = false;
    selectedDocument.value = null;
    documentDetailVisible.value = false;
    selectedDocumentIds.value = [];
    members.value = [];
    expandedOverviewDirectoryKeys.value = [];
    return;
  }
  loading.value = true;
  try {
    const projectInfo = await loadProjectDetailSafely();
    if (!projectInfo) return;
    project.value = projectInfo;

    const projectCategories = await loadProjectDirectoriesSafely();
    categories.value = projectCategories;
    expandedCategoryIds.value = projectCategories.map((category) => category.id);
    expandedOverviewDirectoryKeys.value = [];
    documents.value = [];
    selectedDocument.value = null;
    selectedDocumentIds.value = [];
    documentVersions.value = [];
    documentDetailVisible.value = false;
    documentsLoading.value = false;
  } finally {
    loading.value = false;
  }
}

async function loadProjectDetailSafely(): Promise<ProjectOverviewInfo | null> {
  try {
    return await getProjectOverview(projectId.value);
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('project.detail.message.loadFailed'));
    project.value = null;
    categories.value = [];
    documents.value = [];
    documentsLoading.value = false;
    selectedDocument.value = null;
    documentDetailVisible.value = false;
    selectedDocumentIds.value = [];
    members.value = [];
    expandedOverviewDirectoryKeys.value = [];
    return null;
  }
}

async function loadProjectDirectoriesSafely(): Promise<KnowledgeCategory[]> {
  if (!canViewDirectories.value) return [];
  try {
    return await listProjectDirectories(projectId.value);
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : t('project.detail.message.directoryLoadFailed'));
    return [];
  }
}

async function loadProjectDocumentsSafely(): Promise<DocumentInfo[]> {
  if (!canViewDocuments.value) return [];
  try {
    return await listProjectDocuments(projectId.value);
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : t('project.detail.message.documentsLoadFailed'));
    return [];
  }
}

async function loadProjectMembersSafely(): Promise<Array<Record<string, unknown>>> {
  try {
    return await listProjectMembers(projectId.value);
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : t('project.detail.message.membersLoadFailed'));
    return [];
  }
}

function selectCategory(categoryId: number | null): void {
  /**
   * 切换项目资料目录筛选。
   */
  activeCategoryId.value = categoryId;
}

function toggleCategory(categoryId: number): void {
  /**
   * 展开或收起一个目录节点。
   */
  expandedCategoryIds.value = expandedCategoryIds.value.includes(categoryId)
    ? expandedCategoryIds.value.filter((id) => id !== categoryId)
    : [...expandedCategoryIds.value, categoryId];
}

function isCategoryExpanded(categoryId: number): boolean {
  /**
   * 判断目录节点是否处于展开状态。
   */
  return expandedCategoryIds.value.includes(categoryId);
}

function toOverviewDirectoryNode(category: KnowledgeCategory): OverviewDirectoryNode {
  /**
   * 将后端项目目录树转换为概览页展示结构，计数优先使用包含子目录的 total_document_count。
   */
  return {
    key: `category-${category.id}`,
    code: category.code,
    name: category.name,
    count: category.total_document_count,
    enabled: category.enabled,
    children: (category.children || []).map(toOverviewDirectoryNode),
  };
}

function toDefaultDirectoryNode(item: DirectoryTemplateNode): OverviewDirectoryNode {
  return {
    key: `default-${item.code}-${item.nameKey}`,
    code: item.code,
    name: t(item.nameKey),
    count: 0,
    enabled: true,
    children: item.children.map(toDefaultDirectoryNode),
  };
}

function toggleOverviewDirectory(key: string): void {
  expandedOverviewDirectoryKeys.value = isOverviewDirectoryExpanded(key)
    ? expandedOverviewDirectoryKeys.value.filter((item) => item !== key)
    : [...expandedOverviewDirectoryKeys.value, key];
}

function isOverviewDirectoryExpanded(key: string): boolean {
  return expandedOverviewDirectoryKeys.value.includes(key);
}

function recentDocumentFileType(document: ProjectRecentDocumentSummary): string {
  const fileType = (document.file_type || document.file_name.split('.').pop() || '').trim();
  return fileType ? fileType.toUpperCase() : 'FILE';
}

function recentDocumentUploader(document: ProjectRecentDocumentSummary): string {
  if (document.uploader_name) return document.uploader_name;
  if (document.uploader_username) return document.uploader_username;
  return document.upload_user_id ? t('project.detail.userFallback', { id: document.upload_user_id }) : '-';
}

function recentDocumentFileMeta(document: ProjectRecentDocumentSummary): Pick<RecentDocumentDisplayItem, 'icon' | 'tone'> {
  const extension = recentDocumentFileType(document).toLowerCase();
  if (['doc', 'docx', 'wps'].includes(extension)) return { icon: FileWordFilledIcon, tone: 'blue' };
  if (['xls', 'xlsx', 'csv'].includes(extension)) return { icon: FileExcelFilledIcon, tone: 'green' };
  if (['ppt', 'pptx'].includes(extension)) return { icon: FilePowerpointFilledIcon, tone: 'orange' };
  if (extension === 'pdf') return { icon: FilePdfFilledIcon, tone: 'red' };
  return { icon: FileSearchIcon, tone: 'gray' };
}

function openUploadDialog(): void {
  if (!canUploadDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noUploadPermission'));
    return;
  }
  /**
   * 打开上传弹窗，并预填当前选中的项目资料目录。
   */
  if (!categoryOptions.value.length) {
    MessagePlugin.warning(t('project.detail.message.configureDirectoryFirst'));
    return;
  }
  uploadForm.category_id = activeCategoryId.value || categoryOptions.value.find((item) => !item.disabled)?.value || null;
  const selectedCategory = findCategory(categories.value, uploadForm.category_id);
  uploadForm.security_level = clampSecurityLevel(
    selectedCategory?.default_security_level || project.value?.security_level,
    authStore.maxSecurityLevel,
  );
  uploadForm.document_type = '';
  uploadForm.discipline = '';
  uploadForm.remark = '';
  selectedUploadFiles.value = [];
  uploadDialogVisible.value = true;
}

function openProjectDialog(): void {
  if (!canEditProject.value) {
    MessagePlugin.warning(t('project.message.noEditPermission'));
    return;
  }
  if (!project.value) return;
  projectDialogVisible.value = true;
}

async function confirmProjectDialog(payload: ProjectPayload): Promise<void> {
  if (!project.value) return;
  projectSaving.value = true;
  try {
    await updateProject(project.value.id, payload);
    MessagePlugin.success(t('project.message.updated'));
    projectDialogVisible.value = false;
    await loadData();
  } finally {
    projectSaving.value = false;
  }
}

function normalizeProjectStatus(status?: string): ProjectStatus {
  if (status === '待启动' || status === '进行中' || status === '已完成' || status === '已暂停') return status;
  const legacyMap: Record<string, ProjectStatus> = {
    pending: '待启动',
    active: '进行中',
    completed: '已完成',
    archived: '已暂停',
    inactive: '已暂停',
  };
  return legacyMap[status || ''] || '进行中';
}

function projectStatusLabel(status?: string): string {
  const keyMap: Record<ProjectStatus, string> = {
    待启动: 'project.status.pending',
    进行中: 'project.status.active',
    已完成: 'project.status.completed',
    已暂停: 'project.status.paused',
  };
  return t(keyMap[normalizeProjectStatus(status)]);
}

function projectStatusTheme(status?: string): 'default' | 'primary' | 'success' | 'warning' {
  const themeMap: Record<ProjectStatus, 'default' | 'primary' | 'success' | 'warning'> = {
    待启动: 'warning',
    进行中: 'primary',
    已完成: 'success',
    已暂停: 'default',
  };
  return themeMap[normalizeProjectStatus(status)];
}

function projectFieldTagTheme(field: 'project_type' | 'project_stage' | 'raw_material_type'): 'default' | 'primary' | 'success' | 'warning' {
  const themeMap = {
    project_type: 'primary',
    project_stage: 'warning',
    raw_material_type: 'success',
  } as const;
  return themeMap[field];
}

function profileText(value?: string | number | null): string {
  const text = String(value ?? '').trim();
  return text || '-';
}

function handleFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  setUploadFiles(Array.from(input.files || []));
  input.value = '';
}

function handleUploadDrop(event: DragEvent): void {
  setUploadFiles(Array.from(event.dataTransfer?.files || []));
}

function browseUploadFiles(): void {
  uploadInputRef.value?.click();
}

function removeUploadFile(index: number): void {
  selectedUploadFiles.value = selectedUploadFiles.value.filter((_, itemIndex) => itemIndex !== index);
}

function setUploadFiles(files: File[]): void {
  const validFiles = files.filter((file) => {
    const extension = file.name.split('.').pop()?.toLowerCase() || '';
    return ACCEPTED_UPLOAD_EXTENSIONS.has(extension);
  });
  if (validFiles.length !== files.length) {
    MessagePlugin.warning(t('project.detail.message.unsupportedFilesFiltered'));
  }
  selectedUploadFiles.value = validFiles;
}

async function confirmUpload(): Promise<void> {
  if (!canUploadDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noUploadPermission'));
    return;
  }
  /**
   * 批量上传沿用后端单文件上传协议，逐个上传后再用现有元数据接口补写类型、专业和备注。
   */
  if (!selectedUploadFiles.value.length) {
    MessagePlugin.warning(t('project.detail.message.selectUploadFiles'));
    return;
  }
  if (!uploadForm.category_id) {
    MessagePlugin.warning(t('project.detail.message.selectDirectory'));
    return;
  }

  uploading.value = true;
  try {
    for (const file of selectedUploadFiles.value) {
      const uploaded = await uploadProjectDocument(projectId.value, file, uploadForm.category_id, uploadForm.security_level);
      if (uploadForm.document_type || uploadForm.discipline || uploadForm.remark) {
        await updateProjectDocument(projectId.value, uploaded.id, {
          directory_id: uploadForm.category_id,
          category_id: uploadForm.category_id,
          document_type: uploadForm.document_type || null,
          discipline: uploadForm.discipline || null,
          remark: uploadForm.remark.trim() || null,
        });
      }
    }
    MessagePlugin.success(t('project.detail.message.uploadSuccess', { count: selectedUploadFiles.value.length }));
    uploadDialogVisible.value = false;
    selectedUploadFiles.value = [];
    await loadData();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('project.detail.message.uploadFailed'));
  } finally {
    uploading.value = false;
  }
}

async function submitReview(document: DocumentInfo): Promise<void> {
  if (!canPublishDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noPublishPermission'));
    return;
  }
  /**
   * 项目资料提交审核，解析与索引构建由审核中心统一触发。
   */
  await publishProjectDocument(projectId.value, document.id);
  MessagePlugin.success(t('project.detail.message.filePublished'));
  await loadData();
}

function canSubmitReview(document: DocumentInfo): boolean {
  /**
   * 仅草稿和驳回状态允许重新提交审核。
   */
  return documentStatusCode(document) !== 'published' && SUBMITTABLE_REVIEW_STATUSES.has(document.review_status);
}

function selectDocument(document: DocumentInfo): void {
  selectedDocument.value = document;
  drawerTab.value = 'basic';
  fillDocumentMetadataForm(document);
  void loadDocumentVersions(document);
  documentDetailVisible.value = true;
}

function closeDocumentDetail(): void {
  documentDetailVisible.value = false;
}

function openDocumentPreview(document: DocumentInfo): void {
  if (!canPreviewDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noPreviewPermission'));
    return;
  }
  openProjectDocumentDetail(document.id);
}

function openRecentDocument(document: RecentDocumentDisplayItem): void {
  if (!canViewDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noViewDocumentPermission'));
    return;
  }
  openProjectDocumentDetail(document.id);
}

function openProjectDocumentDetail(documentId: number): void {
  const targetProjectId = currentProjectId.value;
  if (targetProjectId === null) {
    router.push(withBreadcrumbContext(route, `/documents/${documentId}`));
    return;
  }
  router.push(withBreadcrumbContext(route, `/documents/${documentId}`));
}

async function downloadDocument(document: DocumentInfo): Promise<void> {
  if (!canDownloadDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noDownloadPermission'));
    return;
  }
  const blob = await downloadDocumentVersion(document.id, document.version_no);
  triggerBlobDownload(blob, document.file_name);
}

function openVersionUploadDialog(): void {
  if (!selectedDocument.value) return;
  if (!canCreateDocumentVersion.value) {
    MessagePlugin.warning(t('project.detail.message.noVersionCreatePermission'));
    return;
  }
  versionForm.directory_id = documentDirectoryId(selectedDocument.value);
  versionForm.version_note = '';
  selectedVersionFile.value = null;
  versionDialogVisible.value = true;
}

function handleVersionFileChange(event: Event): void {
  const input = event.target as HTMLInputElement;
  selectedVersionFile.value = input.files?.[0] || null;
}

async function confirmVersionUpload(): Promise<void> {
  if (!selectedDocument.value) return;
  if (!canCreateDocumentVersion.value) {
    MessagePlugin.warning(t('project.detail.message.noVersionCreatePermission'));
    return;
  }
  if (!selectedVersionFile.value) {
    MessagePlugin.warning(t('project.detail.message.selectNewVersionFile'));
    return;
  }
  await createProjectDocumentVersion(projectId.value, selectedDocument.value.id, selectedVersionFile.value, {
    directory_id: versionForm.directory_id,
    category_id: versionForm.directory_id,
    version_note: versionForm.version_note.trim() || null,
  });
  MessagePlugin.success(t('project.detail.message.versionUploaded'));
  versionDialogVisible.value = false;
  await loadData();
}

async function setCurrentVersion(version: DocumentVersionInfo): Promise<void> {
  if (!selectedDocument.value) return;
  if (!canSetCurrentDocumentVersion.value) {
    MessagePlugin.warning(t('project.detail.message.noSetVersionPermission'));
    return;
  }
  await setProjectDocumentCurrentVersion(projectId.value, selectedDocument.value.id, version.id);
  MessagePlugin.success(t('project.detail.message.currentVersionUpdated'));
  await loadData();
  if (selectedDocument.value) {
    await loadDocumentVersions(selectedDocument.value);
  }
}

function removeDocument(document: DocumentInfo): void {
  if (!canDeleteDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noDeleteFilePermission'));
    return;
  }
  deleteTargetDocuments.value = [document];
  deleteDialogVisible.value = true;
}

function openBatchDeleteDialog(): void {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning(t('project.detail.message.selectFiles'));
    return;
  }
  if (!canDeleteDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noDeleteFilePermission'));
    return;
  }
  deleteTargetDocuments.value = [...selectedDocuments.value];
  deleteDialogVisible.value = true;
}

async function confirmDeleteDocuments(): Promise<void> {
  if (!deleteTargetDocuments.value.length) return;
  if (!canDeleteDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noDeleteFilePermission'));
    return;
  }
  deleteSubmitting.value = true;
  try {
    const deletedIds = deleteTargetDocuments.value.map((document) => document.id);
    await Promise.all(deletedIds.map((id) => deleteProjectDocument(projectId.value, id)));
    MessagePlugin.success(t('project.detail.message.deleteSuccess', { count: deletedIds.length }));
    if (selectedDocument.value && deletedIds.includes(selectedDocument.value.id)) {
      selectedDocument.value = null;
      documentDetailVisible.value = false;
    }
    selectedDocumentIds.value = selectedDocumentIds.value.filter((id) => !deletedIds.includes(id));
    deleteTargetDocuments.value = [];
    deleteDialogVisible.value = false;
    await loadData();
  } finally {
    deleteSubmitting.value = false;
  }
}

async function applyBatchRetryParse(): Promise<void> {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning(t('project.detail.message.selectFiles'));
    return;
  }
  if (!canRetryParseDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noRetryParsePermission'));
    return;
  }
  await Promise.all(selectedDocuments.value.map((document) => retryParseProjectDocument(projectId.value, document.id, document.version_no)));
  MessagePlugin.success(t('project.detail.message.batchParseRetryStarted'));
  await loadData();
}

async function retryParse(document: DocumentInfo): Promise<void> {
  if (!canRetryParseDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noRetryParsePermission'));
    return;
  }
  await retryParseProjectDocument(projectId.value, document.id, document.version_no);
  MessagePlugin.success(t('project.detail.message.parseRetryStarted'));
  await loadData();
}

async function retryIndex(document: DocumentInfo): Promise<void> {
  if (!canRetryIndexDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noRetryIndexPermission'));
    return;
  }
  await retryIndexProjectDocument(projectId.value, document.id, document.version_no);
  MessagePlugin.success(t('project.detail.message.indexRetryStarted'));
  await loadData();
}

async function applyBatchRetryIndex(): Promise<void> {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning(t('project.detail.message.selectFiles'));
    return;
  }
  if (!canRetryIndexDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noRetryIndexPermission'));
    return;
  }
  await Promise.all(selectedDocuments.value.map((document) => retryIndexProjectDocument(projectId.value, document.id, document.version_no)));
  MessagePlugin.success(t('project.detail.message.batchIndexRetryStarted'));
  await loadData();
}

async function updateSelectedDocumentSecurity(): Promise<void> {
  if (!selectedDocument.value) return;
  if (!canUpdateDocumentSecurity.value) {
    MessagePlugin.warning(t('project.detail.message.noSecurityPermission'));
    return;
  }
  await updateProjectDocumentSecurityLevel(projectId.value, selectedDocument.value.id, selectedDocument.value.security_level);
  MessagePlugin.success(t('project.detail.message.securityUpdated'));
  await loadData();
}

async function applyBatchSecurityLevel(): Promise<void> {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning(t('project.detail.message.selectFiles'));
    return;
  }
  if (!canUpdateDocumentSecurity.value) {
    MessagePlugin.warning(t('project.detail.message.noSecurityPermission'));
    return;
  }
  await Promise.all(selectedDocumentIds.value.map((id) => updateProjectDocumentSecurityLevel(projectId.value, id, batchForm.security_level)));
  MessagePlugin.success(t('project.detail.message.batchSecurityUpdated'));
  await loadData();
}

function triggerBlobDownload(blob: Blob, fileName: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = url;
  anchor.download = fileName;
  anchor.click();
  URL.revokeObjectURL(url);
}

function documentDisplayName(document: DocumentInfo): string {
  return document.document_name || document.file_name;
}

function documentDirectoryId(document: DocumentInfo | null): number | null {
  return document?.directory_id || document?.category_id || null;
}

function documentStatusCode(document: DocumentInfo): 'pending_review' | 'published' | string {
  const status = document.status || document.document_status || document.review_status;
  const map: Record<string, 'pending_review' | 'published'> = {
    pending_review: 'pending_review',
    pending: 'pending_review',
    active: 'published',
    published: 'published',
    reviewed: 'published',
    draft: 'pending_review',
    approved: 'published',
    待审核: 'pending_review',
    已发布: 'published',
  };
  return map[status] || status || '';
}

function documentStatusText(document: DocumentInfo): string {
  const status = documentStatusCode(document);
  const map: Record<string, string> = {
    pending_review: 'project.detail.document.statusPendingReview',
    published: 'project.detail.document.statusPublished',
  };
  return map[status] ? t(map[status]) : status || '-';
}

function documentFileStatusTheme(document: DocumentInfo): 'default' | 'primary' | 'success' | 'warning' {
  return documentStatusCode(document) === 'published' ? 'success' : 'warning';
}

function documentParseStatus(document: DocumentInfo | DocumentVersionInfo | null): string {
  const status = document?.parse_status || '';
  const map: Record<string, string> = {
    parsed: 'success',
    success: 'success',
    completed: 'success',
    failed: 'failed',
    fail: 'failed',
    parsing: 'parsing',
    running: 'parsing',
    pending: 'unparsed',
    unparsed: 'unparsed',
    not_parsed: 'unparsed',
  };
  return map[status] || status || 'unparsed';
}

function documentIndexStatus(document: DocumentInfo | DocumentVersionInfo | null): string {
  const status = document?.index_status || '';
  const map: Record<string, string> = {
    indexed: 'indexed',
    success: 'indexed',
    completed: 'indexed',
    failed: 'failed',
    fail: 'failed',
    indexing: 'indexing',
    running: 'indexing',
    pending: 'not_indexed',
    not_indexed: 'not_indexed',
    unindexed: 'not_indexed',
  };
  return map[status] || status || 'not_indexed';
}

function documentEmbeddingStatus(document: DocumentInfo | null): string {
  const indexStatus = documentIndexStatus(document);
  if (indexStatus === 'indexed') return t('status.project.ready');
  if (indexStatus === 'failed') return t('status.failed');
  if (indexStatus === 'indexing') return t('status.project.building');
  return t('status.pending');
}

function documentChunkCount(document: DocumentInfo | null): number | string {
  if (!document) return '-';
  const extra = document as DocumentInfo & { chunk_count?: number; chunks_count?: number; indexed_chunk_count?: number };
  return extra.chunk_count ?? extra.chunks_count ?? extra.indexed_chunk_count ?? '-';
}

function documentVersionLabel(document: DocumentInfo | DocumentVersionInfo | null): string {
  if (!document) return '-';
  return String(document.version || document.version_no || '-').startsWith('v')
    ? String(document.version || document.version_no)
    : `v${document.version || document.version_no || '-'}`;
}

function documentUploader(document: DocumentInfo | DocumentVersionInfo): string {
  const displayUser = document as DocumentInfo & { uploader_name?: string | null; uploader_username?: string | null };
  if (displayUser.uploader_name) return displayUser.uploader_name;
  if (displayUser.uploader_username) return displayUser.uploader_username;
  return String(document.upload_user_id || document.created_by || '-');
}

function isPublishedDocument(document: DocumentInfo): boolean {
  return documentStatusCode(document) === 'published';
}

function fillDocumentMetadataForm(document: DocumentInfo): void {
  Object.assign(metadataForm, {
    document_name: documentDisplayName(document),
    directory_id: documentDirectoryId(document),
    document_type: document.document_type || '',
    discipline: document.discipline || '',
    version: String(document.version || document.version_no || ''),
    remark: document.remark || '',
  });
}

async function saveSelectedDocumentMetadata(): Promise<void> {
  if (!selectedDocument.value) return;
  if (!canUpdateDocumentMetadata.value) {
    MessagePlugin.warning(t('project.detail.message.noMetadataPermission'));
    return;
  }
  if (!metadataForm.document_name.trim()) {
    MessagePlugin.warning(t('project.detail.message.enterFileName'));
    return;
  }
  if (!metadataForm.directory_id) {
    MessagePlugin.warning(t('project.detail.message.selectParentDirectory'));
    return;
  }
  const updated = await updateProjectDocument(projectId.value, selectedDocument.value.id, {
    document_name: metadataForm.document_name.trim(),
    directory_id: metadataForm.directory_id,
    category_id: metadataForm.directory_id,
    document_type: metadataForm.document_type || null,
    discipline: metadataForm.discipline || null,
    version: metadataForm.version.trim() || null,
    remark: metadataForm.remark.trim() || null,
  });
  selectedDocument.value = updated;
  fillDocumentMetadataForm(updated);
  MessagePlugin.success(t('project.detail.message.metadataSaved'));
  await loadData();
}

async function loadDocumentVersions(document: DocumentInfo): Promise<void> {
  if (!canViewDocumentVersions.value) {
    documentVersions.value = [];
    return;
  }
  try {
    documentVersions.value = await listProjectDocumentVersions(projectId.value, document.id);
  } catch (error) {
    documentVersions.value = [];
    MessagePlugin.warning(error instanceof Error ? error.message : t('project.detail.message.versionLoadFailed'));
  }
}

function openCreateCategoryDialog(): void {
  if (!canCreateCategories.value) {
    MessagePlugin.warning(t('project.detail.message.noCreateDirectoryPermission'));
    return;
  }
  /**
   * 新建项目资料目录，默认挂在当前选中目录下。
   */
  categoryDialogMode.value = 'create';
  editingCategoryId.value = null;
  categoryForm.parent_id = activeCategoryId.value;
  categoryForm.name = '';
  categoryForm.code = '';
  categoryForm.description = '';
  categoryForm.sort_order = 0;
  categoryForm.enabled = true;
  categoryForm.default_security_level = clampSecurityLevel(project.value?.security_level, authStore.maxSecurityLevel);
  categoryDialogVisible.value = true;
}

function openEditCategoryDialog(): void {
  if (!canEditCategories.value) {
    MessagePlugin.warning(t('project.detail.message.noEditDirectoryPermission'));
    return;
  }
  /**
   * 编辑当前选中的项目资料目录。
   */
  const category = findCategory(categories.value, activeCategoryId.value);
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
  categoryForm.default_security_level = category.default_security_level || project.value?.security_level || 'internal';
  categoryDialogVisible.value = true;
}

async function confirmCategoryDialog(): Promise<void> {
  if (categoryDialogMode.value === 'create' && !canCreateCategories.value) {
    MessagePlugin.warning(t('project.detail.message.noCreateDirectoryPermission'));
    return;
  }
  if (categoryDialogMode.value === 'edit' && !canEditCategories.value) {
    MessagePlugin.warning(t('project.detail.message.noEditDirectoryPermission'));
    return;
  }
  /**
   * 保存项目资料目录配置，后端会按项目隔离校验父级和编码。
   */
  if (!categoryForm.name.trim()) {
    MessagePlugin.warning(t('project.detail.message.enterDirectoryName'));
    return;
  }
  const code = categoryForm.code.trim() || `project-${projectId.value}-${Date.now()}`;
  const payload = {
    parent_id: categoryForm.parent_id,
    name: categoryForm.name.trim(),
    code,
    description: categoryForm.description.trim(),
    sort_order: Number(categoryForm.sort_order) || 0,
    enabled: categoryForm.enabled,
    default_security_level: categoryForm.default_security_level,
  };

  if (categoryDialogMode.value === 'create') {
    await createProjectDirectory(projectId.value, payload);
  } else if (editingCategoryId.value) {
    await updateProjectDirectory(projectId.value, editingCategoryId.value, payload);
  }
  MessagePlugin.success(t('project.detail.message.directorySaved'));
  categoryDialogVisible.value = false;
  await loadData();
}

async function removeActiveCategory(): Promise<void> {
  if (!canDeleteCategories.value) {
    MessagePlugin.warning(t('project.detail.message.noDeleteDirectoryPermission'));
    return;
  }
  /**
   * 删除当前目录。后端只允许删除无子级、无文档引用的目录。
   */
  if (!activeCategoryId.value) {
    MessagePlugin.warning(t('project.detail.message.selectDirectoryFirst'));
    return;
  }
  await deleteProjectDirectory(projectId.value, activeCategoryId.value);
  MessagePlugin.success(t('project.detail.message.directoryDeleted'));
  activeCategoryId.value = null;
  await loadData();
}

function openProjectChat(): void {
  if (!canAskProjectChat.value || !authStore.hasActionPermission(PERMISSIONS.AI_PROJECT_CHAT_VIEW)) {
    MessagePlugin.warning(t('project.detail.message.noProjectChatPermission'));
    return;
  }
  if (!authStore.hasMenuPermission(PERMISSIONS.AI_PROJECT_CHAT)) {
    MessagePlugin.warning(t('project.detail.message.noProjectChatPagePermission'));
    return;
  }
  const targetProjectId = currentProjectId.value;
  if (!targetProjectId) {
    MessagePlugin.warning(t('project.detail.message.invalidProjectIdForChat'));
    return;
  }
  router.push(withBreadcrumbContext(route, { path: ROUTE_PATHS.aiProjectChat, query: { projectId: String(targetProjectId) } }));
}

function openProjectDocumentManagement(focusDirectories = false): void {
  if (!canViewDocuments.value) {
    MessagePlugin.warning(t('project.detail.message.noDocumentManagePermission'));
    return;
  }
  const targetProjectId = currentProjectId.value;
  if (!targetProjectId) {
    MessagePlugin.warning(t('project.detail.message.invalidProjectIdForDocuments'));
    return;
  }
  router.push(
    withBreadcrumbContext(route, {
      path: `/projects/${targetProjectId}/documents`,
      query: focusDirectories ? { focus: 'directories' } : undefined,
    }),
  );
}

function openPendingReviewDocuments(): void {
  if (!authStore.hasActionPermission(PERMISSIONS.REVIEW_VIEW) || !authStore.hasMenuPermission(PERMISSIONS.REVIEW)) {
    MessagePlugin.warning(t('project.detail.message.noReviewCenterPermission'));
    return;
  }
  const targetProjectId = currentProjectId.value;
  if (!targetProjectId) {
    MessagePlugin.warning(t('project.detail.message.invalidProjectIdForReview'));
    return;
  }
  router.push(
    withBreadcrumbContext(route, {
      path: ROUTE_PATHS.reviews,
      query: {
        tab: 'tasks',
        projectId: String(targetProjectId),
        status: REVIEW_TASK_STATUS.reviewing,
      },
    }),
  );
}

onMounted(loadData);
</script>

<template>
  <PageContainer class="project-detail-page" title="">
    <div v-if="!canViewProjectDetail" class="panel-stack project-detail-stack data-scroll">
      <t-card class="project-state-card">
        <t-empty :description="t('project.message.noDetailPermission')" />
      </t-card>
    </div>

    <div v-else-if="loading" class="panel-stack project-detail-stack data-scroll">
      <t-card class="project-state-card">
        <div class="project-state-content">
          <t-loading :text="t('project.detail.loading')" />
        </div>
      </t-card>
    </div>

    <div v-else-if="!project" class="panel-stack project-detail-stack data-scroll">
      <t-card class="project-state-card">
        <div class="project-state-content">
          <t-empty :description="t('project.detail.notFound')" />
          <t-button variant="outline" @click="router.push('/projects')">{{ t('project.action.backToCenter') }}</t-button>
        </div>
      </t-card>
    </div>

    <div v-else class="project-overview-layout data-scroll">
      <section class="project-profile-panel">
        <div class="project-profile-header">
          <div class="project-title-group">
            <div class="project-title-row">
              <h2>{{ project.project_name || project.name }}</h2>
              <t-tag size="small" variant="light" :theme="projectStatusTheme(project.project_status || project.status)">
                {{ projectStatusLabel(project.project_status || project.status) }}
              </t-tag>
            </div>
            <p>{{ profileText(project.project_short_name || project.project_code || project.code) }}</p>
          </div>
        </div>

        <div class="project-profile-sections">
          <section class="project-profile-section">
            <h3>{{ t('project.detail.section.basic') }}</h3>
            <div class="project-profile-list">
              <div class="project-profile-item">
                <span>{{ t('project.field.shortName') }}</span>
                <strong>{{ profileText(project.project_short_name) }}</strong>
              </div>
              <div class="project-profile-item">
                <span>{{ t('project.field.englishName') }}</span>
                <strong>{{ profileText(project.project_english_name) }}</strong>
              </div>
              <div class="project-profile-item">
                <span>{{ t('project.field.customerName') }}</span>
                <strong>{{ profileText(project.customer_name || project.client) }}</strong>
              </div>
              <div class="project-profile-item">
                <span>{{ t('project.field.ownerName') }}</span>
                <strong>{{ profileText(project.owner_name || project.manager) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>{{ t('project.field.description') }}</span>
                <strong>{{ profileText(project.description) }}</strong>
              </div>
            </div>
          </section>

          <section class="project-profile-section">
            <h3>{{ t('project.detail.section.control') }}</h3>
            <div class="project-profile-list">
              <div class="project-profile-item">
                <span>{{ t('project.field.status') }}</span>
                <strong>
                  <t-tag size="small" variant="light" :theme="projectStatusTheme(project.project_status || project.status)">
                    {{ projectStatusLabel(project.project_status || project.status) }}
                  </t-tag>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>{{ t('project.field.securityLevel') }}</span>
                <strong>
                  <t-tag size="small" variant="light" :theme="securityLevelTheme(project.security_level)">
                    {{ securityLevelLabel(project.security_level) }}
                  </t-tag>
                </strong>
              </div>
            </div>
          </section>

          <section class="project-profile-section">
            <h3>{{ t('project.detail.section.properties') }}</h3>
            <div class="project-profile-list">
              <div class="project-profile-item">
                <span>{{ t('project.field.projectType') }}</span>
                <strong>
                  <t-tag v-if="project.project_type" size="small" variant="light" :theme="projectFieldTagTheme('project_type')">
                    {{ project.project_type }}
                  </t-tag>
                  <template v-else>-</template>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>{{ t('project.field.projectStage') }}</span>
                <strong>
                  <t-tag v-if="project.project_stage" size="small" variant="light" :theme="projectFieldTagTheme('project_stage')">
                    {{ project.project_stage }}
                  </t-tag>
                  <template v-else>-</template>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>{{ t('project.field.rawMaterialType') }}</span>
                <strong>
                  <t-tag v-if="project.raw_material_type" size="small" variant="light" :theme="projectFieldTagTheme('raw_material_type')">
                    {{ project.raw_material_type }}
                  </t-tag>
                  <template v-else>-</template>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>{{ t('project.field.capacity') }}</span>
                <strong>{{ profileText(project.capacity) }}</strong>
              </div>
            </div>
          </section>

          <section class="project-profile-section">
            <h3>{{ t('project.detail.section.delivery') }}</h3>
            <div class="project-profile-list">
              <div class="project-profile-item project-profile-item--wide">
                <span>{{ t('project.field.processRoute') }}</span>
                <strong>{{ profileText(project.process_route) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>{{ t('project.field.mainProducts') }}</span>
                <strong>{{ profileText(project.main_products) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>{{ t('project.field.scope') }}</span>
                <strong>{{ profileText(project.scope_description) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>{{ t('project.field.deliverables') }}</span>
                <strong>{{ profileText(project.deliverables) }}</strong>
              </div>
            </div>
          </section>
        </div>
      </section>

      <section class="project-overview-main">
        <div class="overview-band overview-stat-band">
          <div class="overview-section-heading">
            <h3>{{ t('project.detail.section.stats') }}</h3>
            <t-space class="overview-action-group" size="small">
              <t-button variant="outline" @click="router.push('/projects')">{{ t('project.action.backToCenter') }}</t-button>
              <t-button v-if="canOpenProjectChat" variant="outline" @click="openProjectChat">{{ t('project.action.projectChat') }}</t-button>
              <t-button v-if="canEditProject" theme="primary" variant="outline" @click="openProjectDialog">{{ t('project.action.editProject') }}</t-button>
            </t-space>
          </div>
          <div class="overview-stat-grid">
            <button
              type="button"
              class="overview-stat-card overview-stat-card--blue"
              :class="{ 'is-clickable': canOpenProjectDocuments }"
              :disabled="!canOpenProjectDocuments"
              :aria-label="t('project.detail.aria.viewDocumentCount')"
              @click="openProjectDocumentManagement()"
            >
              <div class="overview-stat-icon">
                <FolderIcon />
              </div>
              <div>
                <span>{{ t('project.detail.field.documentCount') }}</span>
                <strong>{{ project.document_count }}</strong>
              </div>
            </button>
            <button
              type="button"
              class="overview-stat-card overview-stat-card--green"
              :class="{ 'is-clickable': canOpenProjectChat }"
              :disabled="!canOpenProjectChat"
              :aria-label="t('project.detail.aria.openProjectChat')"
              @click="openProjectChat"
            >
              <div class="overview-stat-icon">
                <ChatBubbleHelpIcon />
              </div>
              <div>
                <span>{{ t('project.detail.field.qaCount') }}</span>
                <strong>{{ project.qa_count ?? 0 }}</strong>
              </div>
            </button>
            <button
              type="button"
              class="overview-stat-card overview-stat-card--blue"
              :class="{ 'is-clickable': canOpenPendingReviewDocuments }"
              :disabled="!canOpenPendingReviewDocuments"
              :aria-label="t('project.detail.aria.viewPendingReviewDocuments')"
              @click="openPendingReviewDocuments"
            >
              <div class="overview-stat-icon">
                <TaskCheckedIcon />
              </div>
              <div>
                <span>{{ t('project.detail.field.pendingReviewDocuments') }}</span>
                <strong>{{ project.pending_review_document_count }}</strong>
              </div>
            </button>
          </div>
        </div>

        <div class="overview-band overview-directory-band">
          <div class="overview-section-heading">
            <h3>{{ t('project.detail.section.directories') }}</h3>
            <t-button
              v-if="canOpenProjectDocuments"
              class="overview-heading-action"
              size="small"
              theme="default"
              variant="outline"
              @click="openProjectDocumentManagement(true)"
            >
              <template #icon><FolderIcon /></template>
              {{ t('project.action.viewAllDirectories') }}
            </t-button>
          </div>
          <div class="overview-directory-list">
            <button
              v-for="row in overviewDirectoryRows"
              :key="row.key"
              type="button"
              class="overview-directory-row"
              :class="{ 'is-disabled': !row.enabled }"
              :style="{ paddingLeft: `${14 + row.level * 22}px` }"
              @click="row.children.length && toggleOverviewDirectory(row.key)"
            >
              <span class="overview-directory-name">
                <span v-if="row.children.length" class="overview-directory-toggle">
                  <ChevronDownSIcon v-if="isOverviewDirectoryExpanded(row.key)" />
                  <ChevronRightSIcon v-else />
                </span>
                <span v-else class="overview-directory-toggle overview-directory-toggle--empty"></span>
                <span>{{ row.name }}</span>
              </span>
              <strong>{{ row.count }}</strong>
            </button>
          </div>
        </div>

        <div class="overview-band overview-recent-band">
          <div class="overview-section-heading">
            <h3>{{ t('project.detail.section.recentUploads') }}</h3>
            <t-button
              v-if="canOpenProjectDocuments"
              class="overview-heading-action"
              size="small"
              theme="default"
              variant="outline"
              @click="openProjectDocumentManagement()"
            >
              <template #icon><FileSearchIcon /></template>
              {{ t('project.action.documentManagement') }}
            </t-button>
          </div>
          <div v-if="recentUploadDocuments.length" class="recent-upload-list">
            <button
              v-for="document in recentUploadDocuments"
              :key="document.id"
              type="button"
              class="recent-upload-row"
              :disabled="!canViewDocuments"
              @click="openRecentDocument(document)"
            >
              <div class="recent-file-icon" :class="`recent-file-icon--${document.tone}`">
                <component :is="document.icon" />
              </div>
              <div class="recent-file-main">
                <span>{{ document.name }}</span>
                <small>{{ document.fileType }} · {{ document.fileSize }}</small>
              </div>
              <div class="recent-file-meta">
                <span>{{ document.uploadedAt }}</span>
                <strong>{{ document.uploader }}</strong>
              </div>
            </button>
          </div>
          <t-empty v-else :description="t('project.detail.emptyRecentUploads')" />
        </div>
      </section>
    </div>

    <t-drawer
      v-if="canViewDocuments"
      v-model:visible="documentDetailVisible"
      class="project-document-drawer drawer-scroll"
      :header="t('project.detail.document.drawerTitle')"
      placement="right"
      size="min(760px, 96vw)"
      :footer="false"
      @close="closeDocumentDetail"
    >
      <t-empty v-if="!selectedDocument" :description="t('project.detail.document.selectFile')" />
      <div v-else class="document-detail-panel">
        <div class="drawer-file-header">
          <div class="file-type-badge">{{ selectedDocument.file_type || 'FILE' }}</div>
          <div class="drawer-file-title">
            <div>{{ documentDisplayName(selectedDocument) }}</div>
            <span>{{ selectedDocument.category_path || selectedDocument.category_name || '-' }}</span>
          </div>
        </div>

        <div class="drawer-tabs">
          <button :class="{ active: drawerTab === 'basic' }" type="button" @click="drawerTab = 'basic'">{{ t('project.detail.document.tabBasic') }}</button>
          <button :class="{ active: drawerTab === 'versions' }" type="button" @click="drawerTab = 'versions'">{{ t('project.detail.document.tabVersions') }}</button>
          <button :class="{ active: drawerTab === 'parse' }" type="button" @click="drawerTab = 'parse'">{{ t('project.detail.document.tabParse') }}</button>
          <button :class="{ active: drawerTab === 'index' }" type="button" @click="drawerTab = 'index'">{{ t('project.detail.document.tabIndex') }}</button>
        </div>

        <div class="drawer-action-row">
          <t-button v-if="canPreviewDocuments" variant="outline" @click="openDocumentPreview(selectedDocument)">
            <template #icon><FileSearchIcon /></template>
            {{ t('common.action.preview') }}
          </t-button>
          <t-button v-if="canDownloadDocuments" variant="outline" @click="downloadDocument(selectedDocument)">
            <template #icon><DownloadIcon /></template>
            {{ t('common.action.download') }}
          </t-button>
          <t-button
            v-if="canRetryParseDocuments"
            theme="primary"
            variant="outline"
            :disabled="documentParseStatus(selectedDocument) !== 'failed'"
            @click="retryParse(selectedDocument)"
          >
            <template #icon><RefreshIcon /></template>
            {{ t('project.detail.document.retryParse') }}
          </t-button>
          <t-button
            v-if="canRetryIndexDocuments"
            theme="primary"
            variant="outline"
            :disabled="documentIndexStatus(selectedDocument) !== 'failed'"
            @click="retryIndex(selectedDocument)"
          >
            <template #icon><RefreshIcon /></template>
            {{ t('project.detail.document.retryIndex') }}
          </t-button>
          <t-button v-if="canCreateDocumentVersion" theme="primary" @click="openVersionUploadDialog">
            <template #icon><AddIcon /></template>
            {{ t('project.detail.upload.versionTitle') }}
          </t-button>
        </div>

        <div v-if="drawerTab === 'basic'" class="drawer-tab-panel">
          <section class="drawer-section">
            <div class="drawer-section-title">{{ t('project.detail.document.sectionFile') }}</div>
            <div class="drawer-info-grid">
              <div><span>{{ t('project.detail.document.fieldProject') }}</span><strong>{{ project?.project_name || project?.name || '-' }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldDirectory') }}</span><strong>{{ selectedDocument.category_path || selectedDocument.category_name || '-' }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldType') }}</span><strong>{{ selectedDocument.document_type || selectedDocument.file_type || '-' }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldDiscipline') }}</span><strong>{{ selectedDocument.discipline || '-' }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldVersion') }}</span><strong>{{ documentVersionLabel(selectedDocument) }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldCurrentVersion') }}</span><strong>{{ (selectedDocument.is_current_version ?? selectedDocument.current_version) ? t('project.detail.document.yes') : t('project.detail.document.no') }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldStatus') }}</span><strong>{{ documentStatusText(selectedDocument) }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldSecurity') }}</span><strong>{{ securityLevelLabel(selectedDocument.security_level) }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldUploader') }}</span><strong>{{ documentUploader(selectedDocument) }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldUploadedAt') }}</span><strong>{{ formatDateTime(selectedDocument.created_at) }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldSize') }}</span><strong>{{ formatFileSize(selectedDocument.file_size) }}</strong></div>
              <div><span>{{ t('project.detail.document.fieldRemark') }}</span><strong>{{ selectedDocument.remark || '-' }}</strong></div>
            </div>
            <div v-if="selectedDocument.review_status === 'rejected' && selectedDocument.review_comment" class="reject-reason-panel">
              <div class="reject-reason-title">{{ t('project.detail.document.rejectReason') }}</div>
              <div class="reject-reason-content">{{ selectedDocument.review_comment }}</div>
            </div>
          </section>

          <section class="drawer-section">
            <div class="drawer-section-title">{{ t('project.detail.document.sectionRag') }}</div>
            <div class="rag-status-grid">
              <div><span>{{ t('project.detail.document.parseStatus') }}</span><StatusTag type="generic" :value="documentParseStatus(selectedDocument)" /></div>
              <div><span>{{ t('project.detail.document.indexStatus') }}</span><StatusTag type="index" :value="documentIndexStatus(selectedDocument)" /></div>
              <div><span>Embedding</span><strong>{{ documentEmbeddingStatus(selectedDocument) }}</strong></div>
              <div><span>{{ t('project.detail.document.chunkCount') }}</span><strong>{{ documentChunkCount(selectedDocument) }}</strong></div>
            </div>
          </section>

          <section class="drawer-section">
            <div class="drawer-section-title">{{ t('project.detail.document.sectionEdit') }}</div>
            <t-form label-align="top" class="document-detail-form">
              <t-form-item :label="t('project.detail.document.fileName')">
                <t-input v-model="metadataForm.document_name" :disabled="!canUpdateDocumentMetadata" />
              </t-form-item>
              <div class="drawer-form-grid">
                <t-form-item :label="t('project.detail.document.fieldDirectory')">
                  <t-select v-model="metadataForm.directory_id" :disabled="!canUpdateDocumentMetadata" :placeholder="t('project.detail.message.selectDirectory')">
                    <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
                  </t-select>
                </t-form-item>
                <t-form-item :label="t('project.detail.document.fieldVersion')">
                  <t-input v-model="metadataForm.version" :disabled="!canUpdateDocumentMetadata" />
                </t-form-item>
                <t-form-item :label="t('project.detail.document.fieldType')">
                  <t-select v-model="metadataForm.document_type" :disabled="!canUpdateDocumentMetadata" clearable :placeholder="t('project.detail.upload.typePlaceholder')">
                    <t-option v-for="item in documentTypeOptions" :key="item.value" :value="item.value" :label="item.label" />
                  </t-select>
                </t-form-item>
                <t-form-item :label="t('project.detail.document.fieldDiscipline')">
                  <t-select v-model="metadataForm.discipline" :disabled="!canUpdateDocumentMetadata" clearable :placeholder="t('project.detail.upload.disciplinePlaceholder')">
                    <t-option v-for="item in disciplineOptions" :key="item.value" :value="item.value" :label="item.label" />
                  </t-select>
                </t-form-item>
                <t-form-item :label="t('project.detail.document.fieldStatus')">
                  <t-select v-model="selectedDocument.status" disabled>
                    <t-option v-for="item in documentStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
                  </t-select>
                </t-form-item>
                <t-form-item :label="t('project.detail.document.fieldSecurity')">
                  <t-select v-model="selectedDocument.security_level" :disabled="!canUpdateDocumentSecurity">
                    <t-option
                      v-for="item in securityLevelOptions(authStore.maxSecurityLevel, selectedDocument.security_level)"
                      :key="item.value"
                      :value="item.value"
                      :label="item.label"
                      :disabled="item.disabled"
                    />
                  </t-select>
                </t-form-item>
              </div>
              <t-form-item :label="t('project.detail.document.fieldRemark')">
                <t-textarea v-model="metadataForm.remark" :disabled="!canUpdateDocumentMetadata" :autosize="{ minRows: 3, maxRows: 4 }" />
              </t-form-item>
              <t-space class="document-form-actions">
                <t-button v-if="canUpdateDocumentMetadata" variant="outline" @click="saveSelectedDocumentMetadata">{{ t('project.detail.document.saveMetadata') }}</t-button>
                <t-button v-if="canUpdateDocumentSecurity" variant="outline" @click="updateSelectedDocumentSecurity">{{ t('project.detail.document.saveSecurity') }}</t-button>
              </t-space>
            </t-form>
          </section>
        </div>

        <div v-else-if="drawerTab === 'versions'" class="drawer-tab-panel">
          <section class="drawer-section">
            <div class="drawer-section-heading">
              <div class="drawer-section-title">{{ t('project.detail.document.sectionVersionSnapshot') }}</div>
              <t-button v-if="canCreateDocumentVersion" theme="primary" @click="openVersionUploadDialog">{{ t('project.detail.upload.versionTitle') }}</t-button>
            </div>
            <t-empty v-if="!documentVersions.length" :description="t('project.detail.document.noVersions')" />
            <div v-else class="version-table-wrap">
              <table class="plain-table version-table">
                <thead>
                  <tr>
                    <th>{{ t('project.detail.document.fieldVersion') }}</th>
                    <th>{{ t('project.detail.document.fieldSize') }}</th>
                    <th>{{ t('project.detail.document.fieldStatus') }}</th>
                    <th>{{ t('project.detail.document.parseStatus') }}</th>
                    <th>{{ t('project.detail.document.indexStatus') }}</th>
                    <th>{{ t('project.detail.document.isCurrentVersion') }}</th>
                    <th>{{ t('project.detail.document.fieldUploader') }}</th>
                    <th>{{ t('project.detail.document.fieldUploadedAt') }}</th>
                    <th>{{ t('project.detail.document.versionRemark') }}</th>
                    <th>{{ t('project.detail.document.operation') }}</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="version in documentVersions" :key="version.id">
                    <td>{{ documentVersionLabel(version) }}</td>
                    <td>{{ formatFileSize(version.file_size || 0) }}</td>
                    <td>{{ version.version_status || version.review_status || '-' }}</td>
                    <td><StatusTag type="generic" :value="documentParseStatus(version)" /></td>
                    <td><StatusTag type="index" :value="documentIndexStatus(version)" /></td>
                    <td>{{ version.is_current || version.is_current_version ? t('project.detail.document.yes') : t('project.detail.document.no') }}</td>
                    <td>{{ documentUploader(version) }}</td>
                    <td>{{ formatDateTime(version.created_at) }}</td>
                    <td>{{ version.version_note || version.change_summary || '-' }}</td>
                    <td>
                      <t-button
                        v-if="canSetCurrentDocumentVersion && !(version.is_current || version.is_current_version)"
                        size="small"
                        variant="outline"
                        @click="setCurrentVersion(version)"
                      >
                        {{ t('project.detail.document.setCurrentVersion') }}
                      </t-button>
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <div v-else-if="drawerTab === 'parse'" class="drawer-tab-panel">
          <section class="drawer-section">
            <div class="drawer-section-heading">
              <div class="drawer-section-title">{{ t('project.detail.document.sectionParse') }}</div>
              <t-button
                v-if="canRetryParseDocuments"
                variant="outline"
                :disabled="documentParseStatus(selectedDocument) !== 'failed'"
                @click="retryParse(selectedDocument)"
              >
                {{ t('project.detail.document.retryParse') }}
              </t-button>
            </div>
            <div class="drawer-info-grid">
              <div><span>{{ t('project.detail.document.parseStatus') }}</span><strong>{{ parseStatusText(documentParseStatus(selectedDocument)) }}</strong></div>
              <div><span>{{ t('project.detail.document.startTime') }}</span><strong>{{ formatDateTime(selectedDocument.parse_started_at || '') }}</strong></div>
              <div><span>{{ t('project.detail.document.finishTime') }}</span><strong>{{ formatDateTime(selectedDocument.parse_finished_at || '') }}</strong></div>
              <div class="drawer-info-wide"><span>{{ t('project.detail.document.errorInfo') }}</span><strong>{{ selectedDocument.parse_error || '-' }}</strong></div>
              <div class="drawer-info-wide"><span>{{ t('project.detail.document.parseLog') }}</span><strong>{{ selectedDocument.parse_log || '-' }}</strong></div>
            </div>
          </section>
        </div>

        <div v-else class="drawer-tab-panel">
          <section class="drawer-section">
            <div class="drawer-section-heading">
              <div class="drawer-section-title">{{ t('project.detail.document.sectionIndex') }}</div>
              <t-button
                v-if="canRetryIndexDocuments"
                variant="outline"
                :disabled="documentIndexStatus(selectedDocument) !== 'failed'"
                @click="retryIndex(selectedDocument)"
              >
                {{ t('project.detail.document.retryIndex') }}
              </t-button>
            </div>
            <div class="drawer-info-grid">
              <div><span>{{ t('project.detail.document.indexStatus') }}</span><strong>{{ indexStatusText(documentIndexStatus(selectedDocument)) }}</strong></div>
              <div><span>Embedding</span><strong>{{ documentEmbeddingStatus(selectedDocument) }}</strong></div>
              <div><span>{{ t('project.detail.document.chunkCount') }}</span><strong>{{ documentChunkCount(selectedDocument) }}</strong></div>
              <div><span>{{ t('project.detail.document.buildStart') }}</span><strong>{{ formatDateTime(selectedDocument.build_started_at || '') }}</strong></div>
              <div><span>{{ t('project.detail.document.buildFinish') }}</span><strong>{{ formatDateTime(selectedDocument.build_finished_at || '') }}</strong></div>
              <div class="drawer-info-wide"><span>{{ t('project.detail.document.buildError') }}</span><strong>{{ selectedDocument.build_error || '-' }}</strong></div>
            </div>
          </section>
        </div>
      </div>
    </t-drawer>

    <t-dialog v-model:visible="uploadDialogVisible" :header="t('project.detail.upload.title')" width="680px" :confirm-loading="uploading" @confirm="confirmUpload">
      <div class="upload-dialog-content">
        <div class="version-rule">
          {{ t('project.detail.upload.rule') }}
        </div>
        <t-form-item :label="t('project.detail.upload.file')" required-mark>
          <div class="upload-dropzone" @click="browseUploadFiles" @dragover.prevent @drop.prevent="handleUploadDrop">
            <input
              ref="uploadInputRef"
              class="hidden-file-input"
              type="file"
              multiple
              accept=".txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf,.zip,.rar"
              @change="handleFileChange"
            />
            <div class="upload-cloud">↑</div>
            <strong>{{ t('project.detail.upload.dropTitle') }}</strong>
            <span>{{ t('project.detail.upload.dropHint') }}</span>
          </div>
          <div v-if="selectedUploadFiles.length" class="upload-file-list">
            <div v-for="(file, index) in selectedUploadFiles" :key="`${file.name}-${file.size}-${index}`" class="upload-file-item">
              <span>{{ file.name }}</span>
              <strong>{{ formatFileSize(file.size) }}</strong>
              <t-button size="small" variant="text" theme="danger" @click.stop="removeUploadFile(index)">{{ t('project.detail.upload.remove') }}</t-button>
            </div>
          </div>
        </t-form-item>
        <t-form label-align="top">
          <div class="upload-form-grid">
            <t-form-item :label="t('project.detail.upload.directory')" required-mark>
              <t-select v-model="uploadForm.category_id" :placeholder="t('project.detail.message.selectDirectory')">
                <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
              </t-select>
            </t-form-item>
            <t-form-item :label="t('project.detail.upload.security')" required-mark>
              <t-select v-model="uploadForm.security_level">
                <t-option v-for="item in securityLevelOptions(authStore.maxSecurityLevel)" :key="item.value" :value="item.value" :label="item.label" />
              </t-select>
            </t-form-item>
            <t-form-item :label="t('project.detail.document.fieldType')">
              <t-select v-model="uploadForm.document_type" clearable :placeholder="t('project.detail.upload.typePlaceholder')">
                <t-option v-for="item in documentTypeOptions" :key="item.value" :value="item.value" :label="item.label" />
              </t-select>
            </t-form-item>
            <t-form-item :label="t('project.detail.document.fieldDiscipline')">
              <t-select v-model="uploadForm.discipline" clearable :placeholder="t('project.detail.upload.disciplinePlaceholder')">
                <t-option v-for="item in disciplineOptions" :key="item.value" :value="item.value" :label="item.label" />
              </t-select>
            </t-form-item>
          </div>
          <t-form-item :label="t('project.detail.document.fieldRemark')">
            <t-textarea v-model="uploadForm.remark" :autosize="{ minRows: 3, maxRows: 4 }" :placeholder="t('project.detail.upload.remarkPlaceholder')" />
          </t-form-item>
        </t-form>
      </div>
    </t-dialog>

    <t-dialog v-model:visible="versionDialogVisible" :header="t('project.detail.upload.versionTitle')" width="560px" @confirm="confirmVersionUpload">
      <t-form label-align="top">
        <t-form-item :label="t('project.detail.document.fieldDirectory')">
          <t-select v-model="versionForm.directory_id" clearable :placeholder="t('project.detail.upload.directoryPlaceholder')">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
          </t-select>
        </t-form-item>
        <t-form-item :label="t('project.detail.document.versionRemark')">
          <t-textarea v-model="versionForm.version_note" :autosize="{ minRows: 2, maxRows: 4 }" />
        </t-form-item>
        <t-form-item :label="t('project.detail.upload.fileVersion')" required-mark>
          <input type="file" accept=".txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf" @change="handleVersionFileChange" />
          <div v-if="selectedVersionFile" class="selected-file">{{ selectedVersionFile.name }}</div>
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog
      v-model:visible="deleteDialogVisible"
      :header="t('project.detail.deleteFile.title')"
      width="560px"
      theme="warning"
      :confirm-loading="deleteSubmitting"
      :confirm-btn="t('project.detail.deleteFile.confirm')"
      :cancel-btn="t('common.action.cancel')"
      @confirm="confirmDeleteDocuments"
    >
      <div class="delete-confirm-panel">
        <div class="delete-confirm-title">{{ t('project.detail.deleteFile.warning', { count: deleteTargetDocuments.length }) }}</div>
        <div class="delete-impact-box">
          <div>{{ t('project.detail.deleteFile.projectImpact') }}</div>
          <div>{{ t('project.detail.deleteFile.fileImpact') }}</div>
          <div>{{ t('project.detail.deleteFile.indexImpact') }}</div>
          <div>{{ t('project.detail.deleteFile.versionImpact') }}</div>
        </div>
        <div class="delete-file-list">
          <div v-for="document in deleteTargetDocuments" :key="document.id">
            <span>{{ documentDisplayName(document) }}</span>
            <strong>{{ formatFileSize(document.file_size) }}</strong>
          </div>
        </div>
      </div>
    </t-dialog>

    <ProjectFormDrawer
      v-model:visible="projectDialogVisible"
      mode="edit"
      :project="project"
      :saving="projectSaving"
      show-progress
      @submit="confirmProjectDialog"
    />

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
        <t-form-item :label="t('project.detail.directory.description')"><t-textarea v-model="categoryForm.description" /></t-form-item>
        <t-form-item :label="t('project.detail.directory.enabled')"><t-switch v-model="categoryForm.enabled" /></t-form-item>
      </t-form>
    </t-dialog>
  </PageContainer>
</template>

<style scoped>
.project-detail-page {
  padding-top: 16px;
}

.project-detail-page :deep(.toolbar) {
  display: none;
}

.project-detail-stack {
  height: 100%;
  overflow-y: auto;
  padding-bottom: 16px;
}

.project-state-card {
  min-height: 280px;
}

.project-state-card :deep(.t-card__body) {
  display: grid;
  min-height: 280px;
  place-items: center;
}

.project-state-content {
  display: grid;
  justify-items: center;
  gap: 12px;
}

.project-overview-layout {
  display: grid;
  height: 100%;
  min-height: 720px;
  grid-template-columns: minmax(320px, 0.88fr) minmax(520px, 1.12fr);
  overflow: auto;
  border: 1px solid #dbe3ef;
  border-radius: 8px;
  background: #fff;
}

.project-profile-panel {
  min-width: 0;
  border-right: 1px solid #dbe3ef;
  padding: 32px 28px;
  overflow: visible;
}

.project-profile-header {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 22px;
}

.project-title-group {
  display: grid;
  min-width: 0;
  gap: 8px;
}

.project-title-row {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.project-title-row h2 {
  margin: 0;
  color: #0b1f44;
  font-size: 26px;
  font-weight: 800;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.project-title-group p {
  margin: 0;
  color: #697999;
  font-size: 16px;
  font-weight: 600;
}

.project-profile-sections {
  display: grid;
  gap: 22px;
}

.project-profile-section {
  display: grid;
  gap: 12px;
}

.project-profile-section + .project-profile-section {
  border-top: 1px solid #e7edf5;
  padding-top: 20px;
}

.project-profile-section h3 {
  margin: 0;
  color: #0b1f44;
  font-size: 16px;
  font-weight: 800;
  line-height: 1.4;
}

.project-profile-list {
  display: grid;
  gap: 12px;
}

.project-profile-item {
  display: grid;
  grid-template-columns: 104px minmax(0, 1fr);
  gap: 22px;
  align-items: start;
}

.project-profile-item span {
  color: #71809e;
  font-size: 15px;
  font-weight: 600;
  line-height: 1.6;
}

.project-profile-item strong {
  min-width: 0;
  color: #10203f;
  font-size: 15px;
  font-weight: 700;
  line-height: 1.65;
  overflow-wrap: anywhere;
}

.project-profile-item--wide strong {
  font-weight: 600;
}

.project-overview-main {
  display: grid;
  min-width: 0;
  align-content: start;
  grid-template-rows: auto auto auto;
  overflow: visible;
}

.overview-band {
  min-width: 0;
  padding: 28px 34px;
}

.overview-band + .overview-band {
  border-top: 1px solid #dbe3ef;
}

.overview-section-heading {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.overview-section-heading h3 {
  margin: 0;
  color: #0b1f44;
  font-size: 24px;
  font-weight: 800;
  line-height: 1.3;
}

.overview-heading-action {
  height: 32px;
  flex: 0 0 auto;
  border-color: #cdd8e7;
  border-radius: 6px;
  background: #fff;
  color: #1d4f91;
  font-size: 14px;
  font-weight: 700;
  padding: 0 12px;
  white-space: nowrap;
}

.overview-heading-action:hover {
  border-color: #80b2f5;
  background: #f5f9ff;
  color: #0052d9;
}

.overview-heading-action:active {
  border-color: #4b91ed;
  background: #eaf3ff;
}

.overview-heading-action:focus-visible {
  outline: 2px solid #8bb7ff;
  outline-offset: 2px;
}

.overview-heading-action :deep(.t-button__text) {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.overview-heading-action :deep(svg) {
  width: 16px;
  height: 16px;
  color: currentcolor;
}

.overview-action-group {
  flex-wrap: wrap;
  justify-content: flex-end;
}

.overview-stat-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 28px;
}

.overview-stat-card {
  display: grid;
  width: 100%;
  min-height: 112px;
  grid-template-columns: 50px minmax(0, 1fr);
  align-items: center;
  gap: 20px;
  border: 1px solid transparent;
  border-radius: 8px;
  background: #f5f8fd;
  color: inherit;
  cursor: default;
  font: inherit;
  padding: 18px 22px;
  text-align: left;
  transition:
    border-color 0.18s ease,
    background-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.overview-stat-card:disabled {
  opacity: 1;
}

.overview-stat-card.is-clickable {
  cursor: pointer;
}

.overview-stat-card.is-clickable:hover {
  border-color: #bbd7ff;
  box-shadow: 0 8px 18px rgb(15 62 118 / 10%);
  transform: translateY(-1px);
}

.overview-stat-card.is-clickable:active {
  box-shadow: 0 4px 10px rgb(15 62 118 / 8%);
  transform: translateY(0);
}

.overview-stat-card:focus-visible {
  outline: 2px solid #8bb7ff;
  outline-offset: 2px;
}

.overview-stat-card--blue {
  background: #f3f7ff;
}

.overview-stat-card--green {
  background: #f2fbf6;
}

.overview-stat-icon {
  display: grid;
  width: 50px;
  height: 58px;
  place-items: center;
  border-radius: 8px;
  background: #e4efff;
  color: #2169f3;
}

.overview-stat-card--green .overview-stat-icon {
  background: #dff5e9;
  color: #1f9e59;
}

.overview-stat-icon :deep(svg) {
  width: 28px;
  height: 28px;
}

.overview-stat-card span {
  color: #4f5f7c;
  font-size: 15px;
  font-weight: 700;
}

.overview-stat-card strong {
  display: block;
  margin-top: 8px;
  color: #08183a;
  font-size: 30px;
  font-weight: 800;
  line-height: 1;
}

.overview-directory-band {
  display: flex;
  min-height: 0;
  flex-direction: column;
}

.overview-directory-list {
  display: grid;
  min-height: 0;
  gap: 0;
  overflow: visible;
}

.overview-directory-row {
  display: flex;
  width: 100%;
  min-height: 44px;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  border: 0;
  border-bottom: 1px solid #e7edf5;
  background: transparent;
  color: #17233f;
  cursor: pointer;
  font: inherit;
  padding-top: 0;
  padding-right: 0;
  padding-bottom: 0;
  text-align: left;
}

.overview-directory-row:hover {
  background: #f7faff;
}

.overview-directory-row.is-disabled {
  color: #94a3b8;
}

.overview-directory-name {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  overflow: hidden;
}

.overview-directory-name > span:last-child {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overview-directory-toggle {
  display: grid;
  width: 16px;
  height: 16px;
  flex: 0 0 auto;
  place-items: center;
  color: #667997;
}

.overview-directory-toggle :deep(svg) {
  width: 16px;
  height: 16px;
}

.overview-directory-toggle--empty {
  opacity: 0;
}

.overview-directory-row strong {
  flex: 0 0 auto;
  color: #17233f;
  font-size: 16px;
  font-weight: 800;
}

.overview-recent-band {
  padding-bottom: 26px;
}

.recent-upload-list {
  display: grid;
  gap: 12px;
}

.recent-upload-row {
  display: grid;
  width: 100%;
  min-height: 42px;
  grid-template-columns: 28px minmax(0, 1fr) minmax(170px, auto);
  align-items: center;
  gap: 12px;
  border: 0;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font: inherit;
  padding: 4px 6px;
  text-align: left;
  transition:
    background-color 0.18s ease,
    box-shadow 0.18s ease;
}

.recent-upload-row:hover {
  background: #f7faff;
}

.recent-upload-row:active {
  background: #eef6ff;
}

.recent-upload-row:focus-visible {
  outline: 2px solid #8bb7ff;
  outline-offset: 2px;
}

.recent-upload-row:disabled {
  cursor: default;
}

.recent-upload-row:disabled:hover {
  background: transparent;
}

.recent-file-icon {
  display: grid;
  width: 22px;
  height: 22px;
  place-items: center;
  border-radius: 5px;
}

.recent-file-icon :deep(svg) {
  width: 22px;
  height: 22px;
}

.recent-file-icon--blue {
  color: #1f6feb;
}

.recent-file-icon--green {
  color: #2fb66d;
}

.recent-file-icon--orange {
  color: #e0852d;
}

.recent-file-icon--red {
  color: #d44f4f;
}

.recent-file-icon--gray {
  color: #64748b;
}

.recent-file-main {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.recent-file-main span {
  min-width: 0;
  overflow: hidden;
  color: #1260d6;
  font-size: 15px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recent-file-main small,
.recent-file-meta span {
  color: #71809e;
  font-size: 13px;
}

.recent-file-meta {
  display: grid;
  justify-items: end;
  gap: 3px;
  color: #71809e;
  font-size: 13px;
}

.recent-file-meta strong {
  color: #445674;
  font-size: 14px;
  font-weight: 700;
}

.project-info-section {
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 16px 24px;
}

.section-title {
  margin-bottom: 12px;
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
}

.project-info-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 0 24px;
}

.info-cell {
  display: grid;
  min-height: 52px;
  align-content: center;
  gap: 4px;
  border-bottom: 1px solid #edf2f7;
  padding: 8px 0;
}

.info-cell--wide {
  grid-column: span 2;
}

.info-cell span {
  color: #64748b;
  font-size: 13px;
}

.info-cell strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.detail-kpi-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.detail-kpi {
  display: flex;
  align-items: center;
  gap: 18px;
  min-height: 82px;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 14px 22px;
}

.detail-kpi-icon {
  display: grid;
  width: 56px;
  height: 56px;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 8px;
  font-size: 26px;
  font-weight: 800;
}

.detail-kpi-icon :deep(svg) {
  width: 30px;
  height: 30px;
}

.detail-kpi--blue .detail-kpi-icon {
  background: #edf5ff;
  color: #2563eb;
}

.detail-kpi--green .detail-kpi-icon {
  background: #eaf8ef;
  color: #16a34a;
}

.detail-kpi--purple .detail-kpi-icon {
  background: #f1edff;
  color: #7c3aed;
}

.detail-kpi--orange .detail-kpi-icon {
  background: #fff4e8;
  color: #f97316;
}

.detail-kpi span {
  color: #64748b;
  font-size: 14px;
}

.detail-kpi strong {
  display: block;
  margin-top: 4px;
  color: #0f172a;
  font-size: 28px;
  font-weight: 800;
}

.project-overview-card {
  flex: 0 0 auto;
}

.project-overview-card :deep(.t-card__body) {
  padding: 16px 24px;
}

.project-workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr);
  gap: 16px;
  align-items: stretch;
  flex: 1 0 520px;
  min-height: 520px;
}

.project-workspace--documents-only {
  grid-template-columns: minmax(0, 1fr);
}

.detail-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px 12px;
}

.detail-item {
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid #edf0f5;
  border-radius: 6px;
  background: #fff;
}

.detail-item.wide {
  grid-column: span 2;
}

.detail-label {
  color: #64748b;
  font-size: 12px;
}

.detail-value {
  margin-top: 4px;
  color: #111827;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.document-card :deep(.t-card__body) {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  gap: 12px;
}

.document-toolbar {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 8px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 14px 16px;
}

.keyword-filter,
.updated-filter {
  min-width: 0;
}

@media (min-width: 1181px) {
  .keyword-filter,
  .updated-filter {
    grid-column: span 2;
  }
}

.batch-toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  border-radius: 6px;
  background: #f8fafc;
  padding: 8px;
}

.batch-select {
  width: 140px;
}

.document-loading-state {
  display: grid;
  min-height: 120px;
  align-items: start;
  justify-items: center;
  border-radius: 6px;
  background: #f8fafc;
  padding-top: 34px;
}

.document-table th,
.document-table td {
  white-space: nowrap;
}

.document-table tr.selected td {
  background: #eff6ff;
}

.selection-col {
  width: 42px;
}

.document-detail-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.project-document-drawer :deep(.t-drawer__body) {
  padding: 20px;
}

.drawer-file-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.file-type-badge {
  display: grid;
  min-width: 44px;
  height: 52px;
  place-items: center;
  border-radius: 6px;
  background: #fee2e2;
  color: #dc2626;
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}

.drawer-file-title {
  display: grid;
  min-width: 0;
  gap: 4px;
}

.drawer-file-title div {
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.drawer-file-title span {
  color: #64748b;
  font-size: 13px;
}

.drawer-tabs {
  display: flex;
  gap: 24px;
  border-bottom: 1px solid #e6ebf2;
}

.drawer-tabs button {
  position: relative;
  border: 0;
  background: transparent;
  color: #475569;
  cursor: pointer;
  font-weight: 700;
  padding: 12px 0;
}

.drawer-tabs button.active {
  color: #2563eb;
}

.drawer-tabs button.active::after {
  position: absolute;
  right: 0;
  bottom: -1px;
  left: 0;
  height: 2px;
  background: #2563eb;
  content: '';
}

.drawer-action-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.drawer-tab-panel {
  display: grid;
  gap: 16px;
}

.drawer-section {
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px;
}

.drawer-section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.drawer-section-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
}

.drawer-info-grid,
.rag-status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px 28px;
}

.drawer-info-grid div,
.rag-status-grid div {
  display: grid;
  gap: 6px;
  min-width: 0;
}

.drawer-info-grid span,
.rag-status-grid span {
  color: #64748b;
  font-size: 13px;
}

.drawer-info-grid strong,
.rag-status-grid strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.reject-reason-panel {
  margin-top: 16px;
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

.drawer-info-wide {
  grid-column: 1 / -1;
}

.version-table-wrap {
  overflow: auto;
}

.version-table th,
.version-table td {
  white-space: nowrap;
}

.document-detail-title {
  color: #111827;
  font-size: 16px;
  font-weight: 700;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.detail-list {
  display: grid;
  gap: 8px;
}

.detail-list div {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  gap: 8px;
  color: #475569;
  font-size: 13px;
}

.detail-list span {
  color: #64748b;
}

.detail-list strong {
  color: #111827;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.document-detail-form {
  padding-top: 0;
}

.drawer-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 10px;
}

.document-form-actions {
  width: 100%;
}

.version-list {
  display: grid;
  gap: 8px;
  border-top: 1px solid #eef2f7;
  padding-top: 12px;
}

.version-list-title {
  color: #111827;
  font-size: 14px;
  font-weight: 700;
}

.version-row {
  display: flex;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  border-radius: 6px;
  background: #f8fafc;
  padding: 8px;
}

.version-row div {
  display: grid;
  min-width: 0;
  gap: 2px;
}

.version-row strong,
.version-row span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.version-row span {
  color: #64748b;
  font-size: 12px;
}

.document-detail-actions {
  width: 100%;
}

.category-card {
  display: flex;
  min-height: 520px;
  flex-direction: column;
}

.category-card :deep(.t-card__body) {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  padding: 12px;
}

.category-tree-scroll {
  flex: 1;
  min-height: 0;
  overflow: auto;
}

.category-readonly-note {
  margin-top: 12px;
  border-top: 1px solid #eef2f7;
  color: #94a3b8;
  font-size: 12px;
  line-height: 1.6;
  padding-top: 12px;
}

.card-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.category-create-button {
  height: 28px;
  border-radius: 6px;
  color: #2563eb;
  font-size: 13px;
  font-weight: 600;
  padding: 0 8px;
}

.category-create-button:hover {
  background: #eff6ff;
}

.category-row {
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

.category-row :deep(.t-button__text) {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.category-row.active {
  background: #eaf4ff;
  color: #0474d8;
  font-weight: 700;
}

.category-row.disabled {
  color: #94a3b8;
}

.category-name {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 4px;
}

.expand-button,
.expand-placeholder {
  display: grid;
  width: 18px;
  height: 18px;
  flex: 0 0 auto;
  place-items: center;
  color: #94a3b8;
}

.category-count {
  color: #94a3b8;
  font-size: 12px;
  font-weight: 500;
}

.category-tools {
  display: flex;
  gap: 8px;
  margin: 12px -12px -12px;
  border-top: 1px solid #eef2f7;
  background: #fbfdff;
  padding: 12px;
}

.category-tool-button {
  flex: 1;
  height: 32px;
  border-color: #d8e3f0;
  border-radius: 6px;
  color: #334155;
  font-weight: 600;
}

.category-tool-button:hover {
  border-color: #93c5fd;
  background: #eff6ff;
  color: #1d4ed8;
}

.category-tool-button.danger {
  border-color: #fecaca;
}

.category-tool-button.danger:hover {
  border-color: #fca5a5;
  background: #fff1f2;
}

.category-tool-button:disabled {
  border-color: #e5e7eb;
  background: #f8fafc;
  color: #94a3b8;
}

.member-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid #edf0f5;
}

.member-name {
  color: #111827;
  font-weight: 700;
}

.selected-file {
  margin-top: 8px;
  color: #475569;
  font-size: 13px;
}

.version-rule {
  color: #475569;
  font-size: 13px;
}

.upload-dialog-content {
  display: grid;
  gap: 16px;
}

.upload-dropzone {
  display: grid;
  min-height: 164px;
  place-items: center;
  gap: 8px;
  border: 1px dashed #7aa7ff;
  border-radius: 6px;
  background: #f7fbff;
  color: #334155;
  cursor: pointer;
  padding: 24px;
  text-align: center;
}

.upload-dropzone strong {
  color: #0f172a;
  font-size: 16px;
}

.upload-dropzone span {
  color: #64748b;
  font-size: 13px;
}

.upload-cloud {
  display: grid;
  width: 48px;
  height: 48px;
  place-items: center;
  border-radius: 50%;
  background: #3b82f6;
  color: #fff;
  font-size: 28px;
  font-weight: 800;
}

.hidden-file-input {
  display: none;
}

.upload-file-list {
  display: grid;
  gap: 8px;
}

.upload-file-item {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto auto;
  align-items: center;
  gap: 12px;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  padding: 8px 12px;
}

.upload-file-item span {
  overflow: hidden;
  color: #0f172a;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.upload-file-item strong {
  color: #64748b;
  font-size: 12px;
}

.upload-form-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 16px;
}

.delete-confirm-panel {
  display: grid;
  gap: 14px;
}

.delete-confirm-title {
  color: #0f172a;
  font-size: 15px;
  font-weight: 800;
}

.delete-impact-box {
  display: grid;
  gap: 8px;
  border-radius: 6px;
  background: #fff7ed;
  color: #475569;
  font-size: 13px;
  line-height: 1.6;
  padding: 12px 14px;
}

.delete-file-list {
  display: grid;
  max-height: 180px;
  gap: 8px;
  overflow: auto;
}

.delete-file-list div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  padding: 8px 10px;
}

.delete-file-list span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.delete-file-list strong {
  color: #64748b;
  font-size: 12px;
}

@media (max-width: 1180px) {
  .project-overview-layout {
    grid-template-columns: 1fr;
    overflow: auto;
  }

  .project-profile-panel {
    border-right: 0;
    border-bottom: 1px solid #dbe3ef;
  }

  .project-overview-main {
    overflow: visible;
  }

  .project-workspace {
    grid-template-columns: 240px minmax(0, 1fr);
  }

  .project-info-grid,
  .detail-kpi-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 720px) {
  .project-overview-layout {
    min-height: 0;
  }

  .project-profile-panel,
  .overview-band {
    padding: 22px 18px;
  }

  .project-title-row h2 {
    font-size: 22px;
  }

  .project-profile-item,
  .overview-stat-grid,
  .recent-upload-row {
    grid-template-columns: 1fr;
  }

  .overview-section-heading {
    align-items: flex-start;
    flex-direction: column;
  }

  .overview-directory-band .overview-section-heading,
  .overview-recent-band .overview-section-heading {
    align-items: center;
    flex-direction: row;
  }

  .overview-section-heading h3 {
    font-size: 20px;
  }

  .overview-stat-card {
    min-height: 96px;
  }

  .recent-file-meta {
    justify-items: start;
  }

  .project-info-grid,
  .detail-kpi-grid,
  .drawer-info-grid,
  .rag-status-grid,
  .drawer-form-grid,
  .document-toolbar,
  .upload-form-grid,
  .project-workspace {
    grid-template-columns: 1fr;
  }

  .info-cell--wide,
  .drawer-info-wide {
    grid-column: span 1;
  }
}
</style>
