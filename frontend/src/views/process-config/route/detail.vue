<script setup lang="ts">
import { ArrowLeftIcon, BrowseIcon, EditIcon, RefreshIcon, SaveIcon, TimeIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, reactive, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { getProcessNode, getProcessRoute, listProcessLibraryOptions, listProcessNodes, updateProcessRoute } from '@/api/process-config';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import { previousBreadcrumbTarget } from '@/utils/breadcrumbContext';
import { formatDateTime } from '@/utils/format';
import type { ProcessLibraryOptionItem, ProcessNodeDetail, ProcessNodeItem } from '@/views/process-config/node/types';
import RouteFlowViewer from '@/views/process-config/route/components/RouteFlowViewer.vue';
import RouteFormDialog from '@/views/process-config/route/components/RouteFormDialog.vue';
import RouteNodeDetailPanel from '@/views/process-config/route/components/RouteNodeDetailPanel.vue';
import RouteVersionDialog from '@/views/process-config/route/components/RouteVersionDialog.vue';
import type { ProcessRouteDetail, ProcessRouteNodeDetail, ProcessRoutePayload, RouteEditableNode, RouteFlowNode, RouteNodeOption } from '@/views/process-config/route/types';
import { PROCESS_NODE_TYPE_OPTIONS } from '@/views/process-config/node/types';

type NodeLibraryRecord = ProcessNodeItem;

const permissions = {
  view: PERMISSIONS.PROCESS_CONFIG_ROUTE_VIEW,
  update: PERMISSIONS.PROCESS_CONFIG_ROUTE_UPDATE,
  version: PERMISSIONS.PROCESS_CONFIG_ROUTE_VERSION,
  preview: PERMISSIONS.PROCESS_CONFIG_ROUTE_PREVIEW,
} as const;

const STATS_FETCH_PAGE_SIZE = 100;

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const pageLoading = ref(false);
const saving = ref(false);
const formSaving = ref(false);
const optionsLoading = ref(false);
const nodeLibraryLoading = ref(false);
const selectedNodeLoading = ref(false);
const formVisible = ref(false);
const versionDialogVisible = ref(false);

const detail = ref<ProcessRouteDetail | null>(null);
const editableNodes = ref<RouteEditableNode[]>([]);
const selectedNodeKey = ref<string | null>(null);
const nodeLibraryKeyword = ref('');

const materialOptions = ref<ProcessLibraryOptionItem[]>([]);
const productOptions = ref<ProcessLibraryOptionItem[]>([]);
const outputOptions = ref<ProcessLibraryOptionItem[]>([]);
const consumableOptions = ref<ProcessLibraryOptionItem[]>([]);
const publicServiceOptions = ref<ProcessLibraryOptionItem[]>([]);
const nodeOptions = ref<RouteNodeOption[]>([]);

const nodeDetailCache = reactive<Record<number, ProcessNodeDetail>>({});
let localNodeSeed = 0;

const routeId = computed(() => Number(route.params.id));
const canUpdate = computed(() => authStore.hasActionPermission(permissions.update));
const canManageVersion = computed(() => authStore.hasActionPermission(permissions.version));


const selectedFlowNode = computed<RouteFlowNode | null>(() => {
  if (!selectedNodeKey.value) return null;
  return flowNodes.value.find((item) => item.local_key === selectedNodeKey.value) || null;
});

const selectedNodeDetail = computed<ProcessNodeDetail | null>(() => {
  const nodeId = selectedFlowNode.value?.node_id;
  if (!nodeId) return null;
  return nodeDetailCache[nodeId] || null;
});

const filteredNodeLibrary = computed(() => {
  const keyword = nodeLibraryKeyword.value.trim().toLowerCase();
  if (!keyword) return nodeOptions.value;
  return nodeOptions.value.filter((item) => {
    const content = [item.code, item.name, item.node_type].join(' ').toLowerCase();
    return content.includes(keyword);
  });
});

const flowNodes = computed<RouteFlowNode[]>(() =>
  editableNodes.value
    .map((item, index) => {
      const node = nodeDetailCache[item.node_id || 0];
      const nodeOption = nodeOptions.value.find((option) => option.id === item.node_id);
      const nodeCode = node?.code || nodeOption?.code || `#${item.node_id || '-'}`;
      const nodeName = node?.name || nodeOption?.name || '未命名节点';
      const nodeType = node?.node_type || nodeOption?.node_type || 'pretreatment';
      const version = node?.version || nodeOption?.version || '-';
      const status = node?.status || nodeOption?.status || 'draft';
      return {
        local_key: item.local_key,
        route_node_id: item.route_node_id,
        node_id: Number(item.node_id),
        sort_order: index + 1,
        node_code: nodeCode,
        node_name: nodeName,
        node_type: nodeType,
        version,
        status,
        remark: item.remark || null,
        node_params_json: item.node_params_json || null,
      };
    })
    .filter((item) => Number.isFinite(item.node_id) && item.node_id > 0),
);

const routeSummaryItems = computed(() => {
  const current = detail.value?.route;
  if (!current) return [];
  return [
    { label: '路线编码', value: current.code },
    { label: '路线名称', value: current.name },
    { label: '输入原料', value: detail.value?.input_material?.name || current.input_material_name || '-' },
    { label: '最终产品', value: detail.value?.final_product?.name || current.final_product_name || '-' },
    { label: '版本号', value: current.version },
    { label: '状态', value: statusLabel(current.status) },
    { label: '节点数量', value: String(editableNodes.value.length) },
    { label: '更新时间', value: formatDateTime(current.updated_at) },
  ];
});

const hasUnsavedNodeChanges = computed(() => {
  const original = (detail.value?.nodes || [])
    .slice()
    .sort((left, right) => left.sort_order - right.sort_order || left.id - right.id)
    .map((item, index) => ({
      node_id: item.node_id,
      sort_order: index + 1,
      node_params_json: normalizeOptionalText(item.node_params_json),
      remark: normalizeOptionalText(item.remark),
    }));
  const current = editableNodes.value.map((item, index) => ({
    node_id: Number(item.node_id),
    sort_order: index + 1,
    node_params_json: normalizeOptionalText(item.node_params_json),
    remark: normalizeOptionalText(item.remark),
  }));
  return JSON.stringify(original) !== JSON.stringify(current);
});

onMounted(() => {
  loadPage();
});

watch(
  () => selectedFlowNode.value?.node_id,
  async (nodeId) => {
    if (!nodeId || nodeDetailCache[nodeId]) return;
    selectedNodeLoading.value = true;
    try {
      nodeDetailCache[nodeId] = await getProcessNode(nodeId);
    } finally {
      selectedNodeLoading.value = false;
    }
  },
);

async function loadPage(): Promise<void> {
  if (!routeId.value) return;
  pageLoading.value = true;
  try {
    await Promise.all([loadOptions(), loadNodeLibrary()]);
    const result = await getProcessRoute(routeId.value);
    syncDetail(result);
  } finally {
    pageLoading.value = false;
  }
}

async function loadOptions(force = false): Promise<void> {
  if (
    materialOptions.value.length &&
    productOptions.value.length &&
    outputOptions.value.length &&
    consumableOptions.value.length &&
    publicServiceOptions.value.length &&
    !force
  )
    return;
  optionsLoading.value = true;
  try {
    const [materials, products, outputs, consumables, publicServices] = await Promise.all([
      listProcessLibraryOptions('materials'),
      listProcessLibraryOptions('products', { output_type: 'product' }),
      listProcessLibraryOptions('products'),
      listProcessLibraryOptions('consumables'),
      listProcessLibraryOptions('public-services'),
    ]);
    materialOptions.value = materials;
    productOptions.value = products;
    outputOptions.value = outputs;
    consumableOptions.value = consumables;
    publicServiceOptions.value = publicServices;
  } finally {
    optionsLoading.value = false;
  }
}

async function loadNodeLibrary(): Promise<void> {
  nodeLibraryLoading.value = true;
  try {
    const firstPage = await listProcessNodes({ page: 1, page_size: STATS_FETCH_PAGE_SIZE });
    const items: NodeLibraryRecord[] = [...firstPage.items];
    const totalPages = Math.ceil(firstPage.total / firstPage.page_size);
    if (totalPages > 1) {
      const restPages = await Promise.all(
        Array.from({ length: totalPages - 1 }, (_, index) =>
          listProcessNodes({
            page: index + 2,
            page_size: firstPage.page_size,
          }),
        ),
      );
      restPages.forEach((result) => items.push(...result.items));
    }
    nodeOptions.value = items.sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);
  } finally {
    nodeLibraryLoading.value = false;
  }
}

