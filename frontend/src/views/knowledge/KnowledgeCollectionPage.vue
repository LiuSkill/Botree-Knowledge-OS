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
import { useI18n } from 'vue-i18n';
import { useRoute, useRouter } from 'vue-router';

import { submitDocumentReview } from '@/api/documents';
import { listKnowledgeCategories } from '@/api/knowledgeCategories';
import { getKnowledgeBase, listKnowledgeBaseDocuments, uploadKnowledgeDocument } from '@/api/knowledgeBases';
import PageContainer from '@/components/PageContainer.vue';
import StatusTag from '@/components/StatusTag.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import type { DocumentInfo, KnowledgeBaseInfo, KnowledgeCategory, SecurityLevel } from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { buildCategoryOptions, collectCategoryIds, findCategory, localizedCategoryName, localizedCategoryPath } from '@/utils/categories';
import { formatDateTime, formatFileSize } from '@/utils/format';
import { clampSecurityLevel, securityLevelLabel, securityLevelTheme } from '@/utils/securityLevels';

const SUBMITTABLE_REVIEW_STATUSES = new Set(['draft', 'rejected']);

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const { t } = useI18n();
const loading = ref(false);
const uploading = ref(false);
const knowledgeBase = ref<KnowledgeBaseInfo | null>(null);
const documents = ref<DocumentInfo[]>([]);
const categories = ref<KnowledgeCategory[]>([]);
const selectedUploadFiles = ref<File[]>([]);
const uploadInputRef = ref<HTMLInputElement | null>(null);

const filterForm = reactive({
  category_id: null as number | null,
});

const uploadForm = reactive({
  category_id: null as number | null,
  security_level: clampSecurityLevel('internal', authStore.maxSecurityLevel),
});

const categoryOptions = computed(() =>
  buildCategoryOptions(categories.value, 0, (name) => localizedCategoryName(name, t)),
);

function categoryDisplayPath(path?: string | null): string {
  return path ? localizedCategoryPath(path, t) : '-';
}
const canViewDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.KNOWLEDGE_VIEW));
const canUploadDocuments = computed(() => authStore.hasActionPermission(PERMISSIONS.KNOWLEDGE_UPLOAD));
const canSubmitDocumentReview = computed(() => authStore.hasActionPermission(PERMISSIONS.KNOWLEDGE_SUBMIT_REVIEW));

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
      MessagePlugin.warning(t('knowledge.message.projectBaseRedirect'));
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
  selectedUploadFiles.value = Array.from(input.files || []);
}

async function handleUpload(): Promise<void> {
  /**
   * 上传企业资料，后端会写入草稿状态和系统递增版本号。
   */
  if (!canUploadDocuments.value) {
    MessagePlugin.warning(t('knowledge.message.uploadKnowledgeForbidden'));
    return;
  }
  if (!selectedUploadFiles.value.length) {
    MessagePlugin.warning(t('knowledge.message.materialRequired'));
    return;
  }
  if (!uploadForm.category_id) {
    MessagePlugin.warning(t('knowledge.message.enterpriseCategoryRequired'));
    return;
  }

  uploading.value = true;
  try {
    for (const file of selectedUploadFiles.value) {
      await uploadKnowledgeDocument(currentId(), file, uploadForm.category_id, uploadForm.security_level);
    }
    MessagePlugin.success(t('knowledge.message.uploadBatchMaterialDraftSuccess', { count: selectedUploadFiles.value.length }));
    selectedUploadFiles.value = [];
    if (uploadInputRef.value) uploadInputRef.value.value = '';
    await loadData();
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : t('knowledge.message.uploadFailed'));
  } finally {
    uploading.value = false;
  }
}

async function submitReview(document: DocumentInfo): Promise<void> {
  /**
   * 提交资料审核。
   */
  if (!canSubmitDocumentReview.value) {
    MessagePlugin.warning(t('knowledge.message.submitForbidden'));
    return;
  }
  await submitDocumentReview(document.id);
  MessagePlugin.success(t('knowledge.message.submitted'));
  await loadData();
}

function viewDocument(document: DocumentInfo): void {
  /**
   * 查看知识资料详情，和详情接口使用相同查看权限。
   */
  if (!canViewDocuments.value) {
    MessagePlugin.warning(t('knowledge.message.viewForbidden'));
    return;
  }
  router.push(withBreadcrumbContext(route, `/documents/${document.id}`));
}

function canSubmitReview(document: DocumentInfo): boolean {
  /**
   * 判断资料是否允许提交审核。
   */
  return canSubmitDocumentReview.value && SUBMITTABLE_REVIEW_STATUSES.has(document.review_status);
}

onMounted(loadData);
</script>

