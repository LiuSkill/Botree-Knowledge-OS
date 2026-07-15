<script setup lang="ts">
import { ArrowLeftIcon, RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { getProcessRouteTreePreview } from '@/api/process-config';
import RouteTreePreviewNode from '@/views/process-config/route/components/RouteTreePreviewNode.vue';
import type {
  ProcessRouteTreeNode,
  ProcessRouteTreePreview,
  ProcessRouteTreeRoute,
  RouteTreePreviewNode as RouteTreePreviewNodeData,
} from '@/views/process-config/route/types';

const MIN_ZOOM = 0.18;
const MAX_ZOOM = 1.25;
const ZOOM_STEP = 0.1;

const route = useRoute();
const router = useRouter();

const loading = ref(false);
const previewData = ref<ProcessRouteTreePreview | null>(null);
const canvasRef = ref<HTMLElement | null>(null);
const treeContentRef = ref<HTMLElement | null>(null);
const zoom = ref(1);
const treeNaturalSize = ref({ width: 1200, height: 520 });

const routeId = computed(() => Number(route.params.id));
const currentRoute = computed(() => previewData.value?.routes.find((item) => item.id === routeId.value) || null);
const selectedRouteIds = computed(() => {
  const ids = String(route.query.routes || '')
    .split(',')
    .map((item) => Number(item))
    .filter((item) => Number.isFinite(item) && item > 0);
  return new Set([routeId.value, ...ids]);
});
const selectedRoutes = computed(() =>
  (previewData.value?.routes || []).filter((item) => selectedRouteIds.value.has(item.id)),
);
const previewTree = computed(() => buildPreviewTree(previewData.value?.routes || [], selectedRouteIds.value));
const zoomPercent = computed(() => `${Math.round(zoom.value * 100)}%`);

const routeSummary = computed(() => {
  if (!selectedRoutes.value.length) return currentRoute.value?.name || '';
  return selectedRoutes.value.map((item) => item.name).join(' + ');
});

const stageStyle = computed(() => ({
  width: `${Math.max(treeNaturalSize.value.width * zoom.value, 960)}px`,
  height: `${Math.max(treeNaturalSize.value.height * zoom.value, 420)}px`,
}));

const treeTransformStyle = computed(() => ({
  transform: `scale(${zoom.value})`,
}));

onMounted(() => {
  window.addEventListener('wheel', handlePreviewWheel, { passive: false });
  window.addEventListener('keydown', handleShortcutZoom);
  loadPreviewData();
});

onBeforeUnmount(() => {
  window.removeEventListener('wheel', handlePreviewWheel);
  window.removeEventListener('keydown', handleShortcutZoom);
});

watch(routeId, () => {
  loadPreviewData();
});

watch(
  previewTree,
  () => {
    nextTick(() => {
      fitToWidth();
    });
  },
  { flush: 'post' },
);

async function loadPreviewData(): Promise<void> {
  if (!Number.isFinite(routeId.value) || routeId.value <= 0 || loading.value) return;
  loading.value = true;
  try {
    previewData.value = await getProcessRouteTreePreview(routeId.value);
    await nextTick();
    fitToWidth();
  } finally {
    loading.value = false;
  }
}

function buildPreviewTree(routes: ProcessRouteTreeRoute[], activeRouteIds: Set<number>): RouteTreePreviewNodeData[] {
  const roots: RouteTreePreviewNodeData[] = [];
  const renderedWasteKeys = new Set<string>();
  const orderedRoutes = routes.slice().sort((left, right) => left.sort_order - right.sort_order || left.id - right.id);

  orderedRoutes.forEach((routeDetail) => {
    const isCurrentRoute = activeRouteIds.has(routeDetail.id);
    const material = routeDetail.input_material;
    let cursor = ensureChild(roots, `material:${material.code}`, () => ({
      key: `material:${material.code}`,
      label: material.name,
      code: material.code,
      meta: material.unit,
      kind: 'material',
      active: isCurrentRoute,
      children: [],
    }));
    if (isCurrentRoute) {
      cursor.active = true;
    }

    routeDetail.nodes
      .slice()
      .sort((left, right) => left.sort_order - right.sort_order || left.route_node_id - right.route_node_id)
      .forEach((node) => {
        cursor = ensureChild(cursor.children, `node:${node.code}`, () => ({
          key: `${cursor.key}>node:${node.code}`,
          label: node.name,
          code: node.code,
          meta: node.version,
          kind: 'node',
          active: isCurrentRoute,
          children: [],
        }));
        if (isCurrentRoute) {
          cursor.active = true;
        }
        appendWasteOutputs(cursor, node, renderedWasteKeys, isCurrentRoute);
      });

    const product = routeDetail.final_product;
    const productNode = ensureChild(cursor.children, `product:${product.code}`, () => ({
      key: `${cursor.key}>product:${product.code}`,
      label: product.name,
      code: product.code,
      meta: product.unit,
      kind: 'product',
      active: isCurrentRoute,
      children: [],
    }));
    if (isCurrentRoute) {
      productNode.active = true;
    }
  });

  return roots;
}

function ensureChild(
  children: RouteTreePreviewNodeData[],
  key: string,
  factory: () => RouteTreePreviewNodeData,
): RouteTreePreviewNodeData {
  const existing = children.find((item) => item.key.endsWith(key) || item.key === key);
  if (existing) return existing;
  const created = factory();
  children.push(created);
  return created;
}

function appendWasteOutputs(
  parent: RouteTreePreviewNodeData,
  node: ProcessRouteTreeNode,
  renderedWasteKeys: Set<string>,
  isCurrentRoute: boolean,
): void {
  node.outputs
    .filter((output) => output.output_type === 'solid_waste' || output.output_type === 'wastewater')
    .forEach((output) => {
      const product = output.product;
      const wasteKey = `${node.code}:${output.output_type}:${product?.code || output.product_id}`;
      if (!isCurrentRoute && renderedWasteKeys.has(wasteKey)) return;
      renderedWasteKeys.add(wasteKey);
      ensureChild(parent.children, `waste:${output.product_id}`, () => ({
        key: `${parent.key}>waste:${output.product_id}`,
        label: product?.name || `#${output.product_id}`,
        code: product?.code || null,
        meta: output.output_type === 'solid_waste' ? '废固' : '废水',
        kind: 'waste',
        active: isCurrentRoute,
        children: [],
      }));
    });
}

function setZoom(value: number): void {
  zoom.value = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Number(value.toFixed(2))));
}

