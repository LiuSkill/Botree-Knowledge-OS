<!--
  Review Task Page

  负责：
  1. 展示审核任务并支持通过、驳回
  2. 展示审核通过资料和索引构建状态
  3. 通过异步索引任务触发“解析并构建索引”，避免前端长时间阻塞
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { CheckCircleIcon, CloseCircleIcon, FileSearchIcon, PlayCircleIcon, RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { createDocumentIndexBuildTask, listDocumentIndexTasks } from '@/api/documents';
import { listKnowledgeCategories } from '@/api/knowledgeCategories';
import { listProjects } from '@/api/projects';
import { approveReviewTask, listApprovedDocuments, listReviewTasks, rejectReviewTask } from '@/api/reviews';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { DocumentInfo, IndexTaskInfo, KnowledgeCategory, ProjectInfo, ReviewTask } from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { buildCategoryOptions } from '@/utils/categories';
import { INDEX_STATUS_TEXT, INDEX_TASK_STATUS_TEXT, REVIEW_TASK_STATUS, isReviewTaskPending } from '@/utils/constants';
import { formatDateTime } from '@/utils/format';
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
const activeTab = ref<ReviewTab>('tasks');
const taskStatus = ref('');
const taskProjectId = ref<number | null>(null);
const tasks = ref<ReviewTask[]>([]);
const approvedDocuments = ref<DocumentInfo[]>([]);
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

const buildStatusOptions = computed(() => {
  /**
   * 构建进度筛选项统一来自状态常量，避免页面散落魔法字符串。
   */
  return Object.entries(INDEX_STATUS_TEXT).map(([value, label]) => ({ value, label }));
});
const rejectDialogVisible = ref(false);
const rejectSubmitting = ref(false);
const pendingRejectTask = ref<ReviewTask | null>(null);
const rejectForm = reactive({
  comment: '',
});
const pendingRejectTaskName = computed(() => (pendingRejectTask.value ? taskFileName(pendingRejectTask.value) : ''));

const taskColumns = [
  { colKey: 'file_name', title: '文件名', minWidth: 240, ellipsis: true },
  { colKey: 'category', title: '文件分类', width: 180, ellipsis: true },
  { colKey: 'uploader', title: '上传人员', width: 120, ellipsis: true },
  { colKey: 'created_at', title: '提交时间', width: 170, ellipsis: true },
  { colKey: 'version', title: '版本', width: 80, align: 'center' },
  { colKey: 'review_status', title: '状态', width: 110, align: 'center' },
  { colKey: 'review_comment', title: '审核意见', minWidth: 180, ellipsis: true },
  { colKey: 'operation', title: '操作', width: 160, align: 'center', fixed: 'right' },
];

const approvedColumns = [
  { colKey: 'document', title: '文档', minWidth: 260, ellipsis: true },
  { colKey: 'scope', title: '范围', width: 160, ellipsis: true },
  { colKey: 'category', title: '分类', width: 180, ellipsis: true },
  { colKey: 'version', title: '版本', width: 80, align: 'center' },
  { colKey: 'index_status', title: '构建状态', width: 140, align: 'center' },
  { colKey: 'build_started_at', title: '开始时间', width: 170, ellipsis: true },
  { colKey: 'build_finished_at', title: '完成时间', width: 170, ellipsis: true },
  { colKey: 'build_error', title: '错误', minWidth: 220, ellipsis: true },
  { colKey: 'operation', title: '操作', width: 120, align: 'center', fixed: 'right' },
];

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
  return INDEX_TASK_STATUS_TEXT[task.status] || task.status;
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
    MessagePlugin.warning('当前账号没有审核通过权限');
    return;
  }
  if (action === 'reject' && !canRejectTask.value) {
    MessagePlugin.warning('当前账号没有审核驳回权限');
    return;
  }
  if (action === 'reject') {
    openRejectDialog(task);
    return;
  }
  await approveReviewTask(task.id);
  MessagePlugin.success('审核操作已完成');
  await loadTasks();
}

function openRejectDialog(task: ReviewTask): void {
  pendingRejectTask.value = task;
  rejectForm.comment = '';
  rejectDialogVisible.value = true;
}

function closeRejectDialog(): void {
  if (rejectSubmitting.value) return;
  rejectDialogVisible.value = false;
  pendingRejectTask.value = null;
  rejectForm.comment = '';
}

