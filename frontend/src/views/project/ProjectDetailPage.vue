<!--
  Project Detail Page

  负责：
  1. 展示项目基础信息、项目资料分类树和项目成员。
  2. 项目资料按项目内分类隔离，上传时强制选择分类。
  3. 项目资料页只负责提交审核，解析与索引统一进入审核中心构建流程。
-->
<script setup lang="ts">
import { AddIcon, AssignmentCheckedIcon, ChevronDownSIcon, ChevronRightSIcon, DeleteIcon, EditIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { listDocuments, submitDocumentReview } from '@/api/documents';
import { createKnowledgeCategory, deleteKnowledgeCategory, listKnowledgeCategories, updateKnowledgeCategory } from '@/api/knowledgeCategories';
import { uploadKnowledgeDocument } from '@/api/knowledgeBases';
import { getProject, listProjectMembers } from '@/api/projects';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import { useAuthStore } from '@/stores/auth';
import type { DocumentInfo, KnowledgeCategory, ProjectInfo } from '@/types/api';
import { buildCategoryOptions, collectCategoryIds, findCategory } from '@/utils/categories';
import { formatDateTime, formatFileSize } from '@/utils/format';

type CategoryDialogMode = 'create' | 'edit';

interface CategoryRow {
  category: KnowledgeCategory;
  level: number;
}

const SUBMITTABLE_REVIEW_STATUSES = new Set(['draft', 'rejected']);

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const project = ref<ProjectInfo | null>(null);
const documents = ref<DocumentInfo[]>([]);
const members = ref<Array<Record<string, unknown>>>([]);
const categories = ref<KnowledgeCategory[]>([]);
const activeCategoryId = ref<number | null>(null);
const expandedCategoryIds = ref<number[]>([]);
const uploading = ref(false);
const uploadDialogVisible = ref(false);
const selectedUploadFile = ref<File | null>(null);
const categoryDialogVisible = ref(false);
const categoryDialogMode = ref<CategoryDialogMode>('create');
const editingCategoryId = ref<number | null>(null);

const projectId = computed(() => Number(route.params.id));
const categoryOptions = computed(() => buildCategoryOptions(categories.value));
const canEditCategories = computed(() => authStore.hasActionPermission('knowledge:edit'));
const canDeleteCategories = computed(() => authStore.hasActionPermission('knowledge:delete'));

const uploadForm = reactive({
  category_id: null as number | null,
});

const categoryForm = reactive({
  parent_id: null as number | null,
  name: '',
  code: '',
  description: '',
  sort_order: 0,
  enabled: true,
});

const visibleCategoryRows = computed<CategoryRow[]>(() => {
  /**
   * 根据展开状态生成左侧可见分类行，支持无限层级。
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
   * 分类筛选包含当前分类及其所有子分类，保证树形筛选符合用户直觉。
   */
  const activeCategory = findCategory(categories.value, activeCategoryId.value);
  const categoryIds = collectCategoryIds(activeCategory);
  if (!categoryIds.length) return documents.value;
  return documents.value.filter((document) => categoryIds.includes(Number(document.category_id)));
});

async function loadData(): Promise<void> {
  /**
   * 加载项目详情、项目内分类、资料列表和成员列表。
   */
  const [projectInfo, projectCategories, projectDocuments, projectMembers] = await Promise.all([
    getProject(projectId.value),
    listKnowledgeCategories({ scope_type: 'project', project_id: projectId.value }),
    listDocuments({ project_id: projectId.value, knowledge_type: 'project' }),
    listProjectMembers(projectId.value),
  ]);
  project.value = projectInfo;
  categories.value = projectCategories;
  expandedCategoryIds.value = projectCategories.map((category) => category.id);
  documents.value = projectDocuments.sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at));
  members.value = projectMembers;
}

function selectCategory(categoryId: number | null): void {
  /**
   * 切换项目资料分类筛选。
   */
  activeCategoryId.value = categoryId;
}