function syncDetail(result: ProcessRouteDetail): void {
  detail.value = result;
  editableNodes.value = result.nodes
    .slice()
    .sort((left, right) => left.sort_order - right.sort_order || left.id - right.id)
    .map((item, index) => ({
      local_key: `route-node-${item.id}`,
      route_node_id: item.id,
      node_id: item.node_id,
      sort_order: index + 1,
      node_params_json: item.node_params_json || '',
      remark: item.remark || '',
    }));
  result.nodes.forEach((item) => {
    nodeDetailCache[item.node_id] = item.node;
  });
  if (!editableNodes.value.length) {
    selectedNodeKey.value = null;
    return;
  }
  const exists = editableNodes.value.some((item) => item.local_key === selectedNodeKey.value);
  selectedNodeKey.value = exists && selectedNodeKey.value ? selectedNodeKey.value : editableNodes.value[0].local_key;
}

function openEditDialog(): void {
  if (!detail.value) return;
  formVisible.value = true;
}

function openPreviewPage(): void {
  if (!detail.value) return;
  const target = router.resolve(`/process-config/routes/${detail.value.route.id}/preview`);
  window.open(target.href, '_blank', 'noopener,noreferrer');
}

function addNodeToRoute(node: NodeLibraryRecord): void {
  editableNodes.value = [
    ...editableNodes.value,
    {
      local_key: `route-local-${Date.now()}-${localNodeSeed++}`,
      node_id: node.id,
      sort_order: editableNodes.value.length + 1,
      node_params_json: '',
      remark: '',
    },
  ].map((item, index) => ({
    ...item,
    sort_order: index + 1,
  }));
  selectedNodeKey.value = editableNodes.value[editableNodes.value.length - 1]?.local_key || null;
}

