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
  updateProjectDocumentAiEnabled,
  updateProjectDocumentSecurityLevel,
  uploadProjectDocument,
  type ProjectPayload,
} from '@/api/projects';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
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
import { buildCategoryOptions, collectCategoryIds, findCategory } from '@/utils/categories';
import { formatDateTime, formatFileSize } from '@/utils/format';
import { SECURITY_LEVEL_OPTIONS, securityLevelLabel, securityLevelTheme } from '@/utils/securityLevels';
import ProjectFormDrawer from '@/views/project/ProjectFormDrawer.vue';

type CategoryDialogMode = 'create' | 'edit';
type DrawerTab = 'basic' | 'versions' | 'parse' | 'index';

interface CategoryRow {
  category: KnowledgeCategory;
  level: number;
}

interface DirectoryTemplateNode {
  code: string;
  name: string;
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
const PROJECT_STATUS_OPTIONS: ProjectStatus[] = ['待启动', '进行中', '已完成', '已暂停'];
const DOCUMENT_STATUS_OPTIONS = [
  { label: '待审核', value: '待审核' },
  { label: '已发布', value: '已发布' },
];
const PARSE_STATUS_OPTIONS = [
  { label: '未解析', value: 'unparsed' },
  { label: '解析中', value: 'parsing' },
  { label: '成功', value: 'success' },
  { label: '失败', value: 'failed' },
];
const INDEX_STATUS_OPTIONS = [
  { label: '未索引', value: 'not_indexed' },
  { label: '索引中', value: 'indexing' },
  { label: '成功', value: 'indexed' },
  { label: '失败', value: 'failed' },
];
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
const AI_ENABLED_OPTIONS = [
  { label: 'AI 开启', value: 'true' },
  { label: 'AI 关闭', value: 'false' },
];
const ACCEPTED_UPLOAD_EXTENSIONS = new Set(['txt', 'md', 'csv', 'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'odt', 'odp', 'ods', 'rtf', 'zip', 'rar']);
const DEFAULT_PROJECT_DIRECTORY_TEMPLATE: DirectoryTemplateNode[] = [
  {
    code: 'A',
    name: '项目管理',
    children: [
      { code: 'A01', name: '项目合同文件', children: [] },
      { code: 'A02', name: '项目程序文件', children: [] },
      { code: 'A03', name: '项目组织机构与通讯录', children: [] },
      { code: 'A04', name: 'WBS', children: [] },
      { code: 'A05', name: '项目模板文件', children: [] },
      { code: 'A06', name: '项目进度计划', children: [] },
      { code: 'A07', name: '项目月报', children: [] },
      { code: 'A08', name: '会议纪要', children: [] },
    ],
  },
  {
    code: 'E',
    name: '设计资料',
    children: [
      { code: 'E01', name: '设计输入资料', children: [] },
      { code: 'E02', name: '设计基础', children: [] },
      { code: 'E03', name: '设计成品文件', children: [] },
      { code: 'E04', name: '厂商资料', children: [] },
    ],
  },
  {
    code: 'D',
    name: '专业资料',
    children: [
      { code: '00', name: '项目统一规定', children: [] },
      { code: '01', name: '工艺', children: [] },
      { code: '02', name: '管道', children: [] },
      { code: '03', name: '设备', children: [] },
      { code: '04', name: '仪表', children: [] },
      { code: '05', name: '电气', children: [] },
      { code: '06', name: '结构', children: [] },
      { code: '07', name: '造价', children: [] },
      { code: '08', name: '拆解', children: [] },
    ],
  },
  {
    code: 'P',
    name: '采购资料',
    children: [
      { code: '01', name: '主合同内容', children: [] },
      { code: '02', name: '采购管理', children: [] },
      { code: '03', name: '采购合同', children: [] },
      { code: '04', name: '提交检验', children: [] },
      { code: '05', name: '运输', children: [] },
      { code: '06', name: '现场采购', children: [] },
      { code: '07', name: '状态表', children: [] },
      { code: '08', name: '备件', children: [] },
      { code: '09', name: '厂商资料', children: [] },
      { code: '10', name: '需要采购', children: [] },
      { code: '11', name: '内部采购合同', children: [] },
    ],
  },
];

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
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
function hasAnyPermission(permissions: string[]): boolean {
  return permissions.some((permission) => authStore.hasPermission(permission));
}

const canViewProjectDetail = computed(() => hasAnyPermission(['project:detail:view', 'project:view', 'project']));
const canEditProject = computed(() => hasAnyPermission(['project:update', 'project:edit']));
const canViewDocuments = computed(() => hasAnyPermission(['project_document:view', 'project:document:view', 'knowledge:view']));
const canUploadDocuments = computed(() => hasAnyPermission(['project_document:upload', 'knowledge:upload']));
const canPreviewDocuments = computed(() => hasAnyPermission(['project_document:preview', 'knowledge:view']));
const canDownloadDocuments = computed(() => hasAnyPermission(['project_document:download', 'knowledge:view']));
const canPublishDocuments = computed(() => hasAnyPermission(['project_document:publish', 'knowledge:submit-review']));
const canDeleteDocuments = computed(() => hasAnyPermission(['project_document:delete', 'knowledge:delete']));
const canRetryParseDocuments = computed(() => hasAnyPermission(['project_document:retry_parse', 'review:build-index']));
const canRetryIndexDocuments = computed(() => hasAnyPermission(['project_document:retry_index', 'review:build-index']));
const canToggleDocumentAi = computed(() => hasAnyPermission(['project_document:ai_toggle', 'knowledge:edit']));
const canUpdateDocumentSecurity = computed(() => hasAnyPermission(['project_document:security_update', 'knowledge:edit']));
const canUpdateDocumentMetadata = computed(() => hasAnyPermission(['project_document:update', 'knowledge:edit']));
const canCreateDocumentVersion = computed(() => hasAnyPermission(['project_document:version:create', 'knowledge:upload']));
const canViewDocumentVersions = computed(() => hasAnyPermission(['project_document:version:view']));
const canViewDirectories = computed(() => hasAnyPermission(['project_directory:view', 'project:document:view', 'project_document:view']));
const canCreateCategories = computed(() => hasAnyPermission(['project_directory:create', 'knowledge:create']));
const canEditCategories = computed(() => hasAnyPermission(['project_directory:update', 'knowledge:edit']));
const canDeleteCategories = computed(() => hasAnyPermission(['project_directory:delete', 'knowledge:delete']));
const canAskProjectChat = computed(() => hasAnyPermission(['project_chat:ask', 'project:chat:view']));
const canUseProjectChat = computed(() => canAskProjectChat.value && (project.value?.project_chat_enabled ?? true));

const uploadForm = reactive({
  category_id: null as number | null,
  security_level: 'internal' as SecurityLevel,
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
  ai_enabled: '' as '' | 'true' | 'false',
  version: '',
  upload_user_id: '',
  updated_range: [] as string[],
});

const batchForm = reactive({
  security_level: 'internal' as SecurityLevel,
  ai_enabled: false,
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
  default_security_level: 'internal' as SecurityLevel,
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
    if (documentFilters.ai_enabled && String(Boolean(document.ai_enabled)) !== documentFilters.ai_enabled) return false;
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

const recentUploadDocuments = computed<RecentDocumentDisplayItem[]>(() =>
  (project.value?.recent_documents || []).slice(0, 5).map((document) => {
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
  }),
);

const selectedDocuments = computed(() => documents.value.filter((document) => selectedDocumentIds.value.includes(document.id)));

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
    MessagePlugin.error(error instanceof Error ? error.message : '项目详情加载失败');
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
    MessagePlugin.warning(error instanceof Error ? error.message : '项目资料目录加载失败');
    return [];
  }
}

async function loadProjectDocumentsSafely(): Promise<DocumentInfo[]> {
  if (!canViewDocuments.value) return [];
  try {
    return await listProjectDocuments(projectId.value);
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : '项目资料加载失败');
    return [];
  }
}

async function loadProjectMembersSafely(): Promise<Array<Record<string, unknown>>> {
  try {
    return await listProjectMembers(projectId.value);
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : '项目成员加载失败');
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
    key: `default-${item.code}-${item.name}`,
    code: item.code,
    name: item.name,
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
  return document.upload_user_id ? `用户 #${document.upload_user_id}` : '-';
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
    MessagePlugin.warning('无权限上传项目资料');
    return;
  }
  /**
   * 打开上传弹窗，并预填当前选中的项目资料目录。
   */
  if (!categoryOptions.value.length) {
    MessagePlugin.warning('请先配置项目资料目录');
    return;
  }
  uploadForm.category_id = activeCategoryId.value || categoryOptions.value.find((item) => !item.disabled)?.value || null;
  const selectedCategory = findCategory(categories.value, uploadForm.category_id);
  uploadForm.security_level = selectedCategory?.default_security_level || project.value?.security_level || 'internal';
  uploadForm.document_type = '';
  uploadForm.discipline = '';
  uploadForm.remark = '';
  selectedUploadFiles.value = [];
  uploadDialogVisible.value = true;
}

function openProjectDialog(): void {
  if (!canEditProject.value) {
    MessagePlugin.warning('无权限编辑项目');
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
    MessagePlugin.success('项目已更新');
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
    MessagePlugin.warning('已过滤不支持的文件类型');
  }
  selectedUploadFiles.value = validFiles;
}

async function confirmUpload(): Promise<void> {
  if (!canUploadDocuments.value) {
    MessagePlugin.warning('无权限上传项目资料');
    return;
  }
  /**
   * 批量上传沿用后端单文件上传协议，逐个上传后再用现有元数据接口补写类型、专业和备注。
   */
  if (!selectedUploadFiles.value.length) {
    MessagePlugin.warning('请选择需要上传的资料');
    return;
  }
  if (!uploadForm.category_id) {
    MessagePlugin.warning('请选择项目资料目录');
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
    MessagePlugin.success(`已上传 ${selectedUploadFiles.value.length} 个文件，默认进入待审核状态`);
    uploadDialogVisible.value = false;
    selectedUploadFiles.value = [];
    await loadData();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '项目资料上传失败');
  } finally {
    uploading.value = false;
  }
}

