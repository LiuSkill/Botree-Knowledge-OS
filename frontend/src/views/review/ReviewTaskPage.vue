<!--
  Review Task Page

  负责：
  1. 展示审核任务并支持通过、驳回
  2. 展示审核通过资料和索引构建状态
  3. 通过异步索引任务触发“解析并构建索引”，避免前端长时间阻塞
-->
<script setup lang="ts">
import { DialogPlugin, MessagePlugin } from 'tdesign-vue-next';
import { CheckCircleIcon, CloseCircleIcon, FileSearchIcon, PlayCircleIcon, RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';

import { createDocumentIndexBuildTask, createDocumentIndexBuildTasksBatch, getKnowledgeDocumentStatusOptions, listDocumentIndexTasks } from '@/api/documents';
import { listKnowledgeCategories } from '@/api/knowledgeCategories';
import { listProjects } from '@/api/projects';
import {
  approveReviewTask,
  approveReviewTasksBatch,
  listApprovedDocuments,
  listReviewTasks,
  rejectReviewTask,
  rejectReviewTasksBatch,
} from '@/api/reviews';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { DocumentInfo, IndexTaskInfo, KnowledgeCategory, KnowledgeDocumentStatusOptions, ProjectInfo, ReviewTask } from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { buildCategoryOptions } from '@/utils/categories';
import {
  REVIEW_TASK_STATUS,
  indexStatusOptions,
  indexTaskStatusText,
  isReviewTaskPending,
  reviewTaskStatusOptions as buildReviewTaskStatusOptions,
} from '@/utils/constants';
import { formatDateTime } from '@/utils/format';
import { showConfirmDialog } from '@/utils/confirmDialog';
import { confirmRebuildIndexedDocument, isIndexedIndexStatus } from '@/utils/indexBuildConfirm';

type ReviewTab = 'tasks' | 'approved';
type ScopeType = '' | 'base' | 'project';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

const PAGE_SIZE_OPTIONS = [10, 20, 50];
const BUILD_TASK_TYPE = 'full_build';
const BUILD_TASK_RUNNING_STATUS = ['pending', 'running'];
const BUILD_TASK_TERMINAL_STATUS = ['success', 'failed', 'canceled'];
const BATCH_BUILD_SELECTABLE_STATUS = ['not_indexed', 'failed'];
const BUILD_POLL_INTERVAL_MS = 5000;
const ROUTE_REVIEW_STATUS_MAP: Record<string, string> = {
  pending: REVIEW_TASK_STATUS.reviewing,
  reviewing: REVIEW_TASK_STATUS.reviewing,
  approved: REVIEW_TASK_STATUS.approved,
  rejected: REVIEW_TASK_STATUS.rejected,
};

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const { t } = useI18n();
const activeTab = ref<ReviewTab>('tasks');
const taskStatus = ref('');
const taskProjectId = ref<number | null>(null);
const tasks = ref<ReviewTask[]>([]);
const approvedDocuments = ref<DocumentInfo[]>([]);
const statusOptions = ref<KnowledgeDocumentStatusOptions | null>(null);
const taskTotal = ref(0);
const taskPage = ref(1);
const taskPageSize = ref(10);
const approvedTotal = ref(0);
const approvedPage = ref(1);
const approvedPageSize = ref(10);
const tasksLoading = ref(false);
const approvedLoading = ref(false);
const projects = ref<ProjectInfo[]>([]);
const categories = ref<KnowledgeCategory[]>([]);
const pendingBuildDocumentIds = ref<number[]>([]);
const latestBuildTaskMap = ref<Record<number, IndexTaskInfo | null>>({});
const buildPollTimer = ref<number | null>(null);
const buildPollingBusy = ref(false);
const selectedTaskIds = ref<number[]>([]);
const selectedDocumentIds = ref<number[]>([]);
const batchSubmitting = ref(false);
const notifiedTaskIds = new Set<number>();

const approvedFilters = reactive({
  scope_type: '' as ScopeType,
  project_id: null as number | null,
  category_id: null as number | null,
  index_status: '',
  keyword: '',
});

const categoryOptions = computed(() => buildCategoryOptions(categories.value));
const canBuildIndex = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_BUILD_INDEX));
const canApproveTask = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_APPROVE));
const canRejectTask = computed(() => authStore.hasActionPermission(PERMISSIONS.REVIEW_REJECT));

const taskStatusOptions = computed(() => buildReviewTaskStatusOptions(statusOptions.value?.review_task_statuses));
const buildStatusOptions = computed(() => {
  /**
   * 构建进度筛选项统一来自状态常量，避免页面散落魔法字符串。
   */
  return indexStatusOptions(statusOptions.value?.approved_index_statuses);
});

function emptyStatusOptions(): KnowledgeDocumentStatusOptions {
  return {
    project_document_statuses: [],
    parse_statuses: [],
    index_statuses: [],
    approved_index_statuses: [],
    review_task_statuses: [],
  };
}

async function loadStatusOptions(): Promise<void> {
  try {
    statusOptions.value = await getKnowledgeDocumentStatusOptions();
  } catch {
    statusOptions.value = emptyStatusOptions();
  }
}