function moveNodeUp(localKey: string): void {
  const index = editableNodes.value.findIndex((item) => item.local_key === localKey);
  if (index <= 0) return;
  const next = [...editableNodes.value];
  [next[index - 1], next[index]] = [next[index], next[index - 1]];
  editableNodes.value = reindexEditableNodes(next);
}

function moveNodeDown(localKey: string): void {
  const index = editableNodes.value.findIndex((item) => item.local_key === localKey);
  if (index === -1 || index >= editableNodes.value.length - 1) return;
  const next = [...editableNodes.value];
  [next[index], next[index + 1]] = [next[index + 1], next[index]];
  editableNodes.value = reindexEditableNodes(next);
}

function removeNode(localKey: string): void {
  editableNodes.value = reindexEditableNodes(editableNodes.value.filter((item) => item.local_key !== localKey));
  if (selectedNodeKey.value === localKey) {
    selectedNodeKey.value = editableNodes.value[0]?.local_key || null;
  }
}

function handleSelectNode(localKey: string): void {
  selectedNodeKey.value = localKey;
}

function reindexEditableNodes(items: RouteEditableNode[]): RouteEditableNode[] {
  return items.map((item, index) => ({
    ...item,
    sort_order: index + 1,
  }));
}

async function handleSaveRoute(): Promise<void> {
  if (!detail.value) return;
  if (detail.value.route.status === 'enabled' && !editableNodes.value.length) {
    MessagePlugin.warning('启用路线至少需要配置一个节点');
    return;
  }

  saving.value = true;
  try {
    const payload = buildRoutePayload(detail.value);
    const result = await updateProcessRoute(detail.value.route.id, payload);
    MessagePlugin.success('工艺路线已保存');
    syncDetail(result);
  } finally {
    saving.value = false;
  }
}

