<!--
  Enterprise Knowledge Center Page

  负责：
  1. 展示企业知识分类树和企业资料列表
  2. 支持动态分类配置、分类筛选和文件类型筛选
  3. 上传资料时强制选择分类，资料默认进入草稿审核流程
-->
<script setup lang="ts">
import { AddIcon, AssignmentCheckedIcon, ChevronDownSIcon, ChevronRightSIcon, DeleteIcon, EditIcon, SearchIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRouter } from 'vue-router';

import { submitDocumentReview } from '@/api/documents';
import { createKnowledgeCategory, deleteKnowledgeCategory, listKnowledgeCategories, updateKnowledgeCategory } from '@/api/knowledgeCategories';
import { listKnowledgeBaseDocuments, listKnowledgeBases, uploadKnowledgeDocument } from '@/api/knowledgeBases';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import { useAuthStore } from '@/stores/auth';
import type { DocumentInfo, KnowledgeBaseInfo, KnowledgeCategory, SecurityLevel } from '@/types/api';
import { buildCategoryOptions, collectCategoryIds, findCategory } from '@/utils/categories';
import { formatDateTime, formatFileSize } from '@/utils/format';
import { SECURITY_LEVEL_OPTIONS, securityLevelLabel, securityLevelTheme } from '@/utils/securityLevels';

type FileTypeFilter = 'all' | 'pdf' | 'word' | 'excel';
type CategoryDialogMode = 'create' | 'edit';

interface CategoryRow {
  category: KnowledgeCategory;
  level: number;
}

const PAGE_SIZE = 6;
const SUBMITTABLE_REVIEW_STATUSES = new Set(['draft', 'rejected']);

const router = useRouter();
const authStore = useAuthStore();
const loading = ref(false);
const uploading = ref(false);
const searchKeyword = ref('');
const activePage = ref(1);
const activeFileType = ref<FileTypeFilter>('all');
const activeCategoryId = ref<number | null>(null);
const expandedCategoryIds = ref<number[]>([]);
const enterpriseBases = ref<KnowledgeBaseInfo[]>([]);
const enterpriseDocuments = ref<DocumentInfo[]>([]);
const categories = ref<KnowledgeCategory[]>([]);
const uploadDialogVisible = ref(false);
const selectedUploadFile = ref<File | null>(null);
const categoryDialogVisible = ref(false);
const categoryDialogMode = ref<CategoryDialogMode>('create');
const editingCategoryId = ref<number | null>(null);

const uploadForm = reactive({
  category_id: null as number | null,
  security_level: 'internal' as SecurityLevel,
});

const categoryForm = reactive({
  parent_id: null as number | null,
  name: '',
  code: '',
  description: '',
  sort_order: 0,
  enabled: true,
});

const fileTypeFilters: Array<{ label: string; value: FileTypeFilter }> = [
  { label: '全部', value: 'all' },
  { label: 'PDF', value: 'pdf' },
  { label: 'Word', value: 'word' },
  { label: 'Excel', value: 'excel' },
];

const uploadTargetBase = computed(() => enterpriseBases.value[0] || null);
const canEditCategories = computed(() => authStore.hasActionPermission('knowledge:edit'));
const canDeleteCategories = computed(() => authStore.hasActionPermission('knowledge:delete'));

const categoryOptions = computed(() => buildCategoryOptions(categories.value));

const visibleCategoryRows = computed<CategoryRow[]>(() => {
  /**
   * 根据展开状态生成左侧可见分类行。
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

const activeCategoryName = computed(() => {
  /**
   * 获取当前筛选分类名称。
   */
  if (!activeCategoryId.value) return '全部知识';
  return findCategory(categories.value, activeCategoryId.value)?.name || '全部知识';
});