async function submitReview(document: DocumentInfo): Promise<void> {
  if (!canPublishDocuments.value) {
    MessagePlugin.warning('无权限发布文件');
    return;
  }
  /**
   * 项目资料提交审核，解析与索引构建由审核中心统一触发。
   */
  await publishProjectDocument(projectId.value, document.id);
  MessagePlugin.success('文件已发布');
  await loadData();
}

function canSubmitReview(document: DocumentInfo): boolean {
  /**
   * 仅草稿和驳回状态允许重新提交审核。
   */
  return documentStatusText(document) !== '已发布' && SUBMITTABLE_REVIEW_STATUSES.has(document.review_status);
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
    MessagePlugin.warning('无权限预览文件');
    return;
  }
  router.push(`/documents/${document.id}`);
}

async function downloadDocument(document: DocumentInfo): Promise<void> {
  if (!canDownloadDocuments.value) {
    MessagePlugin.warning('无权限下载文件');
    return;
  }
  const blob = await downloadDocumentVersion(document.id, document.version_no);
  triggerBlobDownload(blob, document.file_name);
}

function openVersionUploadDialog(): void {
  if (!selectedDocument.value) return;
  if (!canCreateDocumentVersion.value) {
    MessagePlugin.warning('无权限上传新版本');
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
    MessagePlugin.warning('无权限上传新版本');
    return;
  }
  if (!selectedVersionFile.value) {
    MessagePlugin.warning('请选择新版本文件');
    return;
  }
  await createProjectDocumentVersion(projectId.value, selectedDocument.value.id, selectedVersionFile.value, {
    directory_id: versionForm.directory_id,
    category_id: versionForm.directory_id,
    version_note: versionForm.version_note.trim() || null,
  });
  MessagePlugin.success('新版本已上传，已进入待审核状态');
  versionDialogVisible.value = false;
  await loadData();
}