async function handleFormSubmit(payload: ProcessRoutePayload): Promise<void> {
  if (!detail.value) return;
  formSaving.value = true;
  try {
    const result = await updateProcessRoute(detail.value.route.id, payload);
    MessagePlugin.success('工艺路线已更新');
    formVisible.value = false;
    syncDetail(result);
  } finally {
    formSaving.value = false;
  }
}

function buildRoutePayload(source: ProcessRouteDetail): ProcessRoutePayload {
  return {
    code: source.route.code,
    name: source.route.name,
    input_material_id: source.route.input_material_id,
    final_product_id: source.route.final_product_id,
    version: source.route.version,
    description: normalizeOptionalText(source.route.description),
    status: source.route.status,
    sort_order: source.route.sort_order,
    remark: normalizeOptionalText(source.route.remark),
    nodes: editableNodes.value.map((item, index) => ({
      node_id: Number(item.node_id),
      sort_order: index + 1,
      node_params_json: normalizeOptionalText(item.node_params_json),
      remark: normalizeOptionalText(item.remark),
    })),
  };
}

function normalizeOptionalText(value?: string | null): string | null {
  const text = value?.trim();
  return text || null;
}

function handleBack(): void {
  const target = previousBreadcrumbTarget(route);
  router.push(target || '/process-config/routes');
}

function statusLabel(status: string): string {
  return (
    {
      enabled: '启用',
      draft: '草稿',
      disabled: '停用',
    }[status] || status
  );
}

function statusTheme(status: string): 'success' | 'warning' | 'default' {
  return (
    {
      enabled: 'success',
      draft: 'warning',
      disabled: 'default',
    }[status] || 'default'
  );
}

function nodeTypeLabel(value: string): string {
  return PROCESS_NODE_TYPE_OPTIONS.find((item) => item.value === value)?.label || value;
}
</script>

