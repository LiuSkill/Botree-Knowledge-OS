<!--
  CitationList

  负责：
  1. 展示 AI 回答引用来源
  2. 保留文件名、页码和片段内容
  3. 支撑问答来源追溯
-->
<script setup lang="ts">
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onBeforeUnmount, reactive, watch } from 'vue';

import { downloadDocumentAsset } from '@/api/documents';
import ChatRichContent from '@/components/ChatRichContent.vue';
import type { Citation, CitationAsset } from '@/types/api';

const props = defineProps<{
  citations: Citation[];
  chatType?: 'project_chat' | 'base_chat';
}>();

const assetUrlMap = reactive<Record<number, string>>({});
const loadingAssetIds = reactive<Record<number, boolean>>({});
const CITATION_ASSET_METADATA_KEYS = [
  'original_candidate_value',
  'resolved_local_path',
  'local_path',
  'inline_payload_key',
  'remote_url',
  'image_path',
  'img_path',
  'path',
  'saved_path',
  'file_name',
  'image_name',
  'img_name',
] as const;
const visualAssets = computed(() => {
  const assets = props.citations.flatMap((citation) => citation.assets || []);
  return Array.from(new Map(assets.map((asset) => [asset.asset_id, asset])).values());
});

function sourceLabel(sourceType: Citation['source_type'], chatType?: 'project_chat' | 'base_chat'): string {
  /**
   * 根据问答入口转换引用来源展示文案。
   */
  if (chatType === 'project_chat') {
    return sourceType === 'project' ? '项目资料' : '基础知识';
  }
  if (sourceType === 'project') return '项目知识';
  return '基础知识';
}

function resetAssetUrls(): void {
  /**
   * 释放引用图片 Blob URL，避免切换会话后浏览器内存持续上涨。
   */
  for (const url of Object.values(assetUrlMap)) {
    URL.revokeObjectURL(url);
  }
  for (const key of Object.keys(assetUrlMap)) {
    delete assetUrlMap[Number(key)];
  }
}

async function ensureAssetUrl(asset: CitationAsset): Promise<void> {
  /**
   * 引用图片必须通过鉴权接口下载，不能直接把 /api URL 塞给 img 标签。
   */
  if (assetUrlMap[asset.asset_id] || loadingAssetIds[asset.asset_id]) return;
  loadingAssetIds[asset.asset_id] = true;
  try {
    const blob = await downloadDocumentAsset(asset.asset_id);
    assetUrlMap[asset.asset_id] = URL.createObjectURL(blob);
  } catch (error) {
    MessagePlugin.warning(error instanceof Error ? error.message : `图片 #${asset.asset_id} 加载失败`);
  } finally {
    delete loadingAssetIds[asset.asset_id];
  }
}

function openAssetPreview(asset: CitationAsset): void {
  const url = assetUrlMap[asset.asset_id];
  if (!url) return;
  window.open(url, '_blank', 'noopener,noreferrer');
}