const rejectDialogVisible = ref(false);
const rejectSubmitting = ref(false);
const batchRejectMode = ref(false);
const pendingRejectTask = ref<ReviewTask | null>(null);
const rejectForm = reactive({
  comment: '',
});
const pendingRejectTaskName = computed(() => {
  if (batchRejectMode.value) return t('review.message.selectedTasks', { count: selectedTaskIds.value.length });
  return pendingRejectTask.value ? taskFileName(pendingRejectTask.value) : '';
});

const taskColumns = computed(() => [
  {
    colKey: 'row-select',
    type: 'multiple',
    width: 48,
    checkProps: ({ row }: { row: ReviewTask }) => ({
      disabled: batchSubmitting.value || !isReviewTaskPending(row.review_status) || (!canApproveTask.value && !canRejectTask.value),
    }),
  },
  { colKey: 'file_name', title: t('review.field.fileName'), minWidth: 240, ellipsis: true },
  { colKey: 'category', title: t('review.field.fileCategory'), width: 180, ellipsis: true },
  { colKey: 'uploader', title: t('review.field.uploader'), width: 120, ellipsis: true },
  { colKey: 'created_at', title: t('review.field.submittedAt'), width: 170, ellipsis: true },
  { colKey: 'version', title: t('review.field.version'), width: 80, align: 'center' },
  { colKey: 'review_status', title: t('review.field.status'), width: 110, align: 'center' },
  { colKey: 'review_comment', title: t('review.field.comment'), minWidth: 180, ellipsis: true },
  { colKey: 'operation', title: t('review.field.operation'), width: 160, align: 'center', fixed: 'right' },
]);

const approvedColumns = computed(() => [
  {
    colKey: 'row-select',
    type: 'multiple',
    width: 48,
    checkProps: ({ row }: { row: DocumentInfo }) => ({ disabled: batchSubmitting.value || !canSelectForBatchBuild(row) }),
  },
  { colKey: 'document', title: t('review.field.document'), minWidth: 260, ellipsis: true },
  { colKey: 'scope', title: t('review.field.scope'), width: 160, ellipsis: true },
  { colKey: 'category', title: t('review.field.category'), width: 180, ellipsis: true },
  { colKey: 'version', title: t('review.field.version'), width: 80, align: 'center' },
  { colKey: 'index_status', title: t('review.field.buildStatus'), width: 140, align: 'center' },
  { colKey: 'build_started_at', title: t('review.field.startedAt'), width: 170, ellipsis: true },
  { colKey: 'build_finished_at', title: t('review.field.finishedAt'), width: 170, ellipsis: true },
  { colKey: 'build_error', title: t('review.field.error'), minWidth: 220, ellipsis: true },
  { colKey: 'operation', title: t('review.field.operation'), width: 120, align: 'center', fixed: 'right' },
]);

function isBuildTaskTerminal(status: string | null | undefined): boolean {
  /**
   * 判断索引任务是否已经结束。
   */
  return Boolean(status && BUILD_TASK_TERMINAL_STATUS.includes(status));
}

function setPendingBuild(documentId: number, pending: boolean): void {
  /**
   * 维护当前页面正在轮询的文档列表。
   */
  const exists = pendingBuildDocumentIds.value.includes(documentId);
  if (pending && !exists) {
    pendingBuildDocumentIds.value = [...pendingBuildDocumentIds.value, documentId];
    return;
  }
  if (!pending && exists) {
    pendingBuildDocumentIds.value = pendingBuildDocumentIds.value.filter((item) => item !== documentId);
  }
}

function isBuilding(documentId: number): boolean {
  /**
   * 判断指定文档是否处于任务排队或执行中。
   */
  return pendingBuildDocumentIds.value.includes(documentId);
}

function getLatestBuildTask(documentId: number): IndexTaskInfo | null {
  /**
   * 获取当前页面缓存的最新构建任务。
   */
  return latestBuildTaskMap.value[documentId] || null;
}

function getTaskStatusText(documentId: number): string {
  /**
   * 获取任务状态中文文案。
   */
  const task = getLatestBuildTask(documentId);
  if (!task) return '';
  return indexTaskStatusText(task.status);
}

function updateLatestBuildTask(task: IndexTaskInfo): void {
  /**
   * 更新文档最新构建任务缓存。
   */
  latestBuildTaskMap.value = {
    ...latestBuildTaskMap.value,
    [task.document_id]: task,
  };
}

function pickLatestBuildTask(taskList: IndexTaskInfo[]): IndexTaskInfo | null {
  /**
   * 从接口返回的任务列表中选出最新的 full_build 任务。
   */
  return taskList.find((item) => item.task_type === BUILD_TASK_TYPE) || taskList[0] || null;
}

function stopBuildPolling(): void {
  /**
   * 停止全局构建轮询定时器。
   */
  if (buildPollTimer.value !== null) {
    window.clearInterval(buildPollTimer.value);
    buildPollTimer.value = null;
  }
}