<template>
  <div class="system-card scroll-card route-detail-card">
    <div class="system-section-head">
      <div class="system-section-title">
        <h2>路线详情</h2>
        <span v-if="detail">{{ detail.route.code }} / {{ detail.route.version }}</span>
      </div>
      <t-space>
        <t-button variant="outline" @click="handleBack">
          <template #icon><ArrowLeftIcon /></template>
          返回
        </t-button>
        <t-button v-permission="permissions.view" variant="outline" :loading="pageLoading" @click="loadPage">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button v-permission="permissions.update" theme="default" variant="outline" @click="openEditDialog">
          <template #icon><EditIcon /></template>
          编辑路线
        </t-button>
        <t-button v-permission="permissions.preview" theme="default" variant="outline" :disabled="!detail" @click="openPreviewPage">
          <template #icon><BrowseIcon /></template>
          线路预览
        </t-button>
        <t-button v-permission="permissions.version" theme="default" variant="outline" @click="versionDialogVisible = true">
          <template #icon><TimeIcon /></template>
          版本管理
        </t-button>
        <t-button v-permission="permissions.update" theme="primary" :disabled="!hasUnsavedNodeChanges" :loading="saving" @click="handleSaveRoute">
          <template #icon><SaveIcon /></template>
          保存路线
        </t-button>
      </t-space>
    </div>

    <div class="route-detail-page">
      <t-loading :loading="pageLoading">
        <div v-if="detail" class="route-detail-page__content">
          <section class="route-summary-card">
            <div class="route-summary-card__header">
              <div>
                <h2>{{ detail.route.name }}</h2>
                <p>{{ detail.route.code }} / {{ detail.route.version }}</p>
              </div>
              <t-tag size="medium" variant="light" :theme="statusTheme(detail.route.status)">{{ statusLabel(detail.route.status) }}</t-tag>
            </div>
            <div class="route-summary-grid">
              <div v-for="item in routeSummaryItems" :key="item.label" class="route-summary-item">
                <span>{{ item.label }}</span>
                <strong>{{ item.value }}</strong>
              </div>
            </div>
            <div v-if="detail.route.description || detail.route.remark" class="route-summary-extra">
              <div>
                <span>描述</span>
                <strong>{{ detail.route.description || '-' }}</strong>
              </div>
              <div>
                <span>备注</span>
                <strong>{{ detail.route.remark || '-' }}</strong>
              </div>
            </div>
          </section>

          <div class="route-workspace">
            <section class="route-library-panel">
              <div class="route-panel-header">
                <div class="route-panel-title">节点库</div>
                <span class="route-panel-count">共 {{ filteredNodeLibrary.length }} 个</span>
              </div>
              <t-input v-model="nodeLibraryKeyword" clearable placeholder="搜索节点编码 / 名称 / 类型" />
              <div class="route-library-panel__list">
                <t-loading :loading="nodeLibraryLoading">
                  <t-empty v-if="!filteredNodeLibrary.length" description="暂无可用节点" />
                  <button
                    v-for="item in filteredNodeLibrary"
                    :key="item.id"
                    type="button"
                    class="library-node-card"
                    :disabled="!canUpdate"
                    @click="addNodeToRoute(item)"
                  >
                    <div class="library-node-card__head">
                      <strong>{{ item.name }}</strong>
                      <t-tag size="small" variant="light" :theme="statusTheme(item.status)">{{ statusLabel(item.status) }}</t-tag>
                    </div>
                    <div class="library-node-card__meta">
                      <span>{{ item.code }}</span>
                      <span>{{ nodeTypeLabel(item.node_type) }}</span>
                      <span>{{ item.version }}</span>
                    </div>
                    <div class="library-node-card__action" :class="{ 'library-node-card__action--disabled': !canUpdate }">
                      {{ canUpdate ? '点击加入路线' : '无编辑权限' }}
                    </div>
                  </button>
                </t-loading>
              </div>
            </section>

            <section class="route-chain-panel">
              <div class="route-panel-header">
                <div class="route-panel-title">路线链路图</div>
                <span class="route-panel-count">已配置 {{ editableNodes.length }} 个节点</span>
              </div>
              <RouteFlowViewer
                :nodes="flowNodes"
                :selected-key="selectedNodeKey"
                :editable="canUpdate"
                :disabled="saving"
                @select="handleSelectNode"
                @move-up="moveNodeUp"
                @move-down="moveNodeDown"
                @remove="removeNode"
              />
            </section>

            <section class="route-node-panel">
              <div class="route-panel-header">
                <div class="route-panel-title">节点配置详情</div>
                <span class="route-panel-count">{{ selectedFlowNode?.node_name || '未选择节点' }}</span>
              </div>
              <RouteNodeDetailPanel
                :node="selectedNodeDetail"
                :loading="selectedNodeLoading"
                :material-options="materialOptions"
                :product-options="outputOptions"
                :consumable-options="consumableOptions"
                :public-service-options="publicServiceOptions"
              />
            </section>
          </div>
        </div>
      </t-loading>
    </div>

    <RouteFormDialog
      v-model:visible="formVisible"
      mode="edit"
      :route="detail"
      :node-options="nodeOptions"
      :material-options="materialOptions"
      :product-options="productOptions"
      :saving="formSaving"
      :options-loading="optionsLoading || nodeLibraryLoading"
      @submit="handleFormSubmit"
    />

    <RouteVersionDialog
      v-model:visible="versionDialogVisible"
      :route-id="detail?.route.id || null"
      :route-name="detail?.route.name || ''"
      :can-create="canManageVersion"
    />
  </div>