async function setCurrentVersion(version: DocumentVersionInfo): Promise<void> {
  if (!selectedDocument.value) return;
  if (!canCreateDocumentVersion.value) {
    MessagePlugin.warning('无权限切换当前版本');
    return;
  }
  await setProjectDocumentCurrentVersion(projectId.value, selectedDocument.value.id, version.id);
  MessagePlugin.success('当前版本已更新');
  await loadData();
  if (selectedDocument.value) {
    await loadDocumentVersions(selectedDocument.value);
  }
}

function removeDocument(document: DocumentInfo): void {
  if (!canDeleteDocuments.value) {
    MessagePlugin.warning('无权限删除文件');
    return;
  }
  deleteTargetDocuments.value = [document];
  deleteDialogVisible.value = true;
}

function openBatchDeleteDialog(): void {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning('请选择文件');
    return;
  }
  if (!canDeleteDocuments.value) {
    MessagePlugin.warning('无权限删除文件');
    return;
  }
  deleteTargetDocuments.value = [...selectedDocuments.value];
  deleteDialogVisible.value = true;
}

async function confirmDeleteDocuments(): Promise<void> {
  if (!deleteTargetDocuments.value.length) return;
  if (!canDeleteDocuments.value) {
    MessagePlugin.warning('无权限删除文件');
    return;
  }
  deleteSubmitting.value = true;
  try {
    const deletedIds = deleteTargetDocuments.value.map((document) => document.id);
    await Promise.all(deletedIds.map((id) => deleteProjectDocument(projectId.value, id)));
    MessagePlugin.success(`已删除 ${deletedIds.length} 个文件`);
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
    MessagePlugin.warning('请选择文件');
    return;
  }
  if (!canRetryParseDocuments.value) {
    MessagePlugin.warning('无权限重试解析');
    return;
  }
  await Promise.all(selectedDocuments.value.map((document) => retryParseProjectDocument(projectId.value, document.id, document.version_no)));
  MessagePlugin.success('已触发批量解析重试');
  await loadData();
}

async function retryParse(document: DocumentInfo): Promise<void> {
  if (!canRetryParseDocuments.value) {
    MessagePlugin.warning('无权限重试解析');
    return;
  }
  await retryParseProjectDocument(projectId.value, document.id, document.version_no);
  MessagePlugin.success('已触发解析重试');
  await loadData();
}

async function retryIndex(document: DocumentInfo): Promise<void> {
  if (!canRetryIndexDocuments.value) {
    MessagePlugin.warning('无权限重试索引');
    return;
  }
  await retryIndexProjectDocument(projectId.value, document.id, document.version_no);
  MessagePlugin.success('已触发索引重试');
  await loadData();
}

async function applyBatchRetryIndex(): Promise<void> {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning('请选择文件');
    return;
  }
  if (!canRetryIndexDocuments.value) {
    MessagePlugin.warning('无权限重试索引');
    return;
  }
  await Promise.all(selectedDocuments.value.map((document) => retryIndexProjectDocument(projectId.value, document.id, document.version_no)));
  MessagePlugin.success('已触发批量索引重试');
  await loadData();
}

async function updateSelectedDocumentSecurity(): Promise<void> {
  if (!selectedDocument.value) return;
  if (!canUpdateDocumentSecurity.value) {
    MessagePlugin.warning('无权限修改文件密级');
    return;
  }
  await updateProjectDocumentSecurityLevel(projectId.value, selectedDocument.value.id, selectedDocument.value.security_level);
  MessagePlugin.success('文件密级已更新');
  await loadData();
}

async function updateSelectedDocumentAiEnabled(value: boolean): Promise<void> {
  if (!selectedDocument.value) return;
  if (!canToggleDocumentAi.value) {
    MessagePlugin.warning('无权限修改 AI 问答开关');
    return;
  }
  const document = await updateProjectDocumentAiEnabled(projectId.value, selectedDocument.value.id, value);
  selectedDocument.value = document;
  MessagePlugin.success(value ? 'AI 问答已开启' : 'AI 问答已关闭');
  await loadData();
}

async function applyBatchSecurityLevel(): Promise<void> {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning('请选择文件');
    return;
  }
  if (!canUpdateDocumentSecurity.value) {
    MessagePlugin.warning('无权限修改文件密级');
    return;
  }
  await Promise.all(selectedDocumentIds.value.map((id) => updateProjectDocumentSecurityLevel(projectId.value, id, batchForm.security_level)));
  MessagePlugin.success('批量密级已更新');
  await loadData();
}