function zoomIn(): void {
  setZoom(zoom.value + ZOOM_STEP);
}

function zoomOut(): void {
  setZoom(zoom.value - ZOOM_STEP);
}

function handlePreviewWheel(event: WheelEvent): void {
  if (!event.ctrlKey && !event.metaKey) return;
  event.preventDefault();
  if (event.deltaY < 0) {
    zoomIn();
    return;
  }
  zoomOut();
}

function handleShortcutZoom(event: KeyboardEvent): void {
  if (!event.ctrlKey && !event.metaKey) return;
  if (event.key === '+' || event.key === '=') {
    event.preventDefault();
    zoomIn();
    return;
  }
  if (event.key === '-' || event.key === '_') {
    event.preventDefault();
    zoomOut();
    return;
  }
  if (event.key === '0') {
    event.preventDefault();
    resetZoom();
  }
}

function resetZoom(): void {
  setZoom(1);
  nextTick(() => {
    canvasRef.value?.scrollTo({ left: 0, top: 0 });
  });
}

function fitToWidth(): void {
  updateTreeNaturalSize();
  const canvasWidth = canvasRef.value?.clientWidth || 0;
  const treeWidth = treeNaturalSize.value.width;
  if (!canvasWidth || !treeWidth) return;
  setZoom((canvasWidth - 32) / treeWidth);
  nextTick(() => {
    canvasRef.value?.scrollTo({ left: 0, top: 0 });
  });
}

