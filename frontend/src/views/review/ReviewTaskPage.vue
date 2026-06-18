<!--
  Review Task Page

  负责：
  1. 展示审核任务并支持通过、驳回
  2. 展示审核通过资料和索引构建状态
  3. 通过异步索引任务触发“解析并构建索引”，避免前端长时间阻塞
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { CheckCircleIcon, CloseCircleIcon, FileSearchIcon, PlayCircleIcon } from 'tdesign-icons-vue-next';
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { createDocumentIndexBuildTask, listDocumentIndexTasks } from '@/api/documents';
import { listKnowledgeCategories } from '@/api/knowledgeCategories';
import { listProjects } from '@/api/projects';
import { approveReviewTask, listApprovedDocuments, listReviewTasks, rejectReviewTask } from '@/api/reviews';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import { useAuthStore } from '@/stores/auth';
import type { DocumentInfo, IndexTaskInfo, KnowledgeCategory, ProjectInfo, ReviewTask } from '@/types/api';
import { buildCategoryOptions } from '@/utils/categories';
import { INDEX_STATUS_TEXT, INDEX_TASK_STATUS_TEXT, REVIEW_TASK_STATUS, isReviewTaskPending } from '@/utils/constants';
import { formatDateTime } from '@/utils/format';

type ReviewTab = 'tasks' | 'approved';
type ScopeType = 'base' | 'project';

const BUILD_TASK_TYPE = 'full_build';
const BUILD_TASK_RUNNING_STATUS = ['pending', 'running'];
const BUILD_TASK_TERMINAL_STATUS = ['success', 'failed', 'canceled'];
const BUILD_POLL_INTERVAL_MS = 5000;

const router = useRouter();
const authStore = useAuthStore();
const activeTab = ref<ReviewTab>('tasks');
const taskStatus = ref('');
const tasks = ref<ReviewTask[]>([]);
const approvedDocuments = ref<DocumentInfo[]>([]);
const projects = ref<ProjectInfo[]>([]);
const categories = ref<KnowledgeCategory[]>([]);
const pendingBuildDocumentIds = ref<number[]>([]);
const latestBuildTaskMap = ref<Record<number, IndexTaskInfo | null>>({});
const buildPollTimer = ref<number | null>(null);
const buildPollingBusy = ref(false);
const notifiedTaskIds = new Set<number>();

const approvedFilters = reactive({
  scope_type: 'base' as ScopeType,
  project_id: null as number | null,
  category_id: null as number | null,
  index_status: '',
  keyword: '',
});

const categoryOptions = computed(() => buildCategoryOptions(categories.value));
const canBuildIndex = computed(() => authStore.hasActionPermission('review:build-index'));
const canReviewTask = computed(() => authStore.hasActionPermission('review:review'));

const buildStatusOptions = computed(() => {
  /**
   * 构建进度筛选项统一来自状态常量，避免页面散落魔法字符串。
   */
  return Object.entries(INDEX_STATUS_TEXT).map(([value, label]) => ({ value, label }));
});

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
  tasks.value = await listReviewTasks(taskStatus.value ? { status: taskStatus.value } : undefined);
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
  if (approvedFilters.scope_type === 'project' && !approvedFilters.project_id) {
    categories.value = [];
    return;
  }
  categories.value = await listKnowledgeCategories({
    scope_type: approvedFilters.scope_type,
    project_id: approvedFilters.scope_type === 'project' ? approvedFilters.project_id : null,
  });
}