async function applyBatchAiEnabled(): Promise<void> {
  if (!selectedDocumentIds.value.length) {
    MessagePlugin.warning('请选择文件');
    return;
  }
  if (!canToggleDocumentAi.value) {
    MessagePlugin.warning('无权限修改 AI 问答开关');
    return;
  }
  await Promise.all(selectedDocumentIds.value.map((id) => updateProjectDocumentAiEnabled(projectId.value, id, batchForm.ai_enabled)));
  MessagePlugin.success(batchForm.ai_enabled ? '批量 AI 问答已开启' : '批量 AI 问答已关闭');
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

function documentStatusText(document: DocumentInfo): string {
  const status = document.status || document.document_status || document.review_status;
  const map: Record<string, string> = {
    pending_review: '待审核',
    pending: '待审核',
    active: '已发布',
    published: '已发布',
    reviewed: '已发布',
    draft: '待审核',
    approved: '已发布',
  };
  return map[status] || status || '-';
}

function documentFileStatusTheme(document: DocumentInfo): 'default' | 'primary' | 'success' | 'warning' {
  return documentStatusText(document) === '已发布' ? 'success' : 'warning';
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
  if (indexStatus === 'indexed') return 'ready';
  if (indexStatus === 'failed') return 'failed';
  if (indexStatus === 'indexing') return 'building';
  return 'pending';
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
  return documentStatusText(document) === '已发布';
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
    MessagePlugin.warning('无权限编辑文件元数据');
    return;
  }
  if (!metadataForm.document_name.trim()) {
    MessagePlugin.warning('请输入文件名称');
    return;
  }
  if (!metadataForm.directory_id) {
    MessagePlugin.warning('请选择所属目录');
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
  MessagePlugin.success('文件元数据已保存');
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
    MessagePlugin.warning(error instanceof Error ? error.message : '历史版本加载失败');
  }
}