const filteredDocuments = computed(() => {
  /**
   * 按分类、文件类型和搜索关键字过滤企业文档。
   */
  const keyword = normalizeText(searchKeyword.value);
  const activeCategory = findCategory(categories.value, activeCategoryId.value);
  const activeCategoryIds = collectCategoryIds(activeCategory);
  return enterpriseDocuments.value.filter((document) => {
    const matchedCategory = !activeCategoryIds.length || activeCategoryIds.includes(Number(document.category_id));
    const matchedFileType = activeFileType.value === 'all' || getDocumentFileType(document) === activeFileType.value;
    const matchedKeyword = !keyword || normalizeText(document.file_name).includes(keyword);
    return matchedCategory && matchedFileType && matchedKeyword;
  });
});

const totalPages = computed(() => Math.max(1, Math.ceil(filteredDocuments.value.length / PAGE_SIZE)));

const pagedDocuments = computed(() => {
  /**
   * 根据当前页码截取可见文档。
   */
  const startIndex = (activePage.value - 1) * PAGE_SIZE;
  return filteredDocuments.value.slice(startIndex, startIndex + PAGE_SIZE);
});

watch([activeCategoryId, activeFileType, searchKeyword], () => {
  /**
   * 筛选条件变化时回到第一页。
   */
  activePage.value = 1;
});

async function loadEnterpriseKnowledge(): Promise<void> {
  /**
   * 加载企业知识库、企业分类和企业资料。
   */
  loading.value = true;
  try {
    const [baseCategories, bases] = await Promise.all([listKnowledgeCategories({ scope_type: 'base' }), listKnowledgeBases({ type: 'base' })]);
    categories.value = baseCategories;
    expandedCategoryIds.value = collectInitialExpandedIds(baseCategories);
    enterpriseBases.value = bases;
    const documentGroups = await Promise.all(enterpriseBases.value.map((base) => listKnowledgeBaseDocuments(base.id)));
    enterpriseDocuments.value = documentGroups
      .flat()
      .filter((document) => document.knowledge_type === 'base')
      .sort((left, right) => Date.parse(right.created_at) - Date.parse(left.created_at));
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '知识文档加载失败');
  } finally {
    loading.value = false;
  }
}

function collectInitialExpandedIds(items: KnowledgeCategory[]): number[] {
  /**
   * 默认展开根分类，便于进入页面后直接看到二级分类。
   */
  return items.map((item) => item.id);
}

function normalizeText(value: string): string {
  /**
   * 统一搜索匹配口径。
   */
  return value.trim().toLowerCase();
}

function selectCategory(categoryId: number | null): void {
  /**
   * 切换左侧分类筛选。
   */
  activeCategoryId.value = categoryId;
}

function toggleCategory(categoryId: number): void {
  /**
   * 展开或收起分类。
   */
  expandedCategoryIds.value = expandedCategoryIds.value.includes(categoryId)
    ? expandedCategoryIds.value.filter((id) => id !== categoryId)
    : [...expandedCategoryIds.value, categoryId];
}

function isCategoryExpanded(categoryId: number): boolean {
  /**
   * 判断分类是否展开。
   */
  return expandedCategoryIds.value.includes(categoryId);
}

function getDocumentFileType(document: DocumentInfo): FileTypeFilter {
  /**
   * 将文件扩展名归一为类型页签。
   */
  const fileMark = normalizeText(`${document.file_type} ${document.file_name}`);
  if (fileMark.includes('pdf')) return 'pdf';
  if (fileMark.includes('doc') || fileMark.includes('word')) return 'word';
  if (fileMark.includes('xls') || fileMark.includes('xlsx') || fileMark.includes('csv') || fileMark.includes('excel')) return 'excel';
  return 'all';
}

function getFileTypeLabel(document: DocumentInfo): string {
  /**
   * 展示用户易读的文件类型。
   */
  const type = getDocumentFileType(document);
  if (type === 'pdf') return 'PDF';
  if (type === 'word') return 'Word';
  if (type === 'excel') return 'Excel';
  return document.file_type?.toUpperCase() || '未知';
}