<template>
  <PageContainer :title="knowledgeBase?.name || t('knowledge.title.collectionFallback')" :subtitle="t('knowledge.subtitle.collection')">
    <template #actions>
      <t-button variant="outline" @click="router.push('/knowledge')">{{ t('knowledge.action.backToCenter') }}</t-button>
    </template>

    <div class="panel-stack knowledge-detail-stack data-scroll" v-loading="loading">
      <t-card>
        <div class="detail-grid">
          <div class="detail-item">
            <div class="detail-label">{{ t('knowledge.field.knowledgeBaseCode') }}</div>
            <div class="detail-value">{{ knowledgeBase?.code || '-' }}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">{{ t('knowledge.field.knowledgeType') }}</div>
            <div class="detail-value">{{ t('knowledge.value.enterpriseKnowledge') }}</div>
          </div>
          <div class="detail-item">
            <div class="detail-label">{{ t('knowledge.field.chunkCount') }}</div>
            <div class="detail-value">{{ knowledgeBase?.chunk_count || 0 }}</div>
          </div>
        </div>
      </t-card>

      <t-card :title="t('knowledge.section.upload')">
        <t-form label-align="top">
          <div class="upload-grid">
            <t-form-item :label="t('knowledge.field.firstVersion')">
              <div class="version-rule">{{ t('knowledge.upload.firstVersionRule') }}</div>
            </t-form-item>
            <t-form-item :label="t('knowledge.field.enterpriseCategory')" required-mark>
              <t-select v-model="uploadForm.category_id" :placeholder="t('knowledge.upload.enterpriseCategoryPlaceholder')">
                <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
              </t-select>
            </t-form-item>
            <t-form-item :label="t('knowledge.field.documentSecurityLevel')" required-mark>
              <t-select v-model="uploadForm.security_level">
                <t-option v-for="item in authStore.allowedSecurityLevelOptions" :key="item.value" :value="item.value" :label="item.label" />
              </t-select>
            </t-form-item>
            <t-form-item :label="t('knowledge.field.materialFile')" required-mark>
              <input ref="uploadInputRef" type="file" multiple accept=".txt,.md,.csv,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.odt,.odp,.ods,.rtf" @change="handleFileChange" />
              <div v-if="selectedUploadFiles.length" class="selected-file-list">
                <div v-for="file in selectedUploadFiles" :key="`${file.name}-${file.size}-${file.lastModified}`" class="selected-file">{{ file.name }}</div>
              </div>
            </t-form-item>
          </div>
          <t-button v-permission="PERMISSIONS.KNOWLEDGE_UPLOAD" theme="primary" :loading="uploading" @click="handleUpload">{{ t('knowledge.action.uploadMaterial') }}</t-button>
        </t-form>
      </t-card>

      <t-card :title="t('knowledge.section.list')">
        <template #actions>
          <t-select v-model="filterForm.category_id" clearable :placeholder="t('knowledge.filter.categoryPlaceholder')" style="width: 220px">
            <t-option v-for="item in categoryOptions" :key="item.value" :value="item.value" :label="item.label" :disabled="item.disabled" />
          </t-select>
        </template>

        <t-empty v-if="!filteredDocuments.length" :description="t('knowledge.empty.noMaterials')" />
        <div v-else class="table-scroll">
          <table class="plain-table">
          <thead>
            <tr>
              <th>{{ t('knowledge.field.fileName') }}</th>
              <th>{{ t('knowledge.field.category') }}</th>
              <th>{{ t('knowledge.field.securityLevel') }}</th>
              <th>{{ t('knowledge.field.version') }}</th>
              <th>{{ t('knowledge.field.size') }}</th>
              <th>{{ t('knowledge.field.reviewStatus') }}</th>
              <th>{{ t('knowledge.field.parseStatus') }}</th>
              <th>{{ t('knowledge.field.indexStatus') }}</th>
              <th>{{ t('knowledge.field.updatedAt') }}</th>
              <th>{{ t('common.field.operation') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="doc in filteredDocuments" :key="doc.id">
              <td><t-link v-permission="PERMISSIONS.KNOWLEDGE_VIEW" theme="primary" @click="viewDocument(doc)">{{ doc.file_name }}</t-link></td>
              <td>{{ categoryDisplayPath(doc.category_path || doc.category_name) }}</td>
              <td>
                <t-tag size="small" variant="light" :theme="securityLevelTheme(doc.security_level)">
                  {{ securityLevelLabel(doc.security_level) }}
                </t-tag>
              </td>
              <td>v{{ doc.version_no }}</td>
              <td>{{ formatFileSize(doc.file_size) }}</td>
              <td><StatusTag type="review" :value="doc.review_status" /></td>
              <td><StatusTag type="generic" :value="doc.parse_status || 'unparsed'" /></td>
              <td><StatusTag type="index" :value="doc.index_status" /></td>
              <td>{{ formatDateTime(doc.updated_at) }}</td>
              <td>
                <TableActionButton
                  :label="t('knowledge.action.submitReview')"
                  :permission="PERMISSIONS.KNOWLEDGE_SUBMIT_REVIEW"
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
  grid-template-columns: 180px minmax(220px, 320px) 180px minmax(260px, 1fr);
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