function normalizeAssetKey(value: string): string {
  return value
    .trim()
    .replace(/^['"]|['"]$/g, '')
    .replace(/[?#].*$/g, '')
    .replace(/\\/g, '/')
    .replace(/^\.\//, '')
    .replace(/^\/+/, '')
    .toLowerCase();
}

function basenameFromPath(value: string): string {
  const normalized = normalizeAssetKey(value);
  return normalized.split('/').filter(Boolean).pop() || normalized;
}

function collectMetadataStrings(value: unknown): string[] {
  if (typeof value === 'string' && value.trim()) return [value];
  if (Array.isArray(value)) return value.flatMap((item) => collectMetadataStrings(item));
  return [];
}

function collectAssetLookupKeys(asset: CitationAsset): string[] {
  /**
   * MinerU 图片可能以 images/xxx、绝对路径或后端资产 URL 出现在 Markdown 中，
   * 这里统一生成可匹配的安全键，最终仍只使用鉴权下载后的 Blob URL 展示。
   */
  const metadata = asset.metadata || {};
  const rawValues = [
    asset.file_name,
    asset.url,
    ...CITATION_ASSET_METADATA_KEYS.flatMap((key) => collectMetadataStrings(metadata[key])),
  ].filter((item): item is string => typeof item === 'string' && item.trim().length > 0);

  const keys = new Set<string>();
  for (const value of rawValues) {
    const normalized = normalizeAssetKey(value);
    keys.add(normalized);
    keys.add(basenameFromPath(normalized));
  }
  return Array.from(keys);
}

function findCitationAssetBySource(src: string, citation: Citation): CitationAsset | null {
  const normalizedSrc = normalizeAssetKey(src);
  const basename = basenameFromPath(normalizedSrc);
  return (
    (citation.assets || []).find((asset) => {
      const keys = collectAssetLookupKeys(asset);
      return keys.includes(normalizedSrc) || keys.includes(basename);
    }) || null
  );
}

function resolveCitationImageUrl(src: string, citation: Citation): string {
  const asset = findCitationAssetBySource(src, citation);
  return asset ? assetUrlMap[asset.asset_id] || '' : '';
}

watch(
  visualAssets,
  async (assets) => {
    resetAssetUrls();
    await Promise.all(assets.map((asset) => ensureAssetUrl(asset)));
  },
  { immediate: true },
);

onBeforeUnmount(resetAssetUrls);
</script>

<template>
  <div class="citation-list">
    <t-empty v-if="!citations.length" size="small" description="暂无引用来源" />
    <div v-for="item in citations" :key="`${item.document_id}-${item.chunk_id}`" class="citation-item">
      <div class="citation-title">
        <span>{{ item.file_name }}</span>
        <t-tag size="small" variant="light">{{ sourceLabel(item.source_type, chatType) }}</t-tag>
      </div>
      <p v-if="item.drawing_no || item.page_number" class="citation-meta">
        <span v-if="item.drawing_no">图号：{{ item.drawing_no }}</span>
        <span v-if="item.page_number">第 {{ item.page_number }} 页</span>
      </p>
      <div v-if="item.assets?.length" class="citation-assets">
        <t-button
          v-for="asset in item.assets"
          :key="asset.asset_id"
          class="citation-asset"
          variant="outline"
          :disabled="!assetUrlMap[asset.asset_id]"
          @click="openAssetPreview(asset)"
        >
          <img
            v-if="assetUrlMap[asset.asset_id]"
            :src="assetUrlMap[asset.asset_id]"
            :alt="asset.file_name"
            loading="lazy"
            decoding="async"
          />
          <span v-else class="asset-loading">加载中</span>
        </t-button>
      </div>
      <ChatRichContent
        class="citation-content"
        :content="item.content"
        :image-source-resolver="(src) => resolveCitationImageUrl(src, item)"
      />
    </div>
  </div>
</template>

<style scoped>
.citation-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.citation-item {
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
}

.citation-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-weight: 600;
  color: #111827;
}

.citation-title > span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.citation-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 6px 0;
  color: #6b7280;
  font-size: 12px;
}

.citation-content {
  margin-top: 8px;
}

.citation-assets {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
  gap: 8px;
  margin: 8px 0;
}

.citation-asset {
  display: block;
  width: 100%;
  height: auto;
  min-height: 96px;
  aspect-ratio: 4 / 3;
  overflow: hidden;
  border-radius: 6px;
  padding: 0;
}

.citation-asset :deep(.t-button__text) {
  display: block;
  width: 100%;
  height: 100%;
}

.citation-asset img {
  width: 100%;
  height: 100%;
  object-fit: contain;
  background: #fff;
}

.asset-loading {
  display: grid;
  height: 100%;
  place-items: center;
  color: #6b7280;
  font-size: 12px;
}
</style>