function ensureBuildPolling(): void {
  /**
   * 在存在待观察任务时启动全局轮询。
   */
  if (buildPollTimer.value !== null || !pendingBuildDocumentIds.value.length) return;
  buildPollTimer.value = window.setInterval(() => {
    void pollBuildTasks();
  }, BUILD_POLL_INTERVAL_MS);
}

function syncRunningDocuments(documents: DocumentInfo[]): void {
  /**
   * 根据文档索引状态补充需要轮询的文档。
   */
  for (const document of documents) {
    if (['parsing', 'indexing'].includes(document.index_status)) {
      setPendingBuild(document.id, true);
    }
  }
  ensureBuildPolling();
}

async function loadTasks(): Promise<void> {
  /**
   * 根据审核状态加载审核任务列表。
   */
  tasksLoading.value = true;
  try {
    const result = await listReviewTasks({
      status: taskStatus.value || undefined,
      project_id: taskProjectId.value ?? undefined,
      page: taskPage.value,
      page_size: taskPageSize.value,
    });
    tasks.value = result.items;
    taskTotal.value = result.total;
    taskPage.value = result.page;
    taskPageSize.value = result.page_size;
  } finally {
    tasksLoading.value = false;
  }
}

async function loadProjects(): Promise<void> {
  /**
   * 加载项目下拉选项，用于项目资料构建进度筛选。
   */
  projects.value = await listProjects();
}

async function loadCategories(): Promise<void> {
  /**
   * 按企业或项目范围加载分类树，项目资料必须先选择项目。
   */
  approvedFilters.category_id = null;
  if (!approvedFilters.scope_type) {
    categories.value = [];
    return;
  }
  if (approvedFilters.scope_type === 'project' && !approvedFilters.project_id) {
    categories.value = [];
    return;
  }
  categories.value = await listKnowledgeCategories({
    scope_type: approvedFilters.scope_type,
    project_id: approvedFilters.scope_type === 'project' ? approvedFilters.project_id : null,
  });
}

async function loadApprovedDocuments(showLoading = true): Promise<void> {
  /**
    * 加载审核通过资料，并同步当前页面的构建轮询状态。
    */
  if (showLoading) {
    approvedLoading.value = true;
  }
  try {
    const result = await listApprovedDocuments({
      scope_type: approvedFilters.scope_type || undefined,
      project_id: approvedFilters.scope_type === 'project' ? approvedFilters.project_id : null,
      category_id: approvedFilters.category_id,
      index_status: approvedFilters.index_status || undefined,
      keyword: approvedFilters.keyword.trim() || undefined,
      page: approvedPage.value,
      page_size: approvedPageSize.value,
    });
    approvedDocuments.value = result.items;
    approvedTotal.value = result.total;
    approvedPage.value = result.page;
    approvedPageSize.value = result.page_size;
    syncRunningDocuments(approvedDocuments.value);
  } finally {
    if (showLoading) {
      approvedLoading.value = false;
    }
  }
}

async function refreshActiveTab(): Promise<void> {
  /**
   * 根据当前页签刷新对应数据，减少不必要请求。
   */
  if (activeTab.value === 'tasks') {
    await loadTasks();
    return;
  }
  await loadApprovedDocuments();
}

async function decide(action: 'approve' | 'reject', task: ReviewTask): Promise<void> {
  /**
   * 执行审核动作并刷新审核任务列表。
   */
  if (action === 'approve' && !canApproveTask.value) {
    MessagePlugin.warning(t('review.message.noApprovePermission'));
    return;
  }
  if (action === 'reject' && !canRejectTask.value) {
    MessagePlugin.warning(t('review.message.noRejectPermission'));
    return;
  }
  if (action === 'reject') {
    openRejectDialog(task);
    return;
  }
  await approveReviewTask(task.id);
  MessagePlugin.success(t('review.message.reviewDone'));
  await loadTasks();
}

function openRejectDialog(task: ReviewTask): void {
  batchRejectMode.value = false;
  pendingRejectTask.value = task;
  rejectForm.comment = '';
  rejectDialogVisible.value = true;
}

function closeRejectDialog(): void {
  if (rejectSubmitting.value) return;
  rejectDialogVisible.value = false;
  pendingRejectTask.value = null;
  batchRejectMode.value = false;
  rejectForm.comment = '';
}

async function confirmRejectTask(): Promise<void> {
  const comment = rejectForm.comment.trim();
  if (!comment) {
    MessagePlugin.warning(t('review.message.rejectReasonRequired'));
    return;
  }
  if (!batchRejectMode.value && !pendingRejectTask.value) return;

  rejectSubmitting.value = true;
  try {
    if (batchRejectMode.value) {
      const result = await rejectReviewTasksBatch(selectedTaskIds.value, comment);
      showBatchResult(t('review.batch.rejectTitle'), result.results.map((item) => ({ id: item.task_id, success: item.success, message: item.message })));
      selectedTaskIds.value = [];
    } else if (pendingRejectTask.value) {
      await rejectReviewTask(pendingRejectTask.value.id, comment);
      MessagePlugin.success(t('review.message.rejected'));
    }
    rejectDialogVisible.value = false;
    pendingRejectTask.value = null;
    batchRejectMode.value = false;
    rejectForm.comment = '';
    await loadTasks();
  } finally {
    rejectSubmitting.value = false;
  }
}