</template>

<style scoped>
.route-detail-card {
  display: flex;
  flex: 1 1 0;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  overflow: hidden;
}

.system-section-head {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 16px;
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

.route-detail-page {
  flex: 1 1 0;
  min-height: 0;
  overflow: auto;
}

.route-detail-page__content {
  display: grid;
  gap: 16px;
  padding-right: 2px;
}

.route-summary-card {
  display: grid;
  gap: 16px;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 18px 20px;
}

.route-summary-card__header {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.route-summary-card__header h2 {
  margin: 0;
  color: #0f172a;
  font-size: 22px;
  font-weight: 800;
}

.route-summary-card__header p {
  margin: 6px 0 0;
  color: #64748b;
  font-size: 13px;
}

.route-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.route-summary-item {
  display: grid;
  gap: 4px;
  border: 1px solid #eef2f7;
  border-radius: 6px;
  background: #f8fafc;
  padding: 12px 14px;
}

.route-summary-item span,
.route-summary-extra span {
  color: #64748b;
  font-size: 12px;
}

.route-summary-item strong,
.route-summary-extra strong {
  color: #111827;
  font-size: 14px;
  font-weight: 700;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

.route-summary-extra {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.route-summary-extra > div {
  display: grid;
  gap: 4px;
  border-top: 1px solid #eef2f7;
  padding-top: 12px;
}

.route-workspace {
  display: grid;
  grid-template-columns: 280px minmax(340px, 1fr) minmax(380px, 1.15fr);
  gap: 16px;
  align-items: start;
}

.route-library-panel,
.route-chain-panel,
.route-node-panel {
  display: grid;
  gap: 12px;
  min-height: 0;
  border: 1px solid #e6ebf2;
  border-radius: 6px;
  background: #fff;
  padding: 16px;
}

.route-panel-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 12px;
}

.route-panel-title {
  color: #0f172a;
  font-size: 16px;
  font-weight: 800;
}

.route-panel-count {
  color: #64748b;
  font-size: 12px;
}

.route-library-panel__list {
  display: grid;
  gap: 10px;
  max-height: 760px;
  overflow: auto;
  padding-right: 2px;
}

.library-node-card {
  display: grid;
  gap: 8px;
  width: 100%;
  border: 1px solid #e5edf7;
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
  padding: 12px;
  text-align: left;
  transition:
    border-color 0.18s ease,
    box-shadow 0.18s ease,
    transform 0.18s ease;
}

.library-node-card:hover {
  border-color: #bfd6ff;
  box-shadow: 0 8px 18px rgb(15 23 42 / 8%);
  transform: translateY(-1px);
}

.library-node-card:disabled {
  cursor: not-allowed;
  opacity: 0.72;
}

.library-node-card:disabled:hover {
  border-color: #e5edf7;
  box-shadow: none;
  transform: none;
}

.library-node-card__head {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.library-node-card__head strong {
  min-width: 0;
  color: #0f172a;
  font-size: 14px;
  font-weight: 700;
  overflow-wrap: anywhere;
}

.library-node-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  color: #64748b;
  font-size: 12px;
}

.library-node-card__action {
  color: #0052d9;
  font-size: 12px;
  font-weight: 600;
}

.library-node-card__action--disabled {
  color: #94a3b8;
}

@media (max-width: 1400px) {
  .route-workspace {
    grid-template-columns: minmax(0, 1fr);
  }

  .route-library-panel__list {
    max-height: none;
  }
}

@media (max-width: 900px) {
  .system-section-head {
    align-items: stretch;
    flex-direction: column;
  }

  .route-summary-grid,
  .route-summary-extra {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .route-summary-grid,
  .route-summary-extra {
    grid-template-columns: 1fr;
  }
}
</style>