function toggleCategory(categoryId: number): void {
  /**
   * 展开或收起一个分类节点。
   */
  expandedCategoryIds.value = expandedCategoryIds.value.includes(categoryId)
    ? expandedCategoryIds.value.filter((id) => id !== categoryId)
    : [...expandedCategoryIds.value, categoryId];
}

function isCategoryExpanded(categoryId: number): boolean {
  /**
   * 判断分类节点是否处于展开状态。
   */
  return expandedCategoryIds.value.includes(categoryId);
}

function openUploadDialog(): void {
  /**
   * 打开上传弹窗，并预填当前选中的项目分类。
   */
  if (!project.value?.knowledge_base_id) {
    MessagePlugin.warning('项目知识库不存在');
    return;
  }
  if (!categoryOptions.value.length) {
    MessagePlugin.warning('请先配置项目资料分类');
    return;
  }
  uploadForm.category_id = activeCategoryId.value || categoryOptions.value.find((item) => !item.disabled)?.value || null;
  selectedUploadFile.value = null;
  uploadDialogVisible.value = true;
}

function handleFileChange(event: Event): void {
  /**
   * 读取上传弹窗中的本地文件。
   */
  const input = event.target as HTMLInputElement;
  selectedUploadFile.value = input.files?.[0] || null;
}

async function confirmUpload(): Promise<void> {
  /**
   * 上传项目资料，后端会校验分类必须属于当前项目。
   */
  if (!project.value?.knowledge_base_id) {
    MessagePlugin.warning('项目知识库不存在');
    return;
  }
  if (!selectedUploadFile.value) {
    MessagePlugin.warning('请选择需要上传的资料');
    return;
  }
  if (!uploadForm.category_id) {
    MessagePlugin.warning('请选择项目资料分类');
    return;
  }

  uploading.value = true;
  try {
    await uploadKnowledgeDocument(project.value.knowledge_base_id, selectedUploadFile.value, uploadForm.category_id);
    MessagePlugin.success('项目资料上传成功，已进入草稿状态');
    uploadDialogVisible.value = false;
    await loadData();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '项目资料上传失败');
  } finally {
    uploading.value = false;
  }
}

async function submitReview(document: DocumentInfo): Promise<void> {
  /**
   * 项目资料提交审核，解析与索引构建由审核中心统一触发。
   */
  await submitDocumentReview(document.id);
  MessagePlugin.success('已提交审核');
  await loadData();
}

function canSubmitReview(document: DocumentInfo): boolean {
  /**
   * 仅草稿和驳回状态允许重新提交审核。
   */
  return SUBMITTABLE_REVIEW_STATUSES.has(document.review_status);
}

function openCreateCategoryDialog(): void {
  /**
   * 新建项目内分类，默认挂在当前选中分类下。
   */
  categoryDialogMode.value = 'create';
  editingCategoryId.value = null;
  categoryForm.parent_id = activeCategoryId.value;
  categoryForm.name = '';
  categoryForm.code = '';
  categoryForm.description = '';
  categoryForm.sort_order = 0;
  categoryForm.enabled = true;
  categoryDialogVisible.value = true;
}