function showBatchResult(title: string, results: Array<{ id?: number; success: boolean; message: string }>): void {
  const failed = results.filter((item) => !item.success);
  const successCount = results.length - failed.length;
  if (!failed.length) {
    MessagePlugin.success(t('review.batch.successSummary', { title, count: successCount }));
    return;
  }
  DialogPlugin.alert({
    header: t('review.batch.complete', { title }),
    body: [
      t('review.batch.failedSummary', { success: successCount, failed: failed.length }),
      ...failed.map((item) => t('review.batch.failedItem', { id: item.id ?? '-', message: item.message })),
    ].join('\n'),
    theme: successCount ? 'warning' : 'danger',
    confirmBtn: t('review.action.acknowledge'),
  });
}

async function runBatchApprove(): Promise<void> {
  if (!selectedTaskIds.value.length || batchSubmitting.value) return;
  const confirmed = await showConfirmDialog({
    header: t('review.batch.approveConfirmTitle'),
    body: t('review.batch.approveConfirmBody', { count: selectedTaskIds.value.length }),
    confirmBtn: t('review.batch.approveConfirm'),
  });
  if (!confirmed) return;
  batchSubmitting.value = true;
  try {
    const result = await approveReviewTasksBatch(selectedTaskIds.value);
    showBatchResult(t('review.batch.approveTitle'), result.results.map((item) => ({ id: item.task_id, success: item.success, message: item.message })));
    selectedTaskIds.value = [];
    await loadTasks();
  } finally {
    batchSubmitting.value = false;
  }
}

function openBatchRejectDialog(): void {
  if (!selectedTaskIds.value.length || batchSubmitting.value) return;
  batchRejectMode.value = true;
  pendingRejectTask.value = null;
  rejectForm.comment = '';
  rejectDialogVisible.value = true;
}

async function runBatchBuild(): Promise<void> {
  const selectableDocumentIds = new Set(
    approvedDocuments.value.filter(canSelectForBatchBuild).map((document) => document.id),
  );
  const documentIds = selectedDocumentIds.value.filter((documentId) => selectableDocumentIds.has(documentId));
  if (!documentIds.length || batchSubmitting.value) return;
  const confirmed = await showConfirmDialog({
    header: t('review.batch.buildConfirmTitle'),
    body: t('review.batch.buildConfirmBody', { count: documentIds.length, notice: '' }),
    confirmBtn: t('review.action.startBuild'),
  });
  if (!confirmed) return;

  batchSubmitting.value = true;
  try {
    const result = await createDocumentIndexBuildTasksBatch(documentIds);
    for (const item of result.results) {
      if (item.success && item.task) {
        updateLatestBuildTask(item.task);
        setPendingBuild(item.document_id || item.task.document_id, true);
      }
    }
    ensureBuildPolling();
    showBatchResult(
      t('review.batch.buildTitle'),
      result.results.map((item) => ({ id: item.document_id, success: item.success, message: item.message })),
    );
    selectedDocumentIds.value = [];
    await loadApprovedDocuments();
    void pollBuildTasks();
  } finally {
    batchSubmitting.value = false;
  }
}

async function syncBuildTask(documentId: number): Promise<boolean> {
  /**
   * 拉取单个文档的最新构建任务状态。
   *
   * 返回:
   *   true 表示任务已经结束，false 表示仍需继续轮询。
   */
  const taskList = await listDocumentIndexTasks(documentId);
  const latestTask = pickLatestBuildTask(taskList);
  if (!latestTask) {
    return false;
  }

  updateLatestBuildTask(latestTask);

  if (BUILD_TASK_RUNNING_STATUS.includes(latestTask.status)) {
    setPendingBuild(documentId, true);
    return false;
  }

  if (isBuildTaskTerminal(latestTask.status)) {
    setPendingBuild(documentId, false);
    if (!notifiedTaskIds.has(latestTask.id)) {
      notifiedTaskIds.add(latestTask.id);
      if (latestTask.status === 'success') {
        MessagePlugin.success(t('review.message.buildComplete', { id: documentId }));
      } else {
        MessagePlugin.error(latestTask.error_message || t('review.message.buildFailed', { id: documentId }));
      }
    }
    return true;
  }

  return false;
}

async function pollBuildTasks(): Promise<void> {
  /**
   * 轮询当前页面所有待观察文档的构建任务。
   */
  if (buildPollingBusy.value || !pendingBuildDocumentIds.value.length) return;

  buildPollingBusy.value = true;
  try {
    const documentIds = [...pendingBuildDocumentIds.value];
    let shouldRefreshDocuments = false;

    await Promise.all(
      documentIds.map(async (documentId) => {
        try {
          const finished = await syncBuildTask(documentId);
          if (finished) {
            shouldRefreshDocuments = true;
          }
        } catch (error) {
          setPendingBuild(documentId, false);
          MessagePlugin.error(error instanceof Error ? error.message : t('review.message.buildStatusLoadFailed', { id: documentId }));
        }
      }),
    );

    if (shouldRefreshDocuments || activeTab.value === 'approved') {
      await loadApprovedDocuments(false);
    }
  } finally {
    buildPollingBusy.value = false;
    if (!pendingBuildDocumentIds.value.length) {
      stopBuildPolling();
    }
  }
}