async function loadApprovedDocuments(): Promise<void> {
  /**
   * 加载审核通过资料，并同步当前页面的构建轮询状态。
   */
  approvedDocuments.value = await listApprovedDocuments({
    scope_type: approvedFilters.scope_type,
    project_id: approvedFilters.scope_type === 'project' ? approvedFilters.project_id : null,
    category_id: approvedFilters.category_id,
    index_status: approvedFilters.index_status || undefined,
    keyword: approvedFilters.keyword.trim() || undefined,
  });
  syncRunningDocuments(approvedDocuments.value);
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
  if (!canReviewTask.value) {
    MessagePlugin.warning('当前账号没有审核操作权限');
    return;
  }
  if (action === 'approve') await approveReviewTask(task.id);
  if (action === 'reject') await rejectReviewTask(task.id);
  MessagePlugin.success('审核操作已完成');
  await loadTasks();
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
      await loadApprovedDocuments();
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

function handleTabChange(value: unknown): void {
  /**
   * 切换审核中心页签并加载目标页签数据。
   */
  activeTab.value = value as ReviewTab;
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

onMounted(async () => {
  /**
   * 初始化审核中心基础数据。
   */
  await Promise.all([loadTasks(), loadProjects(), loadCategories()]);
});

onBeforeUnmount(() => {
  /**
   * 页面卸载时停止轮询，避免遗留定时器。
   */
  stopBuildPolling();
});
</script>

<template>
  <PageContainer title="审核中心" subtitle="审核通过后，资料进入构建进度页，由审核人员统一发起异步解析与索引构建任务">
    <div class="review-page">
      <t-tabs :value="activeTab" @change="handleTabChange">
        <t-tab-panel value="tasks" label="审核任务" />
        <t-tab-panel value="approved" label="审核通过资料 / 构建进度" />
      </t-tabs>

      <t-card v-if="activeTab === 'tasks'" class="review-card scroll-card">
      <template #title>审核任务</template>
      <template #actions>
        <t-select v-model="taskStatus" clearable placeholder="审核状态" style="width: 180px" @change="loadTasks">
          <t-option :value="REVIEW_TASK_STATUS.reviewing" label="待审核" />
          <t-option :value="REVIEW_TASK_STATUS.approved" label="已通过" />
          <t-option :value="REVIEW_TASK_STATUS.rejected" label="已驳回" />
        </t-select>
      </template>

      <t-empty v-if="!tasks.length" description="暂无审核任务" />
      <div v-else class="table-scroll">
        <table class="plain-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>文件分类</th>
              <th>上传人员</th>
              <th>提交时间</th>
              <th>版本</th>
              <th>状态</th>
              <th>审核意见</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="task in tasks" :key="task.id">
              <td><t-link theme="primary" @click="router.push(`/documents/${task.document_id}`)">{{ taskFileName(task) }}</t-link></td>
              <td>{{ taskCategoryLabel(task) }}</td>
              <td>{{ taskUploaderLabel(task) }}</td>
              <td>{{ formatDateTime(task.created_at) }}</td>
              <td>{{ taskVersionLabel(task) }}</td>
              <td><StatusTag type="review" :value="task.review_status" /></td>
              <td>{{ task.review_comment || '-' }}</td>
              <td>
                <div class="row-actions">
                  <TableActionButton label="详情" @click="router.push(`/reviews/${task.id}`)">
                    <FileSearchIcon />
                  </TableActionButton>
                  <TableActionButton
                    label="通过"
                    permission="review:review"
                    theme="success"
                    :disabled="!canReviewTask || !isReviewTaskPending(task.review_status)"
                    @click="decide('approve', task)"
                  >
                    <CheckCircleIcon />
                  </TableActionButton>
                  <TableActionButton
                    label="驳回"
                    permission="review:review"
                    theme="danger"
                    :disabled="!canReviewTask || !isReviewTaskPending(task.review_status)"
                    @click="decide('reject', task)"
                  >
                    <CloseCircleIcon />
                  </TableActionButton>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      </t-card>

      <t-card v-else class="review-card scroll-card" title="审核通过资料 / 构建进度">
      <div class="filter-bar">
        <t-select v-model="approvedFilters.scope_type" style="width: 140px" @change="loadApprovedDocuments">
          <t-option value="base" label="企业知识" />
          <t-option value="project" label="项目资料" />
        </t-select>
        <t-select
          v-if="approvedFilters.scope_type === 'project'"
          v-model="approvedFilters.project_id"
          clearable
          placeholder="选择项目"
          style="width: 220px"
          @change="loadApprovedDocuments"
        >
          <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="project.name" />
        </t-select>
        <t-select v-model="approvedFilters.category_id" clearable placeholder="选择分类" style="width: 220px" @change="loadApprovedDocuments">
          <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
        </t-select>
        <t-select v-model="approvedFilters.index_status" clearable placeholder="构建状态" style="width: 160px" @change="loadApprovedDocuments">
          <t-option v-for="item in buildStatusOptions" :key="item.value" :value="item.value" :label="item.label" />
        </t-select>
        <t-input v-model="approvedFilters.keyword" clearable placeholder="搜索文档..." style="width: 220px" @enter="loadApprovedDocuments" />
        <t-button theme="primary" @click="loadApprovedDocuments">查询</t-button>
      </div>

      <t-empty v-if="!approvedDocuments.length" description="暂无审核通过资料" />
      <div v-else class="table-scroll">
        <table class="plain-table">
          <thead>
            <tr>
              <th>文档</th>
              <th>范围</th>
              <th>分类</th>
              <th>版本</th>
              <th>构建状态</th>
              <th>开始时间</th>
              <th>完成时间</th>
              <th>错误</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="document in approvedDocuments" :key="document.id">
              <td><t-link theme="primary" @click="router.push(`/documents/${document.id}`)">{{ document.file_name }}</t-link></td>
              <td>{{ document.knowledge_type === 'project' ? `项目 #${document.project_id}` : '企业知识' }}</td>
              <td>{{ document.category_path || document.category_name || '-' }}</td>
              <td>v{{ document.version_no }}</td>
              <td>
                <div class="status-stack">
                  <StatusTag type="index" :value="document.index_status" />
                  <span v-if="getLatestBuildTask(document.id)" class="task-status-text">任务：{{ getTaskStatusText(document.id) }}</span>
                </div>
              </td>
              <td>{{ formatDateTime(document.build_started_at) }}</td>
              <td>{{ formatDateTime(document.build_finished_at) }}</td>
              <td class="error-cell">{{ document.build_error || '-' }}</td>
              <td>
                <TableActionButton
                  :label="isBuilding(document.id) || document.index_status === 'indexing' ? '索引构建中' : document.index_status === 'indexed' ? '重新构建' : '解析并构建索引'"
                  permission="review:build-index"
                  theme="primary"
                  :loading="isBuilding(document.id)"
                  :disabled="!canRunBuild(document)"
                  @click="runBuild(document)"
                >
                  <PlayCircleIcon />
                </TableActionButton>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      </t-card>
    </div>
  </PageContainer>
</template>

<style scoped>
.review-page {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
}

.review-page :deep(.t-tabs) {
  flex: 0 0 auto;
}

.review-card {
  flex: 1;
  margin-top: 16px;
}

.filter-bar {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.status-stack {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-status-text {
  color: #6b7280;
  font-size: 12px;
  line-height: 1.4;
}

.error-cell {
  max-width: 240px;
  color: #dc2626;
  white-space: normal;
}
</style>