function updateTreeNaturalSize(): void {
  const treeEl = treeContentRef.value;
  if (!treeEl) return;
  treeNaturalSize.value = {
    width: Math.max(treeEl.offsetWidth, 1),
    height: Math.max(treeEl.offsetHeight, 1),
  };
}

function backToDetail(): void {
  router.push(`/process-config/routes/${routeId.value}`);
}
</script>

<template>
  <div class="route-preview-page">
    <div class="route-preview-page__toolbar">
      <div class="route-preview-page__title">
        <h2>线路预览</h2>
        <span v-if="routeSummary">{{ routeSummary }}</span>
      </div>
      <t-space>
        <t-tag variant="light" theme="primary">当前路线节点</t-tag>
        <t-tag variant="light" theme="danger">红色为产品</t-tag>
        <t-tag class="route-preview-page__legend-waste" variant="light">紫色为三废</t-tag>
        <t-button size="small" variant="outline" @click="fitToWidth">适应宽度</t-button>
        <t-button size="small" variant="outline" @click="zoomOut">缩小</t-button>
        <t-tag variant="light">{{ zoomPercent }}</t-tag>
        <t-button size="small" variant="outline" @click="zoomIn">放大</t-button>
        <t-button size="small" variant="outline" @click="resetZoom">100%</t-button>
        <t-button size="small" variant="outline" :loading="loading" @click="loadPreviewData">
          <template #icon><RefreshIcon /></template>
          刷新
        </t-button>
        <t-button size="small" variant="outline" @click="backToDetail">
          <template #icon><ArrowLeftIcon /></template>
          返回详情
        </t-button>
      </t-space>
    </div>

    <t-loading class="route-preview-page__loading" :loading="loading">
      <div ref="canvasRef" class="route-preview-page__canvas">
        <t-empty v-if="!previewTree.length" description="暂无可预览的工艺路线" />
        <div v-else class="route-preview-page__stage" :style="stageStyle">
          <div ref="treeContentRef" class="preview-tree" :style="treeTransformStyle">
            <RouteTreePreviewNode v-for="node in previewTree" :key="node.key" :node="node" />
          </div>
        </div>
      </div>
    </t-loading>
  </div>
</template>

<style scoped>
.route-preview-page {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 14px;
  width: 100vw;
  height: 100vh;
  box-sizing: border-box;
  background: #f5f7fb;
  overflow: hidden;
  padding: 16px 18px 18px;
}

.route-preview-page__toolbar {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px 16px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  padding: 12px 14px;
}

.route-preview-page__title {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 10px 16px;
}

.route-preview-page__title h2 {
  margin: 0;
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
}

.route-preview-page__title span {
  max-width: 720px;
  overflow: hidden;
  color: #64748b;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.route-preview-page__legend-waste {
  border-color: #d8b4fe;
  background: #faf5ff;
  color: #7e22ce;
}

.route-preview-page__loading {
  height: 100%;
  min-height: 0;
}

.route-preview-page__canvas {
  height: 100%;
  min-height: 0;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  overflow-x: scroll;
  overflow-y: auto;
  padding: 24px;
  scrollbar-gutter: stable both-edges;
}

.route-preview-page__canvas::-webkit-scrollbar {
  width: 14px;
  height: 14px;
}

.route-preview-page__canvas::-webkit-scrollbar-thumb {
  border: 3px solid #fff;
  border-radius: 999px;
  background: #94a3b8;
}

.route-preview-page__canvas::-webkit-scrollbar-track {
  border-radius: 999px;
  background: #eef2f7;
}

.route-preview-page__stage {
  min-width: 100%;
  min-height: 100%;
  position: relative;
}

.preview-tree {
  display: grid;
  width: max-content;
  min-width: max-content;
  align-items: start;
  gap: 18px;
  transform-origin: left top;
}

@media (max-width: 900px) {
  .route-preview-page__toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .route-preview-page__title span {
    max-width: 100%;
    white-space: normal;
  }

  .route-preview-page__canvas {
    padding: 16px;
  }
}
</style>