async function runBuild(document: DocumentInfo): Promise<void> {
  /**
   * 创建异步“解析并构建索引”任务，并启动前端轮询。
   */
  if (isIndexedIndexStatus(document.index_status)) {
    const confirmed = await confirmRebuildIndexedDocument(approvedDocumentName(document));
    if (!confirmed) return;
  }
  try {
    const task = await createDocumentIndexBuildTask(document.id);
    updateLatestBuildTask(task);
    setPendingBuild(document.id, true);
    ensureBuildPolling();
    MessagePlugin.success(t('review.message.buildTaskCreated'));
    await loadApprovedDocuments();
    void pollBuildTasks();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('review.message.buildTaskCreateFailed'));
    await loadApprovedDocuments();
  }
}

function canRunBuild(document: DocumentInfo): boolean {
  /**
   * 审核权限控制构建按钮，执行中状态不允许重复触发。
   */
  return canBuildIndex.value && document.review_status === 'approved' && !isBuilding(document.id) && !['parsing', 'indexing'].includes(document.index_status);
}

function canSelectForBatchBuild(document: DocumentInfo): boolean {
  /**
   * 批量构建只处理尚未构建或上次构建失败的资料，已索引资料需通过单条操作明确确认重建。
   */
  return canRunBuild(document) && BATCH_BUILD_SELECTABLE_STATUS.includes(document.index_status);
}

function projectOptionLabel(project: ProjectInfo): string {
  return project.project_name || project.name || t('review.scope.projectFallback', { id: project.id });
}

function routeQueryText(value: unknown): string {
  const rawValue = Array.isArray(value) ? value[0] : value;
  return typeof rawValue === 'string' ? rawValue : '';
}

function parseProjectIdValue(value: unknown): number | null {
  const numericValue = Number(routeQueryText(value));
  return Number.isInteger(numericValue) && numericValue > 0 ? numericValue : null;
}

function applyRouteQueryFilters(): void {
  /**
   * 从外部入口带入审核中心筛选条件，确保项目详情页跳转后不会落到全局待审列表。
   */
  const routeProjectId = parseProjectIdValue(route.query.projectId ?? route.query.project_id);
  taskProjectId.value = routeProjectId;
  if (routeProjectId) {
    approvedFilters.scope_type = 'project';
    approvedFilters.project_id = routeProjectId;
  }

  const routeStatus = ROUTE_REVIEW_STATUS_MAP[routeQueryText(route.query.status)];
  if (routeStatus) {
    taskStatus.value = routeStatus;
  }

  const routeTab = routeQueryText(route.query.tab);
  if (routeTab === 'tasks' || routeTab === 'approved') {
    activeTab.value = routeTab;
  }
}

function taskFileName(task: ReviewTask): string {
  /**
   * 审核任务兼容历史数据，文档展示字段缺失时回退到文档ID。
   */
  return task.document_file_name || t('review.scope.documentFallback', { id: task.document_id });
}

function taskCategoryLabel(task: ReviewTask): string {
  return task.document_category_path || task.document_category_name || '-';
}

function taskUploaderLabel(task: ReviewTask): string {
  return task.uploader_name || task.uploader_username || (task.uploader_id ? t('review.scope.userFallback', { id: task.uploader_id }) : '-');
}

function taskVersionLabel(task: ReviewTask): string {
  const versionNo = task.display_version_no ?? task.version_no;
  return versionNo ? `v${versionNo}` : '-';
}

function approvedDocumentName(document: DocumentInfo): string {
  return document.document_name || document.file_name || '-';
}

function openReviewDetail(task: ReviewTask): void {
  router.push(withBreadcrumbContext(route, `/reviews/${task.id}`));
}

function openApprovedDocument(document: DocumentInfo): void {
  router.push(withBreadcrumbContext(route, `/documents/${document.id}`));
}

function approvedScopeLabel(document: DocumentInfo): string {
  if (document.knowledge_type !== 'project') {
    return t('review.scope.base');
  }
  const project = projects.value.find((item) => item.id === document.project_id);
  if (project) {
    return projectOptionLabel(project);
  }
  return document.project_id ? t('review.scope.projectFallback', { id: document.project_id }) : t('review.scope.project');
}

function approvedVersionLabel(document: DocumentInfo): string {
  return document.version_no ? `v${document.version_no}` : '-';
}

function buildActionLabel(document: DocumentInfo): string {
  if (isBuilding(document.id) || document.index_status === 'indexing') {
    return t('review.action.building');
  }
  return isIndexedIndexStatus(document.index_status) ? t('review.action.rebuild') : t('review.action.buildIndex');
}

function handleTaskSearch(): void {
  selectedTaskIds.value = [];
  taskPage.value = 1;
  void loadTasks();
}

function resetTaskFilters(): void {
  selectedTaskIds.value = [];
  taskProjectId.value = null;
  taskStatus.value = '';
  taskPage.value = 1;
  void loadTasks();
}