async function confirmRejectTask(): Promise<void> {
  const comment = rejectForm.comment.trim();
  if (!comment) {
    MessagePlugin.warning('请填写驳回原因');
    return;
  }
  if (!pendingRejectTask.value) return;

  rejectSubmitting.value = true;
  try {
    await rejectReviewTask(pendingRejectTask.value.id, comment);
    MessagePlugin.success('已驳回该资料');
    rejectDialogVisible.value = false;
    pendingRejectTask.value = null;
    rejectForm.comment = '';
    await loadTasks();
  } finally {
    rejectSubmitting.value = false;
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
        MessagePlugin.success(`文档 #${documentId} 解析与索引已完成`);
      } else {
        MessagePlugin.error(latestTask.error_message || `文档 #${documentId} 构建失败`);
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
          MessagePlugin.error(error instanceof Error ? error.message : `文档 #${documentId} 构建状态获取失败`);
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
    MessagePlugin.success('构建任务已创建，后台开始解析与索引');
    await loadApprovedDocuments();
    void pollBuildTasks();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '构建任务创建失败');
    await loadApprovedDocuments();
  }
}

function canRunBuild(document: DocumentInfo): boolean {
  /**
   * 审核权限控制构建按钮，执行中状态不允许重复触发。
   */
  return canBuildIndex.value && document.review_status === 'approved' && !isBuilding(document.id) && !['parsing', 'indexing'].includes(document.index_status);
}

function projectOptionLabel(project: ProjectInfo): string {
  return project.project_name || project.name || `项目 #${project.id}`;
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
  return task.document_file_name || `文档 #${task.document_id}`;
}

function taskCategoryLabel(task: ReviewTask): string {
  return task.document_category_path || task.document_category_name || '-';
}

function taskUploaderLabel(task: ReviewTask): string {
  return task.uploader_name || task.uploader_username || (task.uploader_id ? `用户 #${task.uploader_id}` : '-');
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
    return '企业知识';
  }
  const project = projects.value.find((item) => item.id === document.project_id);
  if (project) {
    return projectOptionLabel(project);
  }
  return document.project_id ? `项目 #${document.project_id}` : '项目资料';
}

function approvedVersionLabel(document: DocumentInfo): string {
  return document.version_no ? `v${document.version_no}` : '-';
}

function buildActionLabel(document: DocumentInfo): string {
  if (isBuilding(document.id) || document.index_status === 'indexing') {
    return '索引构建中';
  }
  return isIndexedIndexStatus(document.index_status) ? '重新构建' : '解析并构建索引';
}

function handleTaskSearch(): void {
  taskPage.value = 1;
  void loadTasks();
}

function resetTaskFilters(): void {
  taskProjectId.value = null;
  taskStatus.value = '';
  taskPage.value = 1;
  void loadTasks();
}

function refreshTasks(): void {
  void loadTasks();
}

function handleTaskPaginationChange(pageInfo: PaginationInfo): void {
  taskPage.value = pageInfo.current;
  taskPageSize.value = pageInfo.pageSize;
  void loadTasks();
}

function handleApprovedSearch(): void {
  approvedPage.value = 1;
  void loadApprovedDocuments();
}

function resetApprovedFilters(): void {
  approvedFilters.scope_type = '';
  approvedFilters.project_id = null;
  approvedFilters.category_id = null;
  approvedFilters.index_status = '';
  approvedFilters.keyword = '';
  approvedPage.value = 1;
  void loadApprovedDocuments();
}

function refreshApprovedDocuments(): void {
  void loadApprovedDocuments();
}

function handleApprovedPaginationChange(pageInfo: PaginationInfo): void {
  approvedPage.value = pageInfo.current;
  approvedPageSize.value = pageInfo.pageSize;
  void loadApprovedDocuments();
}

