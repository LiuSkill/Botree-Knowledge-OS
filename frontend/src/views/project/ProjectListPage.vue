<!--
  Project List Page
-->
<script setup lang="ts">
import { AddIcon, ChatBubbleHelpIcon, DeleteIcon, EditIcon, RefreshIcon, SearchIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';

import { createProject, deleteProject, listProjects, updateProject, type ProjectPayload } from '@/api/projects';
import PageContainer from '@/components/PageContainer.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { ROUTE_PATHS } from '@/shared/constants/routes';
import { useAuthStore } from '@/stores/auth';
import type { ProjectInfo, ProjectStatus, SecurityLevel } from '@/types/api';
import { SECURITY_LEVEL_OPTIONS, securityLevelLabel, securityLevelTheme } from '@/utils/securityLevels';
import ProjectFormDrawer from '@/views/project/ProjectFormDrawer.vue';

type ProjectFormMode = 'create' | 'edit';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

const PAGE_SIZE_OPTIONS = [10, 20, 50];
const PROJECT_STATUS_OPTIONS: Array<{ label: ProjectStatus; value: ProjectStatus; theme: 'default' | 'primary' | 'success' | 'warning' }> = [
  { label: '待启动', value: '待启动', theme: 'warning' },
  { label: '进行中', value: '进行中', theme: 'primary' },
  { label: '已完成', value: '已完成', theme: 'success' },
  { label: '已暂停', value: '已暂停', theme: 'default' },
];

const router = useRouter();
const authStore = useAuthStore();
const projects = ref<ProjectInfo[]>([]);
const loading = ref(false);
const saving = ref(false);
const deleting = ref(false);
const projectDrawerVisible = ref(false);
const projectDrawerMode = ref<ProjectFormMode>('create');
const editingProject = ref<ProjectInfo | null>(null);
const deleteDialogVisible = ref(false);
const pendingDeleteProject = ref<ProjectInfo | null>(null);
const currentPage = ref(1);
const pageSize = ref(10);

const filters = reactive({
  keyword: '',
  project_status: '' as ProjectStatus | '',
  security_level: '' as SecurityLevel | '',
});

const canViewProjects = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_VIEW));
const canOpenProjectDetail = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_VIEW));
const canOpenProjectDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_VIEW));
const canAskProjectChat = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_CHAT));
const canEditProject = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_EDIT));
const canDeleteProject = computed(() => authStore.hasActionPermission(PERMISSIONS.PROJECT_DELETE));
const pagedProjects = computed(() => {
  const start = (currentPage.value - 1) * pageSize.value;
  return projects.value.slice(start, start + pageSize.value);
});

const projectColumns = [
  { colKey: 'project_code', title: '项目编号', width: 180, ellipsis: true },
  { colKey: 'project_name', title: '项目名称', minWidth: 240, ellipsis: true },
  { colKey: 'customer_name', title: '客户名称', minWidth: 180, ellipsis: true },
  { colKey: 'owner_name', title: '负责人', width: 110 },
  { colKey: 'project_status', title: '项目状态', width: 110, align: 'center' },
  { colKey: 'security_level', title: '项目密级', width: 110, align: 'center' },
  { colKey: 'document_count', title: '文档数量', width: 110, align: 'center' },
  { colKey: 'operation', title: '操作', width: 150, align: 'center', fixed: 'right' },
];

async function loadProjects(): Promise<void> {
  if (!canViewProjects.value) {
    projects.value = [];
    return;
  }
  loading.value = true;
  try {
    projects.value = await listProjects({
      keyword: filters.keyword.trim() || undefined,
      project_status: filters.project_status || undefined,
      security_level: filters.security_level || undefined,
    });
    currentPage.value = 1;
  } finally {
    loading.value = false;
  }
}

function enterProject(project: ProjectInfo): void {
  if (!canOpenProjectDetail.value) {
    MessagePlugin.warning('无权限访问项目详情');
    return;
  }
  router.push(`/projects/${project.id}`);
}

function openProjectDocuments(project: ProjectInfo): void {
  if (!canOpenProjectDocuments.value) {
    MessagePlugin.warning('无权限访问项目资料管理');
    return;
  }
  router.push(`/projects/${project.id}/documents`);
}

function openProjectChat(project: ProjectInfo): void {
  if (!canAskProjectChat.value) {
    MessagePlugin.warning('无权限使用项目问答');
    return;
  }
  router.push({ path: ROUTE_PATHS.aiProjectChat, query: { projectId: String(project.id) } });
}

function openCreateDialog(): void {
  projectDrawerMode.value = 'create';
  editingProject.value = null;
  projectDrawerVisible.value = true;
}

function openEditDialog(project: ProjectInfo): void {
  if (!canEditProject.value) {
    MessagePlugin.warning('无权限编辑项目');
    return;
  }
  projectDrawerMode.value = 'edit';
  editingProject.value = project;
  projectDrawerVisible.value = true;
}