function refreshTasks(): void {
  selectedTaskIds.value = [];
  void loadTasks();
}

function handleTaskPaginationChange(pageInfo: PaginationInfo): void {
  selectedTaskIds.value = [];
  taskPage.value = pageInfo.current;
  taskPageSize.value = pageInfo.pageSize;
  void loadTasks();
}

function handleApprovedSearch(): void {
  selectedDocumentIds.value = [];
  approvedPage.value = 1;
  void loadApprovedDocuments();
}

function resetApprovedFilters(): void {
  selectedDocumentIds.value = [];
  approvedFilters.scope_type = '';
  approvedFilters.project_id = null;
  approvedFilters.category_id = null;
  approvedFilters.index_status = '';
  approvedFilters.keyword = '';
  approvedPage.value = 1;
  void loadApprovedDocuments();
}

function refreshApprovedDocuments(): void {
  selectedDocumentIds.value = [];
  void loadApprovedDocuments();
}

function handleApprovedPaginationChange(pageInfo: PaginationInfo): void {
  selectedDocumentIds.value = [];
  approvedPage.value = pageInfo.current;
  approvedPageSize.value = pageInfo.pageSize;
  void loadApprovedDocuments();
}

function handleTabChange(value: unknown): void {
  /**
   * 切换审核中心页签并加载目标页签数据。
   */
  if (value !== 'tasks' && value !== 'approved') return;
  selectedTaskIds.value = [];
  selectedDocumentIds.value = [];
  const nextTab = value as ReviewTab;
  if (route.query.tab !== nextTab) {
    void router.replace({ path: route.path, query: { ...route.query, tab: nextTab } });
    return;
  }
  activeTab.value = nextTab;
  void refreshActiveTab();
}

function handleTaskSelectChange(keys: Array<string | number>): void {
  selectedTaskIds.value = keys.map(Number).filter((item) => Number.isInteger(item));
}

function handleDocumentSelectChange(keys: Array<string | number>): void {
  const selectableDocumentIds = new Set(
    approvedDocuments.value.filter(canSelectForBatchBuild).map((document) => document.id),
  );
  selectedDocumentIds.value = keys
    .map(Number)
    .filter((documentId) => Number.isInteger(documentId) && selectableDocumentIds.has(documentId));
}

watch(
  () => [approvedFilters.scope_type, approvedFilters.project_id],
  () => {
    /**
     * 范围或项目变化后重新加载分类树，避免项目间分类串用。
     */
    void loadCategories();
  },
);

watch(
  () => [route.query.projectId, route.query.project_id, route.query.status, route.query.tab],
  () => {
    applyRouteQueryFilters();
    taskPage.value = 1;
    approvedPage.value = 1;
    void refreshActiveTab();
  },
);

onMounted(async () => {
  /**
   * 初始化审核中心基础数据。
   */
  applyRouteQueryFilters();
  await Promise.all([loadProjects(), loadCategories(), loadStatusOptions()]);
  await refreshActiveTab();
});

onBeforeUnmount(() => {
  /**
   * 页面卸载时停止轮询，避免遗留定时器。
   */
  stopBuildPolling();
});
</script>