function handleTabChange(value: unknown): void {
  /**
   * 切换审核中心页签并加载目标页签数据。
   */
  if (value !== 'tasks' && value !== 'approved') return;
  const nextTab = value as ReviewTab;
  if (route.query.tab !== nextTab) {
    void router.replace({ path: route.path, query: { ...route.query, tab: nextTab } });
    return;
  }
  activeTab.value = nextTab;
  void refreshActiveTab();
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
  await Promise.all([loadProjects(), loadCategories()]);
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
  <PageContainer title="审核中心" subtitle="审核通过后，资料进入索引构建页，由审核人员统一发起异步解析与索引构建任务">
    <div class="system-card scroll-card review-card">
      <t-tabs class="review-tabs" :value="activeTab" @change="handleTabChange">
        <t-tab-panel value="tasks" label="审核任务" />
        <t-tab-panel value="approved" label="索引构建" />
      </t-tabs>

      <template v-if="activeTab === 'tasks'">
        <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
          <t-form-item label="项目">
            <t-select v-model="taskProjectId" class="review-project-select" clearable placeholder="全部项目" @change="handleTaskSearch">
              <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="projectOptionLabel(project)" />
            </t-select>
          </t-form-item>
          <t-form-item label="审核状态">
            <t-select v-model="taskStatus" class="filter-select" clearable placeholder="全部状态" @change="handleTaskSearch">
              <t-option :value="REVIEW_TASK_STATUS.reviewing" label="待审核" />
              <t-option :value="REVIEW_TASK_STATUS.approved" label="已通过" />
              <t-option :value="REVIEW_TASK_STATUS.rejected" label="已驳回" />
            </t-select>
          </t-form-item>
          <t-form-item>
            <t-space>
              <t-button theme="primary" :loading="tasksLoading" @click="handleTaskSearch">查询</t-button>
              <t-button @click="resetTaskFilters">重置</t-button>
            </t-space>
          </t-form-item>
        </t-form>

        <div class="system-section-head">
          <div class="system-section-title">
            <h2>审核任务</h2>
            <span>共 {{ taskTotal }} 条数据</span>
          </div>
          <t-button theme="default" variant="outline" :loading="tasksLoading" @click="refreshTasks">
            <template #icon><RefreshIcon /></template>
            刷新
          </t-button>
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
            empty="暂无审核任务"
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
                <TableActionButton label="详情" @click="openReviewDetail(row)">
                  <FileSearchIcon />
                </TableActionButton>
                <TableActionButton
                  label="通过"
                  :permission="PERMISSIONS.REVIEW_APPROVE"
                  theme="success"
                  :disabled="!canApproveTask || !isReviewTaskPending(row.review_status)"
                  @click="decide('approve', row)"
                >
                  <CheckCircleIcon />
                </TableActionButton>
                <TableActionButton
                  label="驳回"
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
          <t-form-item label="资料范围">
            <t-select v-model="approvedFilters.scope_type" class="filter-select" clearable placeholder="全部范围" @change="handleApprovedSearch">
              <t-option value="base" label="企业知识" />
              <t-option value="project" label="项目资料" />
            </t-select>
          </t-form-item>
          <t-form-item v-if="approvedFilters.scope_type === 'project'" label="项目">
            <t-select
              v-model="approvedFilters.project_id"
              class="review-project-select"
              clearable
              placeholder="全部项目"
              @change="handleApprovedSearch"
            >
              <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="projectOptionLabel(project)" />
            </t-select>
          </t-form-item>
          <t-form-item label="分类">
            <t-select
              v-model="approvedFilters.category_id"
              class="review-category-select"
              clearable
              :disabled="!approvedFilters.scope_type || (approvedFilters.scope_type === 'project' && !approvedFilters.project_id)"
              placeholder="全部分类"
              @change="handleApprovedSearch"
            >
              <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
            </t-select>
          </t-form-item>
          <t-form-item label="构建状态">
            <t-select v-model="approvedFilters.index_status" class="filter-select" clearable placeholder="全部状态" @change="handleApprovedSearch">
              <t-option v-for="item in buildStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
            </t-select>
          </t-form-item>
          <t-form-item label="关键字">
            <t-input v-model="approvedFilters.keyword" class="review-keyword-input" clearable placeholder="搜索文档" @enter="handleApprovedSearch" />
          </t-form-item>
          <t-form-item>
            <t-space>
              <t-button theme="primary" :loading="approvedLoading" @click="handleApprovedSearch">查询</t-button>
              <t-button @click="resetApprovedFilters">重置</t-button>
            </t-space>
          </t-form-item>
        </t-form>

        <div class="system-section-head">
          <div class="system-section-title">
            <h2>索引构建</h2>
            <span>共 {{ approvedTotal }} 条数据</span>
          </div>
          <t-button theme="default" variant="outline" :loading="approvedLoading" @click="refreshApprovedDocuments">
            <template #icon><RefreshIcon /></template>
            刷新
          </t-button>
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
            empty="暂无审核通过资料"
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
                <span v-if="getLatestBuildTask(row.id)" class="task-status-text">任务：{{ getTaskStatusText(row.id) }}</span>
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
      header="填写驳回原因"
      width="520px"
      :confirm-btn="{ content: '确认驳回', theme: 'danger', loading: rejectSubmitting }"
      :cancel-btn="{ content: '取消', disabled: rejectSubmitting }"
      :close-on-overlay-click="!rejectSubmitting"
      @confirm="confirmRejectTask"
      @close="closeRejectDialog"
    >
      <t-form label-align="top">
        <t-form-item label="被驳回资料">
          <span class="reject-document-name">{{ pendingRejectTaskName || '-' }}</span>
        </t-form-item>
        <t-form-item label="驳回原因">
          <t-textarea
            v-model="rejectForm.comment"
            placeholder="请输入驳回原因，提交后会展示在资料详情中"
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