async function handleSubmit(payload: ProjectPayload): Promise<void> {
  saving.value = true;
  try {
    if (projectDrawerMode.value === 'edit' && editingProject.value) {
      await updateProject(editingProject.value.id, payload);
      MessagePlugin.success('项目已更新');
    } else {
      await createProject(payload);
      MessagePlugin.success('项目已创建，项目知识库已自动生成');
    }
    projectDrawerVisible.value = false;
    editingProject.value = null;
    await loadProjects();
  } finally {
    saving.value = false;
  }
}

function openDeleteDialog(project: ProjectInfo): void {
  if (!canDeleteProject.value) {
    MessagePlugin.warning('无权限删除项目');
    return;
  }
  pendingDeleteProject.value = project;
  deleteDialogVisible.value = true;
}

async function confirmDeleteProject(): Promise<void> {
  if (!pendingDeleteProject.value) return;
  deleting.value = true;
  try {
    await deleteProject(pendingDeleteProject.value.id);
    MessagePlugin.success('项目已删除');
    deleteDialogVisible.value = false;
    pendingDeleteProject.value = null;
    await loadProjects();
  } finally {
    deleting.value = false;
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
  return PROJECT_STATUS_OPTIONS.find((item) => item.value === normalizeProjectStatus(status))?.theme || 'default';
}

function projectTitle(project: ProjectInfo): string {
  return project.project_name || project.name;
}

function projectCode(project: ProjectInfo): string {
  return project.project_code || project.code;
}

function handleSearch(): void {
  currentPage.value = 1;
  void loadProjects();
}

function handlePaginationChange(pageInfo: PaginationInfo): void {
  currentPage.value = pageInfo.current;
  pageSize.value = pageInfo.pageSize;
}

function resetFilters(): void {
  filters.keyword = '';
  filters.project_status = '';
  filters.security_level = '';
  void loadProjects();
}

onMounted(loadProjects);
</script>

<template>
  <PageContainer title="项目中心" subtitle="项目目录、项目成员&项目信息的结构网格管理">
    <div v-if="!canViewProjects" class="project-page data-scroll">
      <t-empty description="无权限访问项目列表" />
    </div>

    <div v-else class="system-card scroll-card">
      <t-form class="system-filter-form" layout="inline" label-align="left" label-width="auto">
        <t-form-item label="关键字">
          <t-input
            v-model="filters.keyword"
            class="filter-input project-keyword-input"
            clearable
            placeholder="搜索项目名称、编号、客户"
            @enter="handleSearch"
          >
            <template #prefix-icon><SearchIcon /></template>
          </t-input>
        </t-form-item>
        <t-form-item label="项目状态">
          <t-select v-model="filters.project_status" class="filter-select" clearable placeholder="全部状态" @change="handleSearch">
            <t-option v-for="item in PROJECT_STATUS_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
          </t-select>
        </t-form-item>
        <t-form-item label="项目密级">
          <t-select v-model="filters.security_level" class="filter-select" clearable placeholder="全部密级" @change="handleSearch">
            <t-option v-for="item in SECURITY_LEVEL_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
          </t-select>
        </t-form-item>
        <t-form-item>
          <t-space>
            <t-button theme="primary" :loading="loading" @click="handleSearch">查询</t-button>
            <t-button @click="resetFilters">重置</t-button>
          </t-space>
        </t-form-item>
      </t-form>

      <div class="system-section-head">
        <div class="system-section-title">
          <h2>项目列表</h2>
          <span>共 {{ projects.length }} 条数据</span>
        </div>
        <t-space>
          <t-button theme="default" variant="outline" :loading="loading" @click="loadProjects">
            <template #icon><RefreshIcon /></template>
            刷新
          </t-button>
          <t-button v-permission="PERMISSIONS.PROJECT_CREATE" theme="primary" @click="openCreateDialog">
            <template #icon><AddIcon /></template>
            新建项目
          </t-button>
        </t-space>
      </div>

      <div class="table-scroll">
        <t-table
          row-key="id"
          bordered
          table-layout="fixed"
          :data="pagedProjects"
          :columns="projectColumns"
          :loading="loading"
          empty="暂无可访问项目"
        >
          <template #project_code="{ row }">
            <span class="mono">{{ projectCode(row) || '-' }}</span>
          </template>
          <template #project_name="{ row }">
            <t-link theme="primary" :disabled="!canOpenProjectDetail" @click="enterProject(row)">
              {{ projectTitle(row) || '-' }}
            </t-link>
          </template>
          <template #customer_name="{ row }">
            {{ row.customer_name || row.client || '-' }}
          </template>
          <template #owner_name="{ row }">
            {{ row.owner_name || row.manager || '-' }}
          </template>
          <template #project_status="{ row }">
            <t-tag size="small" variant="light" :theme="projectStatusTheme(row.project_status || row.status)">
              {{ normalizeProjectStatus(row.project_status || row.status) }}
            </t-tag>
          </template>
          <template #security_level="{ row }">
            <t-tag size="small" variant="light" :theme="securityLevelTheme(row.security_level)">
              {{ securityLevelLabel(row.security_level) }}
            </t-tag>
          </template>
          <template #document_count="{ row }">
            <button type="button" class="document-count-link" @click="openProjectDocuments(row)">
              {{ row.document_count }}
            </button>
          </template>
          <template #operation="{ row }">
            <div v-if="canAskProjectChat || canEditProject || canDeleteProject" class="table-action-group">
              <t-tooltip v-if="canAskProjectChat" content="项目问答" placement="top">
                <t-button
                  aria-label="项目问答"
                  class="table-action-button"
                  size="small"
                  variant="text"
                  theme="primary"
                  shape="square"
                  @click="openProjectChat(row)"
                >
                  <template #icon><ChatBubbleHelpIcon /></template>
                </t-button>
              </t-tooltip>
              <t-tooltip v-if="canEditProject" content="编辑" placement="top">
                <t-button
                  aria-label="编辑"
                  class="table-action-button"
                  size="small"
                  variant="text"
                  theme="primary"
                  shape="square"
                  @click="openEditDialog(row)"
                >
                  <template #icon><EditIcon /></template>
                </t-button>
              </t-tooltip>
              <t-tooltip v-if="canDeleteProject" content="删除" placement="top">
                <t-button
                  aria-label="删除"
                  class="table-action-button"
                  size="small"
                  variant="text"
                  theme="danger"
                  shape="square"
                  @click="openDeleteDialog(row)"
                >
                  <template #icon><DeleteIcon /></template>
                </t-button>
              </t-tooltip>
            </div>
            <span v-else class="muted">-</span>
          </template>
        </t-table>
      </div>

      <div class="system-pagination">
        <t-pagination
          :current="currentPage"
          :page-size="pageSize"
          :total="projects.length"
          :page-size-options="PAGE_SIZE_OPTIONS"
          show-jumper
          @change="handlePaginationChange"
        />
      </div>
    </div>

    <ProjectFormDrawer
      v-model:visible="projectDrawerVisible"
      :mode="projectDrawerMode"
      :project="editingProject"
      :saving="saving"
      :show-progress="projectDrawerMode === 'edit'"
      @submit="handleSubmit"
    />

    <t-dialog
      v-model:visible="deleteDialogVisible"
      header="删除确认"
      width="520px"
      theme="warning"
      :confirm-loading="deleting"
      confirm-btn="确认删除"
      cancel-btn="取消"
      @confirm="confirmDeleteProject"
    >
      <div v-if="pendingDeleteProject" class="delete-confirm">
        <div class="delete-warning">确定要删除项目「{{ projectTitle(pendingDeleteProject) }}」吗？</div>
        <div class="delete-impact">
          <div>项目：将从项目中心默认列表移除。</div>
          <div>资料：项目下资料访问会随项目删除状态受限。</div>
          <div>RAG 索引：不会修改索引协议，检索侧按项目删除与权限规则过滤。</div>
          <div>历史版本：不在前端删除历史版本数据，保留后端审计与回溯策略。</div>
        </div>
      </div>
    </t-dialog>
  </PageContainer>
</template>

<style scoped>
.project-page {
  display: flex;
  flex: 1 1 0;
  min-height: 0;
  flex-direction: column;
  justify-content: center;
  background: #fff;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
}

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

.filter-input {
  width: 280px;
}

.project-keyword-input {
  width: 330px;
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
  min-width: 1040px;
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

.document-count-link {
  border: 0;
  background: transparent;
  color: #0052d9;
  cursor: pointer;
  font: inherit;
  font-weight: 600;
  line-height: 1;
  padding: 0;
}

.document-count-link:hover {
  text-decoration: underline;
}

.table-action-group {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
}

.table-action-button :deep(.t-icon) {
  width: 18px;
  height: 18px;
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

.delete-confirm {
  display: grid;
  gap: 14px;
}

.delete-warning {
  color: #0f172a;
  font-size: 15px;
  font-weight: 700;
}

.delete-impact {
  display: grid;
  gap: 8px;
  border-radius: 6px;
  background: #fff7ed;
  color: #475569;
  font-size: 13px;
  line-height: 1.6;
  padding: 12px 14px;
}

@media (max-width: 1180px) {
  .project-keyword-input {
    width: 260px;
  }
}

@media (max-width: 820px) {
  .system-section-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .project-keyword-input,
  .filter-input,
  .filter-select {
    width: 100%;
  }

  .system-pagination {
    align-items: flex-start;
    flex-direction: column;
  }
}
</style>