<template>
  <PageContainer :title="t('review.title.center')" :subtitle="t('review.subtitle.center')">
    <div class="system-card scroll-card review-card">
      <t-tabs class="review-tabs" :value="activeTab" @change="handleTabChange">
        <t-tab-panel value="tasks" :label="t('review.tab.tasks')" />
        <t-tab-panel value="approved" :label="t('review.tab.approved')" />
      </t-tabs>

      <template v-if="activeTab === 'tasks'">
        <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
          <t-form-item :label="t('review.field.project')">
            <t-select v-model="taskProjectId" class="review-project-select" clearable :placeholder="t('review.placeholder.allProjects')" @change="handleTaskSearch">
              <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="projectOptionLabel(project)" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('review.field.reviewStatus')">
            <t-select v-model="taskStatus" class="filter-select" clearable :placeholder="t('review.placeholder.allStatus')" @change="handleTaskSearch">
              <t-option v-for="item in taskStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
          <t-form-item>
            <t-space>
              <t-button theme="primary" :loading="tasksLoading" @click="handleTaskSearch">{{ t('common.action.search') }}</t-button>
              <t-button @click="resetTaskFilters">{{ t('common.action.reset') }}</t-button>
            </t-space>
          </t-form-item>
        </t-form>

        <div class="system-section-head">
          <div class="system-section-title">
            <h2>{{ t('review.tab.tasks') }}</h2>
            <span>{{ t('review.table.taskCount', { count: taskTotal }) }}</span>
          </div>
          <t-space>
            <t-button
              theme="success"
              :disabled="!selectedTaskIds.length || !canApproveTask || batchSubmitting"
              :loading="batchSubmitting"
              @click="runBatchApprove"
            >
              {{ t('review.action.batchApprove', { count: selectedTaskIds.length }) }}
            </t-button>
            <t-button
              theme="danger"
              :disabled="!selectedTaskIds.length || !canRejectTask || batchSubmitting"
              @click="openBatchRejectDialog"
            >
              {{ t('review.action.batchReject') }}
            </t-button>
            <t-button theme="default" variant="outline" :loading="tasksLoading" @click="refreshTasks">
              <template #icon><RefreshIcon /></template>
              {{ t('common.action.refresh') }}
            </t-button>
          </t-space>
        </div>

        <div class="table-scroll">
          <t-table
            row-key="id"
            bordered
            table-layout="fixed"
            vertical-align="top"
            :data="tasks"
            :columns="taskColumns"
            :loading="tasksLoading"
            :selected-row-keys="selectedTaskIds"
            :empty="t('review.table.emptyTasks')"
            @select-change="handleTaskSelectChange"
          >
            <template #file_name="{ row }">
              <t-link theme="primary" @click="openReviewDetail(row)">
                {{ taskFileName(row) }}
              </t-link>
            </template>
            <template #category="{ row }">
              {{ taskCategoryLabel(row) }}
            </template>
            <template #uploader="{ row }">
              {{ taskUploaderLabel(row) }}
            </template>
            <template #created_at="{ row }">
              {{ formatDateTime(row.created_at) }}
            </template>
            <template #version="{ row }">
              {{ taskVersionLabel(row) }}
            </template>
            <template #review_status="{ row }">
              <StatusTag type="review" :value="row.review_status" />
            </template>
            <template #review_comment="{ row }">
              <span class="review-cell-text">{{ row.review_comment || '-' }}</span>
            </template>
            <template #operation="{ row }">
              <div class="row-actions">
                <TableActionButton :label="t('review.action.detail')" @click="openReviewDetail(row)">
                  <FileSearchIcon />
                </TableActionButton>
                <TableActionButton
                  :label="t('review.action.approve')"
                  :permission="PERMISSIONS.REVIEW_APPROVE"
                  theme="success"
                  :disabled="!canApproveTask || !isReviewTaskPending(row.review_status)"
                  @click="decide('approve', row)"
                >
                  <CheckCircleIcon />
                </TableActionButton>
                <TableActionButton
                  :label="t('review.action.reject')"
                  :permission="PERMISSIONS.REVIEW_REJECT"
                  theme="danger"
                  :disabled="!canRejectTask || !isReviewTaskPending(row.review_status)"
                  @click="decide('reject', row)"
                >
                  <CloseCircleIcon />
                </TableActionButton>
              </div>
            </template>
          </t-table>
        </div>
        <div class="system-pagination">
          <t-pagination
            :current="taskPage"
            :page-size="taskPageSize"
            :total="taskTotal"
            :page-size-options="PAGE_SIZE_OPTIONS"
            show-jumper
            @change="handleTaskPaginationChange"
          />
        </div>
      </template>

      <template v-else>
        <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
          <t-form-item :label="t('review.field.scope')">
            <t-select v-model="approvedFilters.scope_type" class="filter-select" clearable :placeholder="t('review.placeholder.allScope')" @change="handleApprovedSearch">
              <t-option value="base" :label="t('review.scope.base')" />
              <t-option value="project" :label="t('review.scope.project')" />
            </t-select>
          </t-form-item>
          <t-form-item v-if="approvedFilters.scope_type === 'project'" :label="t('review.field.project')">
            <t-select
              v-model="approvedFilters.project_id"
              class="review-project-select"
              clearable
              :placeholder="t('review.placeholder.allProjects')"
              @change="handleApprovedSearch"
            >
              <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="projectOptionLabel(project)" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('review.field.category')">
            <t-select
              v-model="approvedFilters.category_id"
              class="review-category-select"
              clearable
              :disabled="!approvedFilters.scope_type || (approvedFilters.scope_type === 'project' && !approvedFilters.project_id)"
              :placeholder="t('review.placeholder.allCategories')"
              @change="handleApprovedSearch"
            >
              <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('review.field.buildStatus')">
            <t-select v-model="approvedFilters.index_status" class="filter-select" clearable :placeholder="t('review.placeholder.allStatus')" @change="handleApprovedSearch">
              <t-option v-for="item in buildStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
          <t-form-item :label="t('review.field.keyword')">
            <t-input v-model="approvedFilters.keyword" class="review-keyword-input" clearable :placeholder="t('review.placeholder.searchDocument')" @enter="handleApprovedSearch" />
          </t-form-item>
          <t-form-item>
            <t-space>
              <t-button theme="primary" :loading="approvedLoading" @click="handleApprovedSearch">{{ t('common.action.search') }}</t-button>
              <t-button @click="resetApprovedFilters">{{ t('common.action.reset') }}</t-button>
            </t-space>
          </t-form-item>
        </t-form>

        <div class="system-section-head">
          <div class="system-section-title">
            <h2>{{ t('review.tab.approved') }}</h2>
            <span>{{ t('review.table.approvedCount', { count: approvedTotal }) }}</span>
          </div>
          <t-space>
            <t-button
              theme="primary"
              :disabled="!selectedDocumentIds.length || !canBuildIndex || batchSubmitting"
              :loading="batchSubmitting"
              @click="runBatchBuild"
            >
              {{ t('review.action.batchBuild', { count: selectedDocumentIds.length }) }}
            </t-button>
            <t-button theme="default" variant="outline" :loading="approvedLoading" @click="refreshApprovedDocuments">
              <template #icon><RefreshIcon /></template>
              {{ t('common.action.refresh') }}
            </t-button>
          </t-space>
        </div>

        <div class="table-scroll">
          <t-table
            row-key="id"
            bordered
            table-layout="fixed"
            vertical-align="top"
            :data="approvedDocuments"
            :columns="approvedColumns"
            :loading="approvedLoading"
            :selected-row-keys="selectedDocumentIds"
            :empty="t('review.table.emptyApproved')"
            @select-change="handleDocumentSelectChange"
          >
            <template #document="{ row }">
              <t-link theme="primary" @click="openApprovedDocument(row)">
                {{ approvedDocumentName(row) }}
              </t-link>
            </template>
            <template #scope="{ row }">
              {{ approvedScopeLabel(row) }}
            </template>
            <template #category="{ row }">
              {{ row.category_path || row.category_name || '-' }}
            </template>
            <template #version="{ row }">
              {{ approvedVersionLabel(row) }}
            </template>
            <template #index_status="{ row }">
              <div class="status-stack">
                <StatusTag type="index" :value="row.index_status" />
                <span v-if="getLatestBuildTask(row.id)" class="task-status-text">{{ t('review.table.latestTask', { status: getTaskStatusText(row.id) }) }}</span>
              </div>
            </template>
            <template #build_started_at="{ row }">
              {{ formatDateTime(row.build_started_at) }}
            </template>
            <template #build_finished_at="{ row }">
              {{ formatDateTime(row.build_finished_at) }}
            </template>
            <template #build_error="{ row }">
              <span class="error-cell">{{ row.build_error || '-' }}</span>
            </template>
            <template #operation="{ row }">
              <div class="row-actions">
                <TableActionButton
                  :label="buildActionLabel(row)"
                  :permission="PERMISSIONS.REVIEW_BUILD_INDEX"
                  theme="primary"
                  :loading="isBuilding(row.id)"
                  :disabled="!canRunBuild(row)"
                  @click="runBuild(row)"
                >
                  <PlayCircleIcon />
                </TableActionButton>
              </div>
            </template>
          </t-table>
        </div>
        <div class="system-pagination">
          <t-pagination
            :current="approvedPage"
            :page-size="approvedPageSize"
            :total="approvedTotal"
            :page-size-options="PAGE_SIZE_OPTIONS"
            show-jumper
            @change="handleApprovedPaginationChange"
          />
        </div>
      </template>
    </div>

    <t-dialog
      v-model:visible="rejectDialogVisible"
      :header="batchRejectMode ? t('review.rejectDialog.batchTitle') : t('review.rejectDialog.singleTitle')"
      width="520px"
      :confirm-btn="{ content: t('review.rejectDialog.confirm'), theme: 'danger', loading: rejectSubmitting }"
      :cancel-btn="{ content: t('common.action.cancel'), disabled: rejectSubmitting }"
      :close-on-overlay-click="!rejectSubmitting"
      @confirm="confirmRejectTask"
      @close="closeRejectDialog"
    >
      <t-form label-align="top">
        <t-form-item :label="t('review.field.rejectTarget')">
          <span class="reject-document-name">{{ pendingRejectTaskName || '-' }}</span>
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
  </PageContainer>