function openUploadDialog(): void {
  /**
   * 打开上传弹窗。
   */
  if (!uploadTargetBase.value) {
    MessagePlugin.warning('未找到企业基础知识库，请先完成基础知识库初始化');
    return;
  }
  if (!categoryOptions.value.length) {
    MessagePlugin.warning('请先配置企业知识分类');
    return;
  }
  uploadForm.category_id = activeCategoryId.value || categoryOptions.value.find((item) => !item.disabled)?.value || null;
  uploadForm.security_level = 'internal';
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
   * 上传新的企业知识文档，后端会写入草稿状态并创建首个版本 v1。
   */
  if (!selectedUploadFile.value) {
    MessagePlugin.warning('请选择需要上传的文档');
    return;
  }
  if (!uploadForm.category_id || !uploadTargetBase.value) {
    MessagePlugin.warning('请选择知识分类');
    return;
  }

  uploading.value = true;
  try {
    await uploadKnowledgeDocument(uploadTargetBase.value.id, selectedUploadFile.value, uploadForm.category_id, uploadForm.security_level);
    MessagePlugin.success('上传成功，文档已进入草稿状态');
    uploadDialogVisible.value = false;
    await loadEnterpriseKnowledge();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '上传失败');
  } finally {
    uploading.value = false;
  }
}

async function submitReview(document: DocumentInfo): Promise<void> {
  /**
   * 提交文档审核。
   */
  await submitDocumentReview(document.id);
  MessagePlugin.success('已提交审核');
  await loadEnterpriseKnowledge();
}

function canSubmitReview(document: DocumentInfo): boolean {
  /**
   * 判断文档是否允许提交审核。
   */
  return SUBMITTABLE_REVIEW_STATUSES.has(document.review_status);
}

function openCreateCategoryDialog(): void {
  /**
   * 打开新增分类弹窗。
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
   * 打开编辑分类弹窗。
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
   * 保存分类配置。
   */
  if (!categoryForm.name.trim()) {
    MessagePlugin.warning('请输入分类名称');
    return;
  }
  const code = categoryForm.code.trim() || `base-${Date.now()}`;
  if (categoryDialogMode.value === 'create') {
    await createKnowledgeCategory({
      scope_type: 'base',
      project_id: null,
      parent_id: categoryForm.parent_id,
      name: categoryForm.name,
      code,
      description: categoryForm.description,
      sort_order: categoryForm.sort_order,
      enabled: categoryForm.enabled,
    });
  } else if (editingCategoryId.value) {
    await updateKnowledgeCategory(editingCategoryId.value, {
      parent_id: categoryForm.parent_id,
      name: categoryForm.name,
      code,
      description: categoryForm.description,
      sort_order: categoryForm.sort_order,
      enabled: categoryForm.enabled,
    });
  }
  MessagePlugin.success('分类配置已保存');
  categoryDialogVisible.value = false;
  await loadEnterpriseKnowledge();
}

async function removeActiveCategory(): Promise<void> {
  /**
   * 删除当前选中的分类。
   */
  if (!activeCategoryId.value) {
    MessagePlugin.warning('请先选择分类');
    return;
  }
  await deleteKnowledgeCategory(activeCategoryId.value);
  MessagePlugin.success('分类已删除');
  activeCategoryId.value = null;
  await loadEnterpriseKnowledge();
}

function changePage(nextPage: number): void {
  /**
   * 控制分页边界。
   */
  activePage.value = Math.min(Math.max(nextPage, 1), totalPages.value);
}

onMounted(loadEnterpriseKnowledge);
</script>