function openEditCategoryDialog(): void {
  /**
   * 编辑当前选中的项目分类。
   */
  const category = findCategory(categories.value, activeCategoryId.value);
  if (!category) {
    MessagePlugin.warning('请先选择需要编辑的分类');
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
  categoryDialogVisible.value = true;
}

async function confirmCategoryDialog(): Promise<void> {
  /**
   * 保存项目资料分类配置，后端会按项目隔离校验父级和编码。
   */
  if (!categoryForm.name.trim()) {
    MessagePlugin.warning('请输入分类名称');
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
  };

  if (categoryDialogMode.value === 'create') {
    await createKnowledgeCategory({
      scope_type: 'project',
      project_id: projectId.value,
      ...payload,
    });
  } else if (editingCategoryId.value) {
    await updateKnowledgeCategory(editingCategoryId.value, payload);
  }
  MessagePlugin.success('项目资料分类已保存');
  categoryDialogVisible.value = false;
  await loadData();
}

async function removeActiveCategory(): Promise<void> {
  /**
   * 删除当前分类。后端只允许删除无子级、无文档引用的分类。
   */
  if (!activeCategoryId.value) {
    MessagePlugin.warning('请先选择分类');
    return;
  }
  await deleteKnowledgeCategory(activeCategoryId.value);
  MessagePlugin.success('分类已删除');
  activeCategoryId.value = null;
  await loadData();
}

onMounted(loadData);
</script>

<template>
  <PageContainer :title="project?.name || '项目详情'" subtitle="项目资料和分类仅在当前项目内可见、可用">
    <template #actions>
      <t-space>
        <t-button variant="outline" @click="router.push('/projects')">返回项目中心</t-button>
        <t-button v-permission="'knowledge:upload'" theme="primary" :loading="uploading" @click="openUploadDialog">
          <template #icon><AddIcon /></template>
          上传资料
        </t-button>
      </t-space>
    </template>

    <div class="panel-stack project-detail-stack data-scroll">
      <t-card>
        <div class="detail-grid">
          <div class="detail-item">
            <div class="detail-label">项目编码</div>
            <div class="detail-value">{{ project?.code || '-' }}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">项目经理</div>
            <div class="detail-value">{{ project?.manager || '-' }}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">项目进度</div>
            <div class="detail-value">{{ project?.progress || 0 }}%</div>
          </div>
        </div>
      </t-card>

      <div class="project-workspace">
        <t-card class="category-card">
          <template #title>
            <div class="card-title-row">
              <span>项目资料分类</span>
              <t-button v-permission="'knowledge:create'" class="category-create-button" size="small" variant="text" @click="openCreateCategoryDialog">
                <template #icon><AddIcon /></template>
                新增
              </t-button>
            </div>
          </template>

          <t-button class="category-row" :class="{ active: activeCategoryId === null }" block variant="text" @click="selectCategory(null)">
            <span>全部项目资料</span>
            <span class="category-count">{{ documents.length }}</span>
          </t-button>
          <t-button
            v-for="row in visibleCategoryRows"
            :key="row.category.id"
            class="category-row"
            :class="{ active: activeCategoryId === row.category.id, disabled: !row.category.enabled }"
            block
            variant="text"
            :style="{ paddingLeft: `${10 + row.level * 18}px` }"
            @click="selectCategory(row.category.id)"
          >
            <span class="category-name">
              <span v-if="row.category.children?.length" class="expand-button" @click.stop="toggleCategory(row.category.id)">
                <ChevronDownSIcon v-if="isCategoryExpanded(row.category.id)" />
                <ChevronRightSIcon v-else />
              </span>
              <span v-else class="expand-placeholder"></span>
              {{ row.category.name }}
            </span>
            <span class="category-count">{{ row.category.total_document_count }}</span>
          </t-button>

          <div v-if="canEditCategories || canDeleteCategories" class="category-tools">
            <t-button
              v-permission="'knowledge:edit'"
              class="category-tool-button"
              size="small"
              variant="outline"
              :disabled="activeCategoryId === null"
              @click="openEditCategoryDialog"
            >
              <template #icon><EditIcon /></template>
              编辑
            </t-button>
            <t-button
              v-permission="'knowledge:delete'"
              class="category-tool-button danger"
              size="small"
              variant="outline"
              theme="danger"
              :disabled="activeCategoryId === null"
              @click="removeActiveCategory"
            >
              <template #icon><DeleteIcon /></template>
              删除
            </t-button>
          </div>
        </t-card>

        <t-card title="项目资料" class="scroll-card">
          <t-empty v-if="!filteredDocuments.length" description="暂无项目资料" />
          <div v-else class="table-scroll">
            <table class="plain-table">
            <thead>
              <tr>
                <th>文件名</th>
                <th>分类</th>
                <th>版本</th>
                <th>大小</th>
                <th>审核</th>
                <th>构建</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in filteredDocuments" :key="doc.id">
                <td><t-link theme="primary" @click="router.push(`/documents/${doc.id}`)">{{ doc.file_name }}</t-link></td>
                <td>{{ doc.category_path || doc.category_name || '-' }}</td>
                <td>v{{ doc.version_no }}</td>
                <td>{{ formatFileSize(doc.file_size) }}</td>
                <td><StatusTag type="review" :value="doc.review_status" /></td>
                <td><StatusTag type="index" :value="doc.index_status" /></td>
                <td>{{ formatDateTime(doc.updated_at) }}</td>
                <td>
                  <TableActionButton
                    label="提交审核"
                    permission="knowledge:submit-review"
                    :disabled="!canSubmitReview(doc)"
                    @click="submitReview(doc)"
                  >
                    <AssignmentCheckedIcon />
                  </TableActionButton>
                </td>
              </tr>
            </tbody>
            </table>
          </div>
        </t-card>

        <t-card title="项目成员">
          <t-empty v-if="!members.length" description="暂无成员" />
          <div v-for="member in members" :key="String(member.id)" class="member-row">
            <div>
              <div class="member-name">用户 #{{ member.user_id }}</div>
              <div class="muted">权限：{{ member.permission_scope }}</div>
            </div>
            <t-tag size="small" variant="light">{{ member.role }}</t-tag>
          </div>
        </t-card>
      </div>
    </div>

    <t-dialog v-model:visible="uploadDialogVisible" header="上传项目资料" width="560px" :confirm-loading="uploading" @confirm="confirmUpload">
      <t-form label-align="top">
        <t-form-item label="首次版本">
          <div class="version-rule">新资料首次上传为 v1；同一资料的新版本请在文档详情中上传，系统自动递增。</div>
        </t-form-item>
        <t-form-item label="项目资料分类">
          <t-select v-model="uploadForm.category_id" placeholder="请选择项目资料分类">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
          </t-select>
        </t-form-item>
        <t-form-item label="资料文件">
          <input type="file" accept=".txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf" @change="handleFileChange" />
          <div v-if="selectedUploadFile" class="selected-file">{{ selectedUploadFile.name }}</div>
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog
      v-model:visible="categoryDialogVisible"
      :header="categoryDialogMode === 'create' ? '新增项目资料分类' : '编辑项目资料分类'"
      width="560px"
      @confirm="confirmCategoryDialog"
    >
      <t-form :data="categoryForm" label-align="top">
        <t-form-item label="父分类">
          <t-select v-model="categoryForm.parent_id" clearable placeholder="根分类">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.value === editingCategoryId" />
          </t-select>
        </t-form-item>
        <t-form-item label="分类名称"><t-input v-model="categoryForm.name" /></t-form-item>
        <t-form-item label="分类编码"><t-input v-model="categoryForm.code" placeholder="为空时自动生成" /></t-form-item>
        <t-form-item label="排序"><t-input v-model="categoryForm.sort_order" type="number" /></t-form-item>
        <t-form-item label="说明"><t-textarea v-model="categoryForm.description" /></t-form-item>
        <t-form-item label="启用"><t-switch v-model="categoryForm.enabled" /></t-form-item>
      </t-form>
    </t-dialog>
  </PageContainer>
</template>

<style scoped>
.project-detail-stack {
  height: 100%;
}

.project-workspace {
  display: grid;
  grid-template-columns: 260px minmax(0, 1fr) 320px;
  gap: 16px;
}

.category-card :deep(.t-card__body) {
  padding: 12px;
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

@media (max-width: 1180px) {
  .project-workspace {
    grid-template-columns: 240px minmax(0, 1fr);
  }

  .project-workspace > :last-child {
    grid-column: 1 / -1;
  }
}
</style>
