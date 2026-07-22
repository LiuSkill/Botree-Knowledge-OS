<script setup lang="ts">
import { FullscreenIcon, RefreshIcon, ZoomInIcon, ZoomOutIcon } from 'tdesign-icons-vue-next';
import { computed, ref, watch } from 'vue';

const MIN_ZOOM = 50;
const MAX_ZOOM = 200;
const ZOOM_STEP = 10;
const DEFAULT_ZOOM = 100;

const props = defineProps<{
  title: string;
  versionLabel: string;
}>();

const visible = defineModel<boolean>('visible', { default: false });
const zoomPercent = ref(DEFAULT_ZOOM);
const previewStyle = computed(() => ({ zoom: String(zoomPercent.value / DEFAULT_ZOOM) }));

function changeZoom(delta: number): void {
  zoomPercent.value = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoomPercent.value + delta));
}

function resetZoom(): void {
  zoomPercent.value = DEFAULT_ZOOM;
}

function closeDialog(): void {
  visible.value = false;
  resetZoom();
}

watch(visible, (isVisible) => {
  if (!isVisible) resetZoom();
});
</script>

<template>
  <t-dialog
    v-model:visible="visible"
    attach="body"
    placement="center"
    width="min(1200px, 96vw)"
    :footer="false"
    destroy-on-close
    :close-on-overlay-click="true"
    @close="closeDialog"
  >
    <template #header>
      <div class="zoom-dialog-header">
        <div class="zoom-dialog-title" :title="props.title">
          <FullscreenIcon />
          <span>{{ props.title }}</span>
          <span class="zoom-dialog-version">{{ props.versionLabel }}</span>
        </div>
        <div class="zoom-dialog-tools" aria-label="预览缩放工具栏">
          <t-button
            size="small"
            variant="outline"
            :disabled="zoomPercent <= MIN_ZOOM"
            aria-label="缩小预览"
            @click="changeZoom(-ZOOM_STEP)"
          >
            <template #icon><ZoomOutIcon /></template>
          </t-button>
          <span class="zoom-dialog-percent">{{ zoomPercent }}%</span>
          <t-button
            size="small"
            variant="outline"
            :disabled="zoomPercent >= MAX_ZOOM"
            aria-label="放大预览"
            @click="changeZoom(ZOOM_STEP)"
          >
            <template #icon><ZoomInIcon /></template>
          </t-button>
          <t-button size="small" variant="text" :disabled="zoomPercent === DEFAULT_ZOOM" @click="resetZoom">
            <template #icon><RefreshIcon /></template>
            重置
          </t-button>
        </div>
      </div>
    </template>

    <div class="zoom-dialog-scroll">
      <div class="zoom-dialog-content" :style="previewStyle">
        <slot />
      </div>
    </div>
  </t-dialog>
</template>

<style scoped>
.zoom-dialog-header {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 12px 20px;
  padding-right: 8px;
}

.zoom-dialog-title,
.zoom-dialog-tools {
  display: flex;
  align-items: center;
}

.zoom-dialog-title {
  min-width: 0;
  gap: 8px;
  font-weight: 600;
}

.zoom-dialog-title > span:first-of-type {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.zoom-dialog-version {
  flex: 0 0 auto;
  color: var(--td-text-color-secondary);
  font-size: 13px;
  font-weight: 400;
}

.zoom-dialog-tools {
  flex: 0 0 auto;
  gap: 8px;
}

.zoom-dialog-percent {
  width: 52px;
  color: var(--td-text-color-secondary);
  font-variant-numeric: tabular-nums;
  text-align: center;
}

.zoom-dialog-scroll {
  height: 78vh;
  overflow: auto;
  border: 1px solid var(--td-component-border);
  border-radius: 6px;
  background: var(--td-bg-color-container-hover);
}

.zoom-dialog-content {
  min-width: 100%;
  min-height: 100%;
  padding: 20px;
  box-sizing: border-box;
  background: #fff;
  transform-origin: left top;
}

@media (max-width: 720px) {
  .zoom-dialog-header,
  .zoom-dialog-title {
    width: 100%;
  }

  .zoom-dialog-tools {
    flex-wrap: wrap;
  }

  .zoom-dialog-scroll {
    height: 72vh;
  }
}
</style>