<template>
  <div class="knowledge-center-shell">
    <aside class="knowledge-category-panel">
      <div class="category-title">
        <span>知识分类</span>
        <t-button v-permission="'knowledge:create'" class="category-create-button" size="small" variant="text" @click="openCreateCategoryDialog">
          <template #icon><AddIcon /></template>
          新增
        </t-button>
      </div>
      <div class="category-list">
        <t-button class="category-row" :class="{ active: activeCategoryId === null }" block variant="text" @click="selectCategory(null)">
          <span>全部知识</span>
          <span class="category-count">{{ enterpriseDocuments.length }}</span>
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
            <span
              v-if="row.category.children?.length"
              class="expand-button"
              @click.stop="toggleCategory(row.category.id)"
            >
              <ChevronDownSIcon v-if="isCategoryExpanded(row.category.id)" />
              <ChevronRightSIcon v-else />
            </span>
            <span v-else class="expand-placeholder"></span>
            {{ row.category.name }}
          </span>
          <span class="category-count">{{ row.category.total_document_count }}</span>
        </t-button>
      </div>

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
    </aside>

    <section class="knowledge-document-panel">
      <header class="document-header">
        <div class="document-title-area">
          <h1>知识文档</h1>
          <div class="result-summary">{{ filteredDocuments.length }} 条结果 · {{ activeCategoryName }}</div>
        </div>

        <div class="file-type-tabs" role="tablist" aria-label="文件类型筛选">
          <t-button
            v-for="item in fileTypeFilters"
            :key="item.value"
            class="file-type-tab"
            :class="{ active: activeFileType === item.value }"
            variant="text"
            @click="activeFileType = item.value"
          >
            {{ item.label }}
          </t-button>
        </div>

        <div class="document-actions">
          <label class="search-box">
            <SearchIcon class="search-icon" />
            <input v-model="searchKeyword" type="search" placeholder="搜索文档..." />
          </label>
          <t-button v-permission="'knowledge:upload'" class="upload-button" theme="primary" :loading="uploading" @click="openUploadDialog">
            <template #icon><AddIcon /></template>
            上传文档
          </t-button>
        </div>
      </header>

      <main class="document-body">
        <div v-if="loading" class="empty-document-card">正在加载知识文档...</div>
        <div v-else-if="!pagedDocuments.length" class="empty-document-card">没有找到匹配文档</div>
        <div v-else class="document-table-card">
          <div class="table-scroll">
            <table class="plain-table enterprise-document-table">
            <thead>
              <tr>
                <th>文档名称</th>
                <th>分类</th>
                <th>密级</th>
                <th>版本</th>
                <th>类型</th>
                <th>大小</th>
                <th>审核状态</th>
                <th>构建状态</th>
                <th>更新时间</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="document in pagedDocuments" :key="document.id">
                <td>
                  <t-link theme="primary" @click="router.push(`/documents/${document.id}`)">{{ document.file_name }}</t-link>
                </td>
                <td>{{ document.category_path || document.category_name || '-' }}</td>
                <td>
                  <t-tag size="small" variant="light" :theme="securityLevelTheme(document.security_level)">
                    {{ securityLevelLabel(document.security_level) }}
                  </t-tag>
                </td>
                <td>v{{ document.version_no }}</td>
                <td>{{ getFileTypeLabel(document) }}</td>
                <td>{{ formatFileSize(document.file_size) }}</td>
                <td><StatusTag type="review" :value="document.review_status" /></td>
                <td><StatusTag type="index" :value="document.index_status" /></td>
                <td>{{ formatDateTime(document.updated_at || document.created_at) }}</td>
                <td>
                  <TableActionButton
                    label="提交审核"
                    permission="knowledge:submit-review"
                    :disabled="!canSubmitReview(document)"
                    @click="submitReview(document)"
                  >
                    <AssignmentCheckedIcon />
                  </TableActionButton>
                </td>
              </tr>
            </tbody>
            </table>
          </div>
        </div>

        <footer class="document-pagination">
          <span>共 {{ filteredDocuments.length }} 条记录，每页 {{ PAGE_SIZE }} 条</span>
          <div class="pagination-actions">
            <t-button size="small" variant="outline" :disabled="activePage === 1" @click="changePage(activePage - 1)">上一页</t-button>
            <t-button size="small" class="current-page" theme="primary">{{ activePage }}</t-button>
            <t-button size="small" variant="outline" :disabled="activePage === totalPages" @click="changePage(activePage + 1)">下一页</t-button>
          </div>
        </footer>
      </main>
    </section>

    <t-dialog v-model:visible="uploadDialogVisible" header="上传企业知识文档" width="560px" :confirm-loading="uploading" @confirm="confirmUpload">
      <t-form label-align="top">
        <t-form-item label="首次版本">
          <div class="version-rule">新资料首次上传为 v1；同一资料的新版本请在文档详情中上传，系统自动递增。</div>
        </t-form-item>
        <t-form-item label="知识分类">
          <t-select v-model="uploadForm.category_id" placeholder="请选择知识分类">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
          </t-select>
        </t-form-item>
        <t-form-item label="文档密级">
          <t-select v-model="uploadForm.security_level">
            <t-option v-for="item in SECURITY_LEVEL_OPTIONS" :key="item.value" :value="item.value" :label="item.label" />
          </t-select>
        </t-form-item>
        <t-form-item label="文档文件">
          <input type="file" accept=".txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf" @change="handleFileChange" />
          <div v-if="selectedUploadFile" class="selected-file">{{ selectedUploadFile.name }}</div>
        </t-form-item>
      </t-form>
    </t-dialog>

    <t-dialog
      v-model:visible="categoryDialogVisible"
      :header="categoryDialogMode === 'create' ? '新增知识分类' : '编辑知识分类'"
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
  </div>
