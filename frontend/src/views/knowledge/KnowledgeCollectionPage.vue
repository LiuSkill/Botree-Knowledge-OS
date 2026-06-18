<!--
  Knowledge Collection Page

  负责：
  1. 展示单个企业知识库详情和资料列表。
  2. 上传企业资料时强制选择企业全局分类。
  3. 页面仅提供提交审核入口，解析与索引统一由审核中心触发。
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { AssignmentCheckedIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, reactive, ref } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { submitDocumentReview } from '@/api/documents';
import { listKnowledgeCategories } from '@/api/knowledgeCategories';
import { getKnowledgeBase, listKnowledgeBaseDocuments, uploadKnowledgeDocument } from '@/api/knowledgeBases';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import type { DocumentInfo, KnowledgeBaseInfo, KnowledgeCategory } from '@/types/api';
import { buildCategoryOptions, collectCategoryIds, findCategory } from '@/utils/categories';
import { formatDateTime, formatFileSize } from '@/utils/format';

const SUBMITTABLE_REVIEW_STATUSES = new Set(['draft', 'rejected']);

const route = useRoute();
const router = useRouter();
const loading = ref(false);
const uploading = ref(false);
const knowledgeBase = ref<KnowledgeBaseInfo | null>(null);
const documents = ref<DocumentInfo[]>([]);
const categories = ref<KnowledgeCategory[]>([]);
const selectedUploadFile = ref<File | null>(null);

const filterForm = reactive({
  category_id: null as number | null,
});

const uploadForm = reactive({
  category_id: null as number | null,
});

const categoryOptions = computed(() => buildCategoryOptions(categories.value));

const filteredDocuments = computed(() => {
  /**
   * 按企业分类树筛选当前知识库资料。
   */
  const activeCategory = findCategory(categories.value, filterForm.category_id);
  const categoryIds = collectCategoryIds(activeCategory);
  if (!categoryIds.length) return documents.value;
  return documents.value.filter((document) => categoryIds.includes(Number(document.category_id)));
});

function currentId(): number {
  /**
   * 将路由参数转换为数字 ID。
   */
  return Number(route.params.id);
}

async function loadData(): Promise<void> {
  /**
   * 加载企业知识库详情、企业分类树和资料列表。
   */
  loading.value = true;
  try {
    const [baseInfo, baseCategories] = await Promise.all([
      getKnowledgeBase(currentId()),
      listKnowledgeCategories({ scope_type: 'base' }),
    ]);
    knowledgeBase.value = baseInfo;
    categories.value = baseCategories;

    if (baseInfo.type !== 'base') {
      MessagePlugin.warning('该资料库属于项目资料，请在项目中心管理');
      documents.value = [];
      await router.replace(baseInfo.project_id ? `/projects/${baseInfo.project_id}` : '/projects');
      return;
    }

    documents.value = await listKnowledgeBaseDocuments(currentId());
  } finally {
    loading.value = false;
  }
}

function handleFileChange(event: Event): void {
  /**
   * 读取用户选择的本地资料文件。
   */
  const input = event.target as HTMLInputElement;
  selectedUploadFile.value = input.files?.[0] || null;
}

async function handleUpload(): Promise<void> {
  /**
   * 上传企业资料，后端会写入草稿状态和系统递增版本号。
   */
  if (!selectedUploadFile.value) {
    MessagePlugin.warning('请选择需要上传的资料');
    return;
  }
  if (!uploadForm.category_id) {
    MessagePlugin.warning('请选择企业知识分类');
    return;
  }

  uploading.value = true;
  try {
    await uploadKnowledgeDocument(currentId(), selectedUploadFile.value, uploadForm.category_id);
    MessagePlugin.success('上传成功，资料处于草稿状态');
    selectedUploadFile.value = null;
    await loadData();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '上传失败');
  } finally {
    uploading.value = false;
  }
}

async function submitReview(document: DocumentInfo): Promise<void> {
  /**
   * 提交资料审核。
   */
  await submitDocumentReview(document.id);
  MessagePlugin.success('已提交审核');
  await loadData();
}

function canSubmitReview(document: DocumentInfo): boolean {
  /**
   * 判断资料是否允许提交审核。
   */
  return SUBMITTABLE_REVIEW_STATUSES.has(document.review_status);
}

onMounted(loadData);
</script>

<template>
  <PageContainer :title="knowledgeBase?.name || '知识库详情'" subtitle="企业资料上传、分类筛选和审核提交入口">
    <template #actions>
      <t-button variant="outline" @click="router.push('/knowledge')">返回知识中心</t-button>
    </template>

    <div class="panel-stack knowledge-detail-stack data-scroll" v-loading="loading">
      <t-card>
        <div class="detail-grid">
          <div class="detail-item">
            <div class="detail-label">知识库编码</div>
            <div class="detail-value">{{ knowledgeBase?.code || '-' }}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">知识类型</div>
            <div class="detail-value">企业知识</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">知识分块</div>
            <div class="detail-value">{{ knowledgeBase?.chunk_count || 0 }}</div>
          </div>
        </div>
      </t-card>

      <t-card title="上传资料">
        <t-form label-align="top">
          <div class="upload-grid">
            <t-form-item label="首次版本">
              <div class="version-rule">新资料首次上传为 v1；同一资料的新版本请在文档详情中上传，系统自动递增。</div>
            </t-form-item>
            <t-form-item label="企业知识分类">
              <t-select v-model="uploadForm.category_id" placeholder="请选择分类">
                <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
              </t-select>
            </t-form-item>
            <t-form-item label="资料文件">
              <input type="file" accept=".txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf" @change="handleFileChange" />
              <div v-if="selectedUploadFile" class="selected-file">{{ selectedUploadFile.name }}</div>
            </t-form-item>
          </div>
          <t-button v-permission="'knowledge:upload'" theme="primary" :loading="uploading" @click="handleUpload">上传资料</t-button>
        </t-form>
      </t-card>

      <t-card title="资料列表">
        <template #actions>
          <t-select v-model="filterForm.category_id" clearable placeholder="按分类筛选" style="width: 220px">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
          </t-select>
        </template>

        <t-empty v-if="!filteredDocuments.length" description="暂无资料" />
        <div v-else class="table-scroll">
          <table class="plain-table">
          <thead>
            <tr>
              <th>文件名</th>
              <th>分类</th>
              <th>版本</th>
              <th>大小</th>
              <th>审核状态</th>
              <th>构建状态</th>
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
    </div>
  </PageContainer>
</template>

<style scoped>
.knowledge-detail-stack {
  height: 100%;
}

.upload-grid {
  display: grid;
  grid-template-columns: 180px minmax(220px, 320px) minmax(260px, 1fr);
  gap: 16px;
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