function openCreateCategoryDialog(): void {
  if (!canCreateCategories.value) {
    MessagePlugin.warning('无权限新建目录');
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
  categoryForm.default_security_level = project.value?.security_level || 'internal';
  categoryDialogVisible.value = true;
}

function openEditCategoryDialog(): void {
  if (!canEditCategories.value) {
    MessagePlugin.warning('无权限编辑目录');
    return;
  }
  /**
   * 编辑当前选中的项目资料目录。
   */
  const category = findCategory(categories.value, activeCategoryId.value);
  if (!category) {
    MessagePlugin.warning('请先选择需要编辑的目录');
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
    MessagePlugin.warning('无权限新建目录');
    return;
  }
  if (categoryDialogMode.value === 'edit' && !canEditCategories.value) {
    MessagePlugin.warning('无权限编辑目录');
    return;
  }
  /**
   * 保存项目资料目录配置，后端会按项目隔离校验父级和编码。
   */
  if (!categoryForm.name.trim()) {
    MessagePlugin.warning('请输入目录名称');
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
  MessagePlugin.success('项目资料目录已保存');
  categoryDialogVisible.value = false;
  await loadData();
}

async function removeActiveCategory(): Promise<void> {
  if (!canDeleteCategories.value) {
    MessagePlugin.warning('无权限删除目录');
    return;
  }
  /**
   * 删除当前目录。后端只允许删除无子级、无文档引用的目录。
   */
  if (!activeCategoryId.value) {
    MessagePlugin.warning('请先选择目录');
    return;
  }
  await deleteProjectDirectory(projectId.value, activeCategoryId.value);
  MessagePlugin.success('目录已删除');
  activeCategoryId.value = null;
  await loadData();
}

function openProjectChat(): void {
  if (!canAskProjectChat.value) {
    MessagePlugin.warning('无权限使用项目问答');
    return;
  }
  router.push({ path: ROUTE_PATHS.aiProjectChat, query: { projectId: String(projectId.value) } });
}

function openProjectDocumentManagement(): void {
  router.push(`/projects/${projectId.value}/documents`);
}

onMounted(loadData);
</script>

<template>
  <PageContainer class="project-detail-page" title="">
    <div v-if="!canViewProjectDetail" class="panel-stack project-detail-stack data-scroll">
      <t-card class="project-state-card">
        <t-empty description="无权限访问项目详情" />
      </t-card>
    </div>

    <div v-else-if="loading" class="panel-stack project-detail-stack data-scroll">
      <t-card class="project-state-card">
        <div class="project-state-content">
          <t-loading text="正在加载项目详情" />
        </div>
      </t-card>
    </div>

    <div v-else-if="!project" class="panel-stack project-detail-stack data-scroll">
      <t-card class="project-state-card">
        <div class="project-state-content">
          <t-empty description="项目详情加载失败或项目不存在" />
          <t-button variant="outline" @click="router.push('/projects')">返回项目中心</t-button>
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
                {{ normalizeProjectStatus(project.project_status || project.status) }}
              </t-tag>
            </div>
            <p>{{ profileText(project.project_short_name || project.project_code || project.code) }}</p>
          </div>
        </div>

        <div class="project-profile-sections">
          <section class="project-profile-section">
            <h3>基础信息</h3>
            <div class="project-profile-list">
              <div class="project-profile-item">
                <span>项目简称</span>
                <strong>{{ profileText(project.project_short_name) }}</strong>
              </div>
              <div class="project-profile-item">
                <span>英文名称</span>
                <strong>{{ profileText(project.project_english_name) }}</strong>
              </div>
              <div class="project-profile-item">
                <span>客户名称</span>
                <strong>{{ profileText(project.customer_name || project.client) }}</strong>
              </div>
              <div class="project-profile-item">
                <span>项目负责人</span>
                <strong>{{ profileText(project.owner_name || project.manager) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>项目简介</span>
                <strong>{{ profileText(project.description) }}</strong>
              </div>
            </div>
          </section>

          <section class="project-profile-section">
            <h3>管控信息</h3>
            <div class="project-profile-list">
              <div class="project-profile-item">
                <span>项目状态</span>
                <strong>
                  <t-tag size="small" variant="light" :theme="projectStatusTheme(project.project_status || project.status)">
                    {{ normalizeProjectStatus(project.project_status || project.status) }}
                  </t-tag>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>项目密级</span>
                <strong>
                  <t-tag size="small" variant="light" :theme="securityLevelTheme(project.security_level)">
                    {{ securityLevelLabel(project.security_level) }}
                  </t-tag>
                </strong>
              </div>
            </div>
          </section>

          <section class="project-profile-section">
            <h3>项目属性</h3>
            <div class="project-profile-list">
              <div class="project-profile-item">
                <span>项目类型</span>
                <strong>
                  <t-tag v-if="project.project_type" size="small" variant="light" :theme="projectFieldTagTheme('project_type')">
                    {{ project.project_type }}
                  </t-tag>
                  <template v-else>-</template>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>项目阶段</span>
                <strong>
                  <t-tag v-if="project.project_stage" size="small" variant="light" :theme="projectFieldTagTheme('project_stage')">
                    {{ project.project_stage }}
                  </t-tag>
                  <template v-else>-</template>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>原料类型</span>
                <strong>
                  <t-tag v-if="project.raw_material_type" size="small" variant="light" :theme="projectFieldTagTheme('raw_material_type')">
                    {{ project.raw_material_type }}
                  </t-tag>
                  <template v-else>-</template>
                </strong>
              </div>
              <div class="project-profile-item">
                <span>处理能力</span>
                <strong>{{ profileText(project.capacity) }}</strong>
              </div>
            </div>
          </section>

          <section class="project-profile-section">
            <h3>建设与交付</h3>
            <div class="project-profile-list">
              <div class="project-profile-item project-profile-item--wide">
                <span>工艺路线</span>
                <strong>{{ profileText(project.process_route) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>主要产品</span>
                <strong>{{ profileText(project.main_products) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>项目范围</span>
                <strong>{{ profileText(project.scope_description) }}</strong>
              </div>
              <div class="project-profile-item project-profile-item--wide">
                <span>交付成果</span>
                <strong>{{ profileText(project.deliverables) }}</strong>
              </div>
            </div>
          </section>
        </div>
      </section>

      <section class="project-overview-main">
        <div class="overview-band overview-stat-band">
          <div class="overview-section-heading">
            <h3>数据统计</h3>
            <t-space class="overview-action-group" size="small">
              <t-button variant="outline" @click="router.push('/projects')">返回项目中心</t-button>
              <t-button v-if="canUseProjectChat" variant="outline" @click="openProjectChat">项目问答</t-button>
              <t-button v-if="canEditProject" theme="primary" variant="outline" @click="openProjectDialog">编辑项目</t-button>
            </t-space>
          </div>
          <div class="overview-stat-grid">
            <div class="overview-stat-card overview-stat-card--blue">
              <div class="overview-stat-icon">
                <FolderIcon />
              </div>
              <div>
                <span>资料数量</span>
                <strong>{{ project.document_count }}</strong>
              </div>
            </div>
            <div class="overview-stat-card overview-stat-card--green">
              <div class="overview-stat-icon">
                <ChatBubbleHelpIcon />
              </div>
              <div>
                <span>问答次数</span>
                <strong>{{ project.qa_count ?? 0 }}</strong>
              </div>
            </div>
            <div class="overview-stat-card overview-stat-card--blue">
              <div class="overview-stat-icon">
                <TaskCheckedIcon />
              </div>
              <div>
                <span>待审核文档</span>
                <strong>{{ project.pending_review_document_count }}</strong>
              </div>
            </div>
          </div>
        </div>

        <div class="overview-band overview-directory-band">
          <div class="overview-section-heading">
            <h3>资料目录结构</h3>
            <button type="button" class="overview-heading-action" @click="openProjectDocumentManagement">
              <span>查看全部目录</span>
              <ChevronDownSIcon />
            </button>
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
            <h3>最近上传资料</h3>
            <button type="button" class="overview-heading-action" @click="openProjectDocumentManagement">
              <span>进入资料管理</span>
              <ChevronDownSIcon />
            </button>
          </div>
          <div v-if="recentUploadDocuments.length" class="recent-upload-list">
            <div v-for="document in recentUploadDocuments" :key="document.id" class="recent-upload-row">
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
            </div>
          </div>
          <t-empty v-else description="暂无最近上传资料" />
        </div>
      </section>
    </div>

    <t-drawer
      v-if="canViewDocuments"
      v-model:visible="documentDetailVisible"
      class="project-document-drawer drawer-scroll"
      header="文件详情"
      placement="right"
      size="min(760px, 96vw)"
      :footer="false"
      @close="closeDocumentDetail"
    >
      <t-empty v-if="!selectedDocument" description="请选择文件" />
      <div v-else class="document-detail-panel">
        <div class="drawer-file-header">
          <div class="file-type-badge">{{ selectedDocument.file_type || 'FILE' }}</div>
          <div class="drawer-file-title">
            <div>{{ documentDisplayName(selectedDocument) }}</div>
            <span>{{ selectedDocument.category_path || selectedDocument.category_name || '-' }}</span>
          </div>
        </div>

        <div class="drawer-tabs">
          <button :class="{ active: drawerTab === 'basic' }" type="button" @click="drawerTab = 'basic'">基本信息</button>
          <button :class="{ active: drawerTab === 'versions' }" type="button" @click="drawerTab = 'versions'">版本管理</button>
          <button :class="{ active: drawerTab === 'parse' }" type="button" @click="drawerTab = 'parse'">解析信息</button>
          <button :class="{ active: drawerTab === 'index' }" type="button" @click="drawerTab = 'index'">索引信息</button>
        </div>

        <div class="drawer-action-row">
          <t-button v-if="canPreviewDocuments" variant="outline" @click="openDocumentPreview(selectedDocument)">
            <template #icon><FileSearchIcon /></template>
            预览
          </t-button>
          <t-button v-if="canDownloadDocuments" variant="outline" @click="downloadDocument(selectedDocument)">
            <template #icon><DownloadIcon /></template>
            下载
          </t-button>
          <t-button
            v-if="canRetryParseDocuments"
            theme="primary"
            variant="outline"
            :disabled="documentParseStatus(selectedDocument) !== 'failed'"
            @click="retryParse(selectedDocument)"
          >
            <template #icon><RefreshIcon /></template>
            重试解析
          </t-button>
          <t-button
            v-if="canRetryIndexDocuments"
            theme="primary"
            variant="outline"
            :disabled="documentIndexStatus(selectedDocument) !== 'failed'"
            @click="retryIndex(selectedDocument)"
          >
            <template #icon><RefreshIcon /></template>
            重试索引
          </t-button>
          <t-button v-if="canCreateDocumentVersion" theme="primary" @click="openVersionUploadDialog">
            <template #icon><AddIcon /></template>
            上传新版本
          </t-button>
        </div>

        <div v-if="drawerTab === 'basic'" class="drawer-tab-panel">
          <section class="drawer-section">
            <div class="drawer-section-title">文件信息</div>
            <div class="drawer-info-grid">
              <div><span>所属项目</span><strong>{{ project?.project_name || project?.name || '-' }}</strong></div>
              <div><span>所属目录</span><strong>{{ selectedDocument.category_path || selectedDocument.category_name || '-' }}</strong></div>
              <div><span>文档类型</span><strong>{{ selectedDocument.document_type || selectedDocument.file_type || '-' }}</strong></div>
              <div><span>所属专业</span><strong>{{ selectedDocument.discipline || '-' }}</strong></div>
              <div><span>版本号</span><strong>{{ documentVersionLabel(selectedDocument) }}</strong></div>
              <div><span>当前版本</span><strong>{{ (selectedDocument.is_current_version ?? selectedDocument.current_version) ? '是' : '否' }}</strong></div>
              <div><span>文件状态</span><strong>{{ documentStatusText(selectedDocument) }}</strong></div>
              <div><span>密级</span><strong>{{ securityLevelLabel(selectedDocument.security_level) }}</strong></div>
              <div><span>上传人</span><strong>{{ documentUploader(selectedDocument) }}</strong></div>
              <div><span>上传时间</span><strong>{{ formatDateTime(selectedDocument.created_at) }}</strong></div>
              <div><span>文件大小</span><strong>{{ formatFileSize(selectedDocument.file_size) }}</strong></div>
              <div><span>备注</span><strong>{{ selectedDocument.remark || '-' }}</strong></div>
            </div>
          </section>

          <section class="drawer-section">
            <div class="drawer-section-title">RAG 状态</div>
            <div class="rag-status-grid">
              <div><span>解析状态</span><StatusTag type="generic" :value="documentParseStatus(selectedDocument)" /></div>
              <div><span>索引状态</span><StatusTag type="index" :value="documentIndexStatus(selectedDocument)" /></div>
              <div><span>Embedding</span><strong>{{ documentEmbeddingStatus(selectedDocument) }}</strong></div>
              <div><span>Chunk 数量</span><strong>{{ documentChunkCount(selectedDocument) }}</strong></div>
              <div><span>AI 问答</span><strong>{{ selectedDocument.ai_enabled ? '开启' : '关闭' }}</strong></div>
              <div><span>检索资格</span><strong>{{ isPublishedDocument(selectedDocument) && selectedDocument.ai_enabled && documentIndexStatus(selectedDocument) === 'indexed' ? '可进入问答' : '不可进入问答' }}</strong></div>
            </div>
          </section>

          <section class="drawer-section">
            <div class="drawer-section-title">编辑信息</div>
            <t-form label-align="top" class="document-detail-form">
              <t-form-item label="文件名称">
                <t-input v-model="metadataForm.document_name" :disabled="!canUpdateDocumentMetadata" />
              </t-form-item>
              <div class="drawer-form-grid">
                <t-form-item label="所属目录">
                  <t-select v-model="metadataForm.directory_id" :disabled="!canUpdateDocumentMetadata" placeholder="请选择项目资料目录">
                    <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
                  </t-select>
                </t-form-item>
                <t-form-item label="版本号">
                  <t-input v-model="metadataForm.version" :disabled="!canUpdateDocumentMetadata" />
                </t-form-item>
                <t-form-item label="文档类型">
                  <t-select v-model="metadataForm.document_type" :disabled="!canUpdateDocumentMetadata" clearable placeholder="请选择文档类型">
                    <t-option v-for="item in DOCUMENT_TYPE_OPTIONS" :key="item" :value="item" :label="item" />
                  </t-select>
                </t-form-item>
                <t-form-item label="所属专业">
                  <t-select v-model="metadataForm.discipline" :disabled="!canUpdateDocumentMetadata" clearable placeholder="请选择专业">
                    <t-option v-for="item in DISCIPLINE_OPTIONS" :key="item" :value="item" :label="item" />
                  </t-select>
                </t-form-item>
                <t-form-item label="文件状态">
                  <t-select v-model="selectedDocument.status" disabled>
                    <t-option v-for="item in DOCUMENT_STATUS_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
                  </t-select>
                </t-form-item>
                <t-form-item label="文件密级">
                  <t-select v-model="selectedDocument.security_level" :disabled="!canUpdateDocumentSecurity">
                    <t-option v-for="item in SECURITY_LEVEL_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
                  </t-select>
                </t-form-item>
              </div>
              <t-form-item label="备注">
                <t-textarea v-model="metadataForm.remark" :disabled="!canUpdateDocumentMetadata" :autosize="{ minRows: 3, maxRows: 4 }" />
              </t-form-item>
              <t-form-item label="AI 问答开关">
                <t-switch
                  v-if="canToggleDocumentAi"
                  v-model="selectedDocument.ai_enabled"
                  :disabled="!isPublishedDocument(selectedDocument)"
                  @change="(value) => updateSelectedDocumentAiEnabled(Boolean(value))"
                />
                <span v-else class="muted">无权限修改</span>
              </t-form-item>
              <t-space class="document-form-actions">
                <t-button v-if="canUpdateDocumentMetadata" variant="outline" @click="saveSelectedDocumentMetadata">保存元数据</t-button>
                <t-button v-if="canUpdateDocumentSecurity" variant="outline" @click="updateSelectedDocumentSecurity">保存密级</t-button>
              </t-space>
            </t-form>
          </section>
        </div>

        <div v-else-if="drawerTab === 'versions'" class="drawer-tab-panel">
          <section class="drawer-section">
            <div class="drawer-section-heading">
              <div class="drawer-section-title">版本管理</div>
              <t-button v-if="canCreateDocumentVersion" theme="primary" @click="openVersionUploadDialog">上传新版本</t-button>
            </div>
            <t-empty v-if="!documentVersions.length" description="暂无历史版本" />
            <div v-else class="version-table-wrap">
              <table class="plain-table version-table">
                <thead>
                  <tr>
                    <th>版本号</th>
                    <th>文件大小</th>
                    <th>文件状态</th>
                    <th>解析状态</th>
                    <th>索引状态</th>
                    <th>是否当前版本</th>
                    <th>上传人</th>
                    <th>上传时间</th>
                    <th>版本备注</th>
                    <th>操作</th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="version in documentVersions" :key="version.id">
                    <td>{{ documentVersionLabel(version) }}</td>
                    <td>{{ formatFileSize(version.file_size || 0) }}</td>
                    <td>{{ version.version_status || version.review_status || '-' }}</td>
                    <td><StatusTag type="generic" :value="documentParseStatus(version)" /></td>
                    <td><StatusTag type="index" :value="documentIndexStatus(version)" /></td>
                    <td>{{ version.is_current || version.is_current_version ? '是' : '否' }}</td>
                    <td>{{ documentUploader(version) }}</td>
                    <td>{{ formatDateTime(version.created_at) }}</td>
                    <td>{{ version.version_note || version.change_summary || '-' }}</td>
                    <td>
                      <t-button
                        v-if="canCreateDocumentVersion && !(version.is_current || version.is_current_version)"
                        size="small"
                        variant="outline"
                        @click="setCurrentVersion(version)"
                      >
                        设为当前版本
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
              <div class="drawer-section-title">解析信息</div>
              <t-button
                v-if="canRetryParseDocuments"
                variant="outline"
                :disabled="documentParseStatus(selectedDocument) !== 'failed'"
                @click="retryParse(selectedDocument)"
              >
                重试解析
              </t-button>
            </div>
            <div class="drawer-info-grid">
              <div><span>解析状态</span><strong>{{ documentParseStatus(selectedDocument) }}</strong></div>
              <div><span>开始时间</span><strong>{{ formatDateTime(selectedDocument.parse_started_at || '') }}</strong></div>
              <div><span>完成时间</span><strong>{{ formatDateTime(selectedDocument.parse_finished_at || '') }}</strong></div>
              <div class="drawer-info-wide"><span>错误信息</span><strong>{{ selectedDocument.parse_error || '-' }}</strong></div>
              <div class="drawer-info-wide"><span>解析日志</span><strong>{{ selectedDocument.parse_log || '-' }}</strong></div>
            </div>
          </section>
        </div>

        <div v-else class="drawer-tab-panel">
          <section class="drawer-section">
            <div class="drawer-section-heading">
              <div class="drawer-section-title">索引信息</div>
              <t-button
                v-if="canRetryIndexDocuments"
                variant="outline"
                :disabled="documentIndexStatus(selectedDocument) !== 'failed'"
                @click="retryIndex(selectedDocument)"
              >
                重试索引
              </t-button>
            </div>
            <div class="drawer-info-grid">
              <div><span>索引状态</span><strong>{{ documentIndexStatus(selectedDocument) }}</strong></div>
              <div><span>Embedding</span><strong>{{ documentEmbeddingStatus(selectedDocument) }}</strong></div>
              <div><span>Chunk 数量</span><strong>{{ documentChunkCount(selectedDocument) }}</strong></div>
              <div><span>AI 问答</span><strong>{{ selectedDocument.ai_enabled ? '开启' : '关闭' }}</strong></div>
              <div><span>构建开始</span><strong>{{ formatDateTime(selectedDocument.build_started_at || '') }}</strong></div>
              <div><span>构建完成</span><strong>{{ formatDateTime(selectedDocument.build_finished_at || '') }}</strong></div>
              <div class="drawer-info-wide"><span>构建错误</span><strong>{{ selectedDocument.build_error || '-' }}</strong></div>
            </div>
          </section>
        </div>
      </div>
    </t-drawer>

    <t-dialog v-model:visible="uploadDialogVisible" header="上传项目资料" width="680px" :confirm-loading="uploading" @confirm="confirmUpload">
      <div class="upload-dialog-content">
        <div class="version-rule">
          新资料首次上传为 v1；同一资料的新版本请在文件详情中上传，系统自动递增。
        </div>
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
          <strong>点击或将文件拖拽到此区域上传</strong>
          <span>支持单个或批量上传，格式：PDF、DOC、DOCX、PPT、XLS、TXT、ZIP、RAR</span>
        </div>
        <div v-if="selectedUploadFiles.length" class="upload-file-list">
          <div v-for="(file, index) in selectedUploadFiles" :key="`${file.name}-${file.size}-${index}`" class="upload-file-item">
            <span>{{ file.name }}</span>
            <strong>{{ formatFileSize(file.size) }}</strong>
            <t-button size="small" variant="text" theme="danger" @click.stop="removeUploadFile(index)">移除</t-button>
          </div>
        </div>
        <t-form label-align="top">
          <div class="upload-form-grid">
            <t-form-item label="项目资料目录">
              <t-select v-model="uploadForm.category_id" placeholder="请选择项目资料目录">
                <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
              </t-select>
            </t-form-item>
            <t-form-item label="文档密级">
              <t-select v-model="uploadForm.security_level">
                <t-option v-for="item in SECURITY_LEVEL_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
              </t-select>
            </t-form-item>
            <t-form-item label="文档类型">
              <t-select v-model="uploadForm.document_type" clearable placeholder="请选择文档类型">
                <t-option v-for="item in DOCUMENT_TYPE_OPTIONS" :key="item" :value="item" :label="item" />
              </t-select>
            </t-form-item>
            <t-form-item label="所属专业">
              <t-select v-model="uploadForm.discipline" clearable placeholder="请选择专业">
                <t-option v-for="item in DISCIPLINE_OPTIONS" :key="item" :value="item" :label="item" />
              </t-select>
            </t-form-item>
          </div>
          <t-form-item label="备注">
            <t-textarea v-model="uploadForm.remark" :autosize="{ minRows: 3, maxRows: 4 }" placeholder="请输入备注信息（非必填）" />
          </t-form-item>
        </t-form>
      </div>
    </t-dialog>

    <t-dialog v-model:visible="versionDialogVisible" header="上传新版本" width="560px" @confirm="confirmVersionUpload">
      <t-form label-align="top">
        <t-form-item label="所属目录">
          <t-select v-model="versionForm.directory_id" clearable placeholder="默认沿用当前目录">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
          </t-select>
        </t-form-item>
        <t-form-item label="版本备注">
          <t-textarea v-model="versionForm.version_note" :autosize="{ minRows: 2, maxRows: 4 }" />
        </t-form-item>
        <t-form-item label="新版本文件">
          <input type="file" accept=".txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf" @change="handleVersionFileChange" />
          <div v-if="selectedVersionFile" class="selected-file">{{ selectedVersionFile.name }}</div>
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog
      v-model:visible="deleteDialogVisible"
      header="删除确认"
      width="560px"
      theme="warning"
      :confirm-loading="deleteSubmitting"
      confirm-btn="确认删除"
      cancel-btn="取消"
      @confirm="confirmDeleteDocuments"
    >
      <div class="delete-confirm-panel">
        <div class="delete-confirm-title">确定要删除选中的 {{ deleteTargetDocuments.length }} 个文件吗？</div>
        <div class="delete-impact-box">
          <div>项目：文件会从当前项目资料列表默认视图移除。</div>
          <div>文件：后端按现有删除接口处理，前端不改变删除协议。</div>
          <div>RAG 索引：已索引文件将通过删除状态和权限过滤从项目问答中失效。</div>
          <div>历史版本：历史版本记录不在前端批量清理，保留后端审计与回溯策略。</div>
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
      :header="categoryDialogMode === 'create' ? '新增项目资料目录' : '编辑项目资料目录'"
      width="560px"
      @confirm="confirmCategoryDialog"
    >
      <t-form :data="categoryForm" label-align="top">
        <t-form-item label="父目录">
          <t-select v-model="categoryForm.parent_id" clearable placeholder="根目录">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.value === editingCategoryId" />
          </t-select>
        </t-form-item>
        <t-form-item label="目录名称"><t-input v-model="categoryForm.name" /></t-form-item>
        <t-form-item label="目录编码"><t-input v-model="categoryForm.code" placeholder="为空时自动生成" /></t-form-item>
        <t-form-item label="排序"><t-input v-model="categoryForm.sort_order" type="number" /></t-form-item>
        <t-form-item label="默认密级">
          <t-select v-model="categoryForm.default_security_level">
            <t-option v-for="item in SECURITY_LEVEL_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
          </t-select>
        </t-form-item>
        <t-form-item label="说明"><t-textarea v-model="categoryForm.description" /></t-form-item>
        <t-form-item label="启用"><t-switch v-model="categoryForm.enabled" /></t-form-item>
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
  display: inline-flex;
  height: 34px;
  flex: 0 0 auto;
  align-items: center;
  gap: 4px;
  border: 1px solid #d6deeb;
  border-radius: 6px;
  background: #fff;
  color: inherit;
  cursor: pointer;
  font: inherit;
  font-size: 14px;
  font-weight: 700;
  line-height: 1;
  padding: 0 10px 0 12px;
  white-space: nowrap;
}

.overview-heading-action:hover {
  background: #f7faff;
}

.overview-heading-action:focus-visible {
  outline: 2px solid #8bb7ff;
  outline-offset: 2px;
}

.overview-heading-action :deep(svg) {
  width: 16px;
  height: 16px;
  color: #667997;
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
  min-height: 112px;
  grid-template-columns: 50px minmax(0, 1fr);
  align-items: center;
  gap: 20px;
  border-radius: 8px;
  background: #f5f8fd;
  padding: 18px 22px;
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
  min-height: 42px;
  grid-template-columns: 28px minmax(0, 1fr) minmax(170px, auto);
  align-items: center;
  gap: 12px;
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