</template>

<style scoped>
.knowledge-center-shell {
  display: grid;
  height: 100%;
  min-height: 0;
  grid-template-columns: 256px minmax(0, 1fr);
  background: #f4f7fb;
  overflow: hidden;
}

.knowledge-category-panel {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #e5e7eb;
  background: #fff;
}

.category-title {
  display: flex;
  height: 52px;
  align-items: center;
  justify-content: space-between;
  padding: 0 16px;
  border-bottom: 1px solid #eef2f7;
  color: #111827;
  font-size: 16px;
  font-weight: 700;
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

.category-list {
  overflow-y: auto;
  flex: 1;
  padding: 14px 16px;
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
  border-top: 1px solid #eef2f7;
  background: #fbfdff;
  padding: 12px 16px;
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

.knowledge-document-panel {
  display: flex;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
}

.document-header {
  display: grid;
  flex: 0 0 auto;
  min-height: 68px;
  grid-template-columns: auto 1fr auto;
  align-items: center;
  gap: 20px;
  border-bottom: 1px solid #e5e7eb;
  background: #fff;
  padding: 14px 20px 12px 24px;
}

.document-title-area h1 {
  margin: 0;
  color: #0f172a;
  font-size: 20px;
  font-weight: 700;
}

.result-summary {
  margin-top: 3px;
  color: #64748b;
  font-size: 12px;
}

.file-type-tabs {
  display: flex;
  align-items: center;
  gap: 12px;
}

.file-type-tab {
  height: 32px;
  min-width: 52px;
  border-radius: 7px;
  color: #1f2937;
  font-size: 13px;
  padding: 0 10px;
}

.file-type-tab.active {
  background: #eaf4ff;
  color: #0474d8;
  font-weight: 700;
}

.document-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.search-box {
  position: relative;
  display: flex;
  width: 256px;
  height: 36px;
  align-items: center;
}

.search-icon {
  position: absolute;
  left: 12px;
  color: #94a3b8;
  font-size: 16px;
}

.search-box input {
  width: 100%;
  height: 100%;
  border: 1px solid #d8dee8;
  border-radius: 9px;
  background: #f8fafc;
  color: #1f2937;
  font-size: 13px;
  outline: none;
  padding: 0 12px 0 34px;
}

.upload-button {
  min-width: 112px;
  font-weight: 700;
}

.document-body {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  padding: 24px;
}

.empty-document-card,
.document-table-card {
  flex: 1;
  min-height: 0;
  overflow: hidden;
  border: 1px solid #e8edf4;
  border-radius: 8px;
  background: #fff;
}

.document-table-card .table-scroll {
  height: 100%;
}

.empty-document-card {
  display: grid;
  flex: 1;
  min-height: 102px;
  place-items: center;
  color: #475569;
  font-size: 14px;
}

.enterprise-document-table th,
.enterprise-document-table td {
  padding: 14px 12px;
}

.document-pagination {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  margin-top: 18px;
  color: #475569;
  font-size: 14px;
}

.pagination-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pagination-actions :deep(.t-button) {
  min-width: 36px;
  height: 32px;
  padding: 0 10px;
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
</style>