</template>

<style scoped>
.system-card {
  display: flex;
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  margin-top: 0;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow: hidden;
  padding: 16px;
}

.review-tabs {
  flex: 0 0 auto;
  margin-bottom: 18px;
}

.system-filter-form {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 14px;
  margin-bottom: 18px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 14px 16px;
}

.system-filter-form :deep(.t-form__item) {
  margin: 0;
}

.system-filter-form :deep(.t-form__label) {
  width: auto !important;
  padding-right: 8px;
}

.system-filter-form :deep(.t-form__controls) {
  margin-left: 0 !important;
}

.filter-select {
  width: 160px;
}

.review-project-select,
.review-category-select {
  width: 220px;
}

.review-keyword-input {
  width: 240px;
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
  flex: 1;
  min-height: 240px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow: auto;
  scrollbar-gutter: auto;
}

.table-scroll :deep(.t-table) {
  --td-table-border-color: #edf2f7;
  min-width: 1320px;
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

.system-pagination {
  display: flex;
  flex: 0 0 auto;
  justify-content: flex-end;
  padding-top: 12px;
}

.row-actions {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.status-stack {
  display: inline-flex;
  align-items: center;
  flex-direction: column;
  gap: 4px;
  max-width: 100%;
}

.task-status-text {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.4;
}

.review-cell-text,
.error-cell {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
}

.error-cell {
  color: #dc2626;
}

.reject-document-name {
  color: #0f172a;
  font-weight: 600;
  line-height: 1.5;
  word-break: break-word;
}

@media (max-width: 820px) {
  .system-section-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .filter-select,
  .review-project-select,
  .review-category-select,
  .review-keyword-input {
    width: 100%;
  }
}
</style>
