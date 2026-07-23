<!--
  Dashboard Page

  负责：
  1. 按首页工作台原型展示欢迎区、指标卡片和快捷入口
  2. 展示知识资产分布、近 7 天 AI 问答趋势和文档类型分布
  3. 只展示后端工作台接口返回的真实业务数据
-->
<script setup lang="ts">
import {
  AddIcon,
  CatalogIcon,
  ChatBubbleHelpIcon,
  CloudUploadIcon,
  DataBaseIcon,
  FlashlightIcon,
  FolderIcon,
} from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, ref, type Component } from 'vue';
import { useRoute, useRouter } from 'vue-router';

import { getDashboardStats } from '@/api/system';
import { PERMISSIONS } from '@/constants/permissions';
import { ROUTE_PATHS } from '@/shared/constants/routes';
import { useAuthStore } from '@/stores/auth';
import type {
  DashboardDocumentTypeStat,
  DashboardKnowledgeAssetItem,
  DashboardQaTrendDaily,
  DashboardStats,
} from '@/types/api';
import { withBreadcrumbContext } from '@/utils/breadcrumbContext';
import { formatDateTime } from '@/utils/format';

type ToneName = 'blue' | 'purple' | 'orange' | 'pink' | 'green';

interface MetricCard {
  key: string;
  title: string;
  value: number;
  icon: Component;
  tone: ToneName;
}

interface QuickAction {
  key: string;
  title: string;
  subtitle: string;
  route: string;
  icon: Component;
  tone: ToneName;
  permission: string;
}

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const stats = ref<DashboardStats | null>(null);
const loading = ref(false);
const loadFailed = ref(false);
const trendChartWrap = ref<HTMLDivElement | null>(null);
const hoveredTrendItem = ref<DashboardQaTrendDaily | null>(null);
const trendTooltipPosition = ref({ left: 0, top: 0 });
const donutChartWrap = ref<HTMLDivElement | null>(null);
const hoveredDocumentType = ref<DashboardDocumentTypeStat | null>(null);
const donutTooltipPosition = ref({ left: 0, top: 0 });
const assetChartWrap = ref<HTMLDivElement | null>(null);
const hoveredAssetItem = ref<DashboardKnowledgeAssetItem | null>(null);
const assetTooltipPosition = ref({ left: 0, top: 0 });

const DONUT_RADIUS = 48;
const DONUT_CENTER = 72;
const DONUT_STROKE_WIDTH = 18;
const DONUT_GAP_LENGTH = 7;
const DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS;
const TREND_CHART_WIDTH = 420;
const TREND_CHART_HEIGHT = 220;
const TREND_PLOT_LEFT = 42;
const TREND_PLOT_RIGHT = 14;
const TREND_PLOT_TOP = 18;
const TREND_PLOT_BOTTOM = 40;

const userDisplayName = computed(() => authStore.user?.real_name || authStore.user?.username || '未登录用户');

const pendingTaskCount = computed(() => stats.value?.pending_review_count ?? 0);

const lastLoginText = computed(() => formatDateTime(stats.value?.last_login_at));

const todayText = computed(() => {
  /**
   * 构造欢迎区日期文案，保持与原型一致的中文日期格式。
   */
  return formatChineseDate(new Date());
});

const metricCards = computed<MetricCard[]>(() => [
  {
    key: 'document',
    title: '知识文档',
    value: stats.value?.document_count ?? 0,
    icon: FolderIcon,
    tone: 'blue',
  },
  {
    key: 'entry',
    title: '知识条目数',
    value: stats.value?.knowledge_entry_count ?? 0,
    icon: CatalogIcon,
    tone: 'purple',
  },
  {
    key: 'project',
    title: '项目数量',
    value: stats.value?.project_count ?? 0,
    icon: DataBaseIcon,
    tone: 'orange',
  },
  {
    key: 'answer',
    title: 'AI 问答次数',
    value: stats.value?.ai_answer_count ?? 0,
    icon: FlashlightIcon,
    tone: 'pink',
  },
]);

const quickActionDefinitions: QuickAction[] = [
  {
    key: 'upload',
    title: '上传文档',
    subtitle: '添加知识资产',
    route: ROUTE_PATHS.knowledge,
    icon: CloudUploadIcon,
    tone: 'blue',
    permission: PERMISSIONS.KNOWLEDGE_UPLOAD,
  },
  {
    key: 'project',
    title: '创建项目',
    subtitle: '启动新项目',
    route: ROUTE_PATHS.projects,
    icon: AddIcon,
    tone: 'green',
    permission: PERMISSIONS.PROJECT_CREATE,
  },
  {
    key: 'base-chat',
    title: '企业知识问答',
    subtitle: '基于全库智能问答',
    route: ROUTE_PATHS.aiBaseChat,
    icon: ChatBubbleHelpIcon,
    tone: 'purple',
    permission: PERMISSIONS.AI_BASE_CHAT_VIEW,
  },
  {
    key: 'project-chat',
    title: '项目知识问答',
    subtitle: '针对项目智能检索',
    route: ROUTE_PATHS.aiProjectChat,
    icon: DataBaseIcon,
    tone: 'orange',
    permission: PERMISSIONS.AI_PROJECT_CHAT_VIEW,
  },
];

const visibleQuickActions = computed(() => quickActionDefinitions.filter((action) => authStore.hasActionPermission(action.permission)));
const canViewKnowledgeMenu = computed(() => authStore.hasMenuPermission(PERMISSIONS.KNOWLEDGE));
const canViewProjectMenu = computed(() => authStore.hasMenuPermission(PERMISSIONS.PROJECT));
const canViewQaAudit = computed(() => authStore.hasMenuPermission(PERMISSIONS.SYSTEM_QA_AUDIT));
const canViewReviews = computed(
  () => authStore.hasMenuPermission(PERMISSIONS.REVIEW) && authStore.hasActionPermission(PERMISSIONS.REVIEW_VIEW),
);

const knowledgeAssetDistribution = computed(() => stats.value?.knowledge_asset_distribution);
const knowledgeAssetItems = computed<DashboardKnowledgeAssetItem[]>(() => knowledgeAssetDistribution.value?.items || []);
const assetMaxCount = computed(() => Math.max(1, ...knowledgeAssetItems.value.map((item) => item.document_count)));

function assetBarWidth(item: DashboardKnowledgeAssetItem): string {
  return `${(item.document_count / assetMaxCount.value) * 100}%`;
}

function showAssetTooltip(event: MouseEvent, item: DashboardKnowledgeAssetItem): void {
  const container = assetChartWrap.value;
  if (!container) return;
  const bounds = container.getBoundingClientRect();
  const tooltipHalfWidth = 100;
  hoveredAssetItem.value = item;
  assetTooltipPosition.value = {
    left: Math.min(Math.max(event.clientX - bounds.left, tooltipHalfWidth), bounds.width - tooltipHalfWidth),
    top: Math.max(event.clientY - bounds.top - 10, 92),
  };
}

function hideAssetTooltip(): void {
  hoveredAssetItem.value = null;
}

const qaTrend = computed(() => stats.value?.qa_trend);
const qaTrendDaily = computed<DashboardQaTrendDaily[]>(() => qaTrend.value?.daily || []);
const qaTrendHasData = computed(() => (qaTrend.value?.total || 0) > 0);
const qaTrendMax = computed(() => {
  const maximum = Math.max(0, ...qaTrendDaily.value.flatMap((item) => [item.enterprise_count, item.project_count]));
  return Math.max(4, Math.ceil(maximum / 4) * 4);
});
const qaTrendYTicks = computed(() => Array.from({ length: 5 }, (_, index) => (qaTrendMax.value / 4) * (4 - index)));

function trendX(index: number): number {
  const plotWidth = TREND_CHART_WIDTH - TREND_PLOT_LEFT - TREND_PLOT_RIGHT;
  return TREND_PLOT_LEFT + (plotWidth * index) / Math.max(qaTrendDaily.value.length - 1, 1);
}

function trendY(value: number): number {
  const plotHeight = TREND_CHART_HEIGHT - TREND_PLOT_TOP - TREND_PLOT_BOTTOM;
  return TREND_PLOT_TOP + plotHeight * (1 - value / qaTrendMax.value);
}

function trendPoints(key: 'enterprise_count' | 'project_count'): string {
  return qaTrendDaily.value.map((item, index) => `${trendX(index)},${trendY(item[key])}`).join(' ');
}

function formatTrendDate(dateText: string): string {
  const [, month, day] = dateText.split('-').map(Number);
  return `${month}/${day}`;
}

function formatTrendTooltipDate(dateText: string): string {
  const [, month, day] = dateText.split('-').map(Number);
  return `${month}月${day}日`;
}

function showTrendTooltip(event: MouseEvent, item: DashboardQaTrendDaily): void {
  const container = trendChartWrap.value;
  if (!container) return;
  const bounds = container.getBoundingClientRect();
  const tooltipHalfWidth = 100;
  hoveredTrendItem.value = item;
  trendTooltipPosition.value = {
    left: Math.min(Math.max(event.clientX - bounds.left, tooltipHalfWidth), bounds.width - tooltipHalfWidth),
    top: Math.max(event.clientY - bounds.top - 10, 112),
  };
}

function hideTrendTooltip(): void {
  hoveredTrendItem.value = null;
}

function showDocumentTypeTooltip(event: MouseEvent, item: DashboardDocumentTypeStat): void {
  if (item.count <= 0) return;
  const container = donutChartWrap.value;
  if (!container) return;
  const bounds = container.getBoundingClientRect();
  const tooltipHalfWidth = 82;
  hoveredDocumentType.value = item;
  donutTooltipPosition.value = {
    left: Math.min(Math.max(event.clientX - bounds.left, tooltipHalfWidth), bounds.width - tooltipHalfWidth),
    top: Math.max(event.clientY - bounds.top - 10, 70),
  };
}

function hideDocumentTypeTooltip(): void {
  hoveredDocumentType.value = null;
}

const documentTypeStats = computed<DashboardDocumentTypeStat[]>(() => {
  /**
   * 文档类型分布完全来自后端接口，接口为空时页面展示空状态。
   */
  return stats.value?.document_type_distribution || [];
});

const hasDocumentTypeData = computed(() => documentTypeStats.value.some((item) => item.count > 0));

const donutSegments = computed(() => {
  /**
   * 将文件数量换算为 SVG 圆环线段，避免百分比四舍五入影响图形比例。
   */
  const totalCount = documentTypeStats.value.reduce((sum, item) => sum + item.count, 0) || 1;
  let offset = 0;
  return documentTypeStats.value.map((item) => {
    const percentRatio = item.count / totalCount;
    const segmentLength = Math.max(percentRatio * DONUT_CIRCUMFERENCE - DONUT_GAP_LENGTH, 0);
    const segment = {
      key: item.name,
      name: item.name,
      count: item.count,
      percentage: item.percentage,
      color: item.color,
      dasharray: `${segmentLength} ${DONUT_CIRCUMFERENCE}`,
      dashoffset: `${-offset}`,
    };
    offset += percentRatio * DONUT_CIRCUMFERENCE;
    return segment;
  });
});

async function loadData(): Promise<void> {
  /**
   * 从后端统计接口加载工作台真实数据。
   */
  loading.value = true;
  loadFailed.value = false;
  try {
    stats.value = await getDashboardStats();
  } catch (error) {
    loadFailed.value = true;
    MessagePlugin.error(error instanceof Error ? error.message : '工作台数据加载失败');
  } finally {
    loading.value = false;
  }
}

function formatMetricValue(value: number): string {
  /**
   * 使用千分位格式化指标数字，匹配原型卡片的展示密度。
   */
  return new Intl.NumberFormat('en-US').format(value);
}

function formatChineseDate(date: Date): string {
  /**
   * 格式化为“YYYY年M月D日 星期X”的中文日期。
   */
  const weekdays = ['星期日', '星期一', '星期二', '星期三', '星期四', '星期五', '星期六'];
  return `${date.getFullYear()}年${date.getMonth() + 1}月${date.getDate()}日 ${weekdays[date.getDay()]}`;
}

function openPendingReviewTasks(): void {
  /**
   * 跳转到审核中心的审核任务页签，并默认筛选待审核任务。
   */
  if (!canViewReviews.value) {
    MessagePlugin.warning('无权限访问审核中心');
    return;
  }
  router.push(withBreadcrumbContext(route, { path: ROUTE_PATHS.reviews, query: { tab: 'tasks', status: 'pending' } }));
}

function navigateTo(targetRoute: string): void {
  /**
   * 统一处理工作台入口跳转。
   */
  router.push(withBreadcrumbContext(route, targetRoute));
}

onMounted(loadData);
</script>

<template>
  <section class="dashboard-workbench" :aria-busy="loading">
    <header class="welcome-banner">
      <div class="welcome-main">
        <h1><span class="wave">👋</span> 欢迎回来，{{ userDisplayName }} <span class="wave small">👋</span></h1>
        <p>
          今天是 {{ todayText }}，您有
          <button
            v-if="canViewReviews"
            class="pending-task-link"
            type="button"
            aria-label="查看审核中心待处理任务"
            @click="openPendingReviewTasks"
          >
            {{ pendingTaskCount }}
          </button>
          <span v-else class="pending-task-count">{{ pendingTaskCount }}</span>
          个待处理任务
        </p>
      </div>
      <div class="login-meta">
        <span>上次登录时间</span>
        <strong>{{ lastLoginText }}</strong>
      </div>
    </header>

    <div class="dashboard-scroll data-scroll">
      <div class="metric-grid" aria-label="工作台核心指标">
        <article v-for="item in metricCards" :key="item.key" class="metric-card">
          <span class="metric-icon" :class="`tone-${item.tone}`">
            <component :is="item.icon" />
          </span>
          <span class="metric-copy">
            <strong>{{ formatMetricValue(item.value) }}</strong>
            <span>{{ item.title }}</span>
          </span>
        </article>
      </div>

      <div class="quick-action-grid" aria-label="常用工作入口">
        <t-button
          v-for="action in visibleQuickActions"
          :key="action.key"
          class="quick-action-card"
          :class="{ highlighted: action.key === 'project' }"
          block
          variant="outline"
          @click="navigateTo(action.route)"
        >
          <span class="action-icon" :class="`tone-${action.tone}`">
            <component :is="action.icon" />
          </span>
          <span class="action-copy">
            <strong>{{ action.title }}</strong>
            <small>{{ action.subtitle }}</small>
          </span>
        </t-button>
      </div>

      <div class="content-grid">
        <section class="dashboard-panel knowledge-assets-panel">
          <header class="panel-header">
            <h2>知识资产分布</h2>
            <t-button v-if="canViewProjectMenu" size="small" variant="text" @click="navigateTo(ROUTE_PATHS.projects)">查看详情</t-button>
          </header>
          <div v-if="loading" class="empty-state knowledge-assets-state">知识资产分布加载中</div>
          <div v-else-if="loadFailed" class="empty-state knowledge-assets-state">知识资产分布加载失败</div>
          <div
            v-else-if="knowledgeAssetItems.length"
            ref="assetChartWrap"
            class="knowledge-assets-chart"
            role="img"
            aria-label="企业公共知识和项目知识文档数量横向条形图"
            @mouseleave="hideAssetTooltip"
          >
            <div
              v-for="item in knowledgeAssetItems"
              :key="`${item.scope_type}-${item.scope_id ?? 'all'}`"
              class="asset-row"
              @mouseenter="showAssetTooltip($event, item)"
              @mousemove="showAssetTooltip($event, item)"
            >
              <span class="asset-name" :title="item.name">{{ item.name }}</span>
              <div class="asset-bar-track">
                <span
                  class="asset-bar"
                  :class="{ enterprise: item.scope_type === 'enterprise', other: item.scope_type === 'other_projects' }"
                  :style="{ width: assetBarWidth(item) }"
                ></span>
              </div>
              <strong class="asset-count">{{ formatMetricValue(item.document_count) }}</strong>
            </div>
            <div
              v-if="hoveredAssetItem"
              class="asset-tooltip"
              :style="{ left: `${assetTooltipPosition.left}px`, top: `${assetTooltipPosition.top}px` }"
              role="tooltip"
            >
              <strong>{{ hoveredAssetItem.name }}</strong>
              <span v-if="hoveredAssetItem.project_count">包含项目：{{ hoveredAssetItem.project_count }} 个</span>
              <span>知识文档：{{ formatMetricValue(hoveredAssetItem.document_count) }} 份</span>
              <span>占全部文档：{{ hoveredAssetItem.percentage.toFixed(1) }}%</span>
            </div>
          </div>
          <div v-else class="empty-state knowledge-assets-state">暂无知识资产数据</div>
        </section>

        <section class="dashboard-panel qa-trend-panel">
          <header class="panel-header">
            <h2>近 7 天 AI 问答趋势</h2>
            <t-button v-if="canViewQaAudit" size="small" variant="text" @click="navigateTo(ROUTE_PATHS.qaAudit)">查看详情</t-button>
          </header>
          <div v-if="loading" class="empty-state qa-trend-state">问答趋势加载中</div>
          <div v-else-if="loadFailed" class="empty-state qa-trend-state">问答趋势加载失败</div>
          <div v-else-if="qaTrend" class="qa-trend-body">
            <div class="qa-trend-summary">
              <span><strong>{{ formatMetricValue(qaTrend.total) }}</strong><small>近 7 天问答</small></span>
              <span><strong>{{ formatMetricValue(qaTrend.enterprise_total) }}</strong><small>企业知识问答</small></span>
              <span><strong>{{ formatMetricValue(qaTrend.project_total) }}</strong><small>项目知识问答</small></span>
            </div>
            <div class="qa-trend-legend" aria-label="问答趋势图例">
              <span><i class="enterprise"></i>企业知识问答</span>
              <span><i class="project"></i>项目知识问答</span>
            </div>
            <div ref="trendChartWrap" class="qa-trend-chart-wrap" @mouseleave="hideTrendTooltip">
              <svg
                class="qa-trend-chart"
                :viewBox="`0 0 ${TREND_CHART_WIDTH} ${TREND_CHART_HEIGHT}`"
                role="img"
                aria-label="近 7 天企业知识问答和项目知识问答趋势折线图"
              >
                <g v-for="(tick, index) in qaTrendYTicks" :key="tick" class="trend-grid">
                  <line :x1="TREND_PLOT_LEFT" :x2="TREND_CHART_WIDTH - TREND_PLOT_RIGHT" :y1="trendY(tick)" :y2="trendY(tick)" />
                  <text :x="TREND_PLOT_LEFT - 10" :y="trendY(tick) + 4">{{ tick }}</text>
                </g>
                <polyline class="trend-line enterprise" :points="trendPoints('enterprise_count')" />
                <polyline class="trend-line project" :points="trendPoints('project_count')" />
                <g v-for="(item, index) in qaTrendDaily" :key="item.date">
                  <text class="trend-x-label" :x="trendX(index)" :y="TREND_CHART_HEIGHT - 14">{{ formatTrendDate(item.date) }}</text>
                  <circle class="trend-point enterprise" :cx="trendX(index)" :cy="trendY(item.enterprise_count)" r="4" />
                  <circle class="trend-point project" :cx="trendX(index)" :cy="trendY(item.project_count)" r="4" />
                  <rect
                    class="trend-hover-area"
                    :x="trendX(index) - 26"
                    :y="TREND_PLOT_TOP"
                    width="52"
                    :height="TREND_CHART_HEIGHT - TREND_PLOT_TOP - TREND_PLOT_BOTTOM"
                    @mouseenter="showTrendTooltip($event, item)"
                    @mousemove="showTrendTooltip($event, item)"
                  />
                </g>
              </svg>
              <div
                v-if="hoveredTrendItem"
                class="qa-trend-tooltip"
                :style="{ left: `${trendTooltipPosition.left}px`, top: `${trendTooltipPosition.top}px` }"
                role="tooltip"
              >
                <strong>{{ formatTrendTooltipDate(hoveredTrendItem.date) }}</strong>
                <span><i class="enterprise"></i>企业知识问答：{{ hoveredTrendItem.enterprise_count }} 次</span>
                <span><i class="project"></i>项目知识问答：{{ hoveredTrendItem.project_count }} 次</span>
                <span class="total">合计：{{ hoveredTrendItem.total_count }} 次</span>
              </div>
              <div v-if="!qaTrendHasData" class="qa-trend-empty">近 7 天暂无问答数据</div>
            </div>
          </div>
          <div v-else class="empty-state qa-trend-state">近 7 天暂无问答数据</div>
        </section>

        <section class="dashboard-panel document-type-panel">
          <header class="panel-header">
            <h2>文档类型分布</h2>
            <t-button v-if="canViewKnowledgeMenu" size="small" variant="text" @click="navigateTo(ROUTE_PATHS.knowledge)">查看详情</t-button>
          </header>
          <div v-if="hasDocumentTypeData" class="document-type-body">
            <div ref="donutChartWrap" class="donut-chart-wrap" @mouseleave="hideDocumentTypeTooltip">
              <svg class="donut-chart" viewBox="0 0 144 144" role="img" aria-label="文档类型分布环图">
                <circle
                  class="donut-track"
                  :cx="DONUT_CENTER"
                  :cy="DONUT_CENTER"
                  :r="DONUT_RADIUS"
                  :stroke-width="DONUT_STROKE_WIDTH"
                />
                <circle
                  v-for="segment in donutSegments"
                  :key="segment.key"
                  class="donut-segment"
                  :cx="DONUT_CENTER"
                  :cy="DONUT_CENTER"
                  :r="DONUT_RADIUS"
                  :stroke="segment.color"
                  :stroke-width="DONUT_STROKE_WIDTH"
                  :stroke-dasharray="segment.dasharray"
                  :stroke-dashoffset="segment.dashoffset"
                  @mouseenter="showDocumentTypeTooltip($event, segment)"
                  @mousemove="showDocumentTypeTooltip($event, segment)"
                />
              </svg>
              <div
                v-if="hoveredDocumentType"
                class="document-type-tooltip"
                :style="{ left: `${donutTooltipPosition.left}px`, top: `${donutTooltipPosition.top}px` }"
                role="tooltip"
              >
                <strong>{{ hoveredDocumentType.name }}</strong>
                <span>{{ formatMetricValue(hoveredDocumentType.count) }} 份</span>
                <span>{{ hoveredDocumentType.percentage.toFixed(1) }}%</span>
              </div>
            </div>
            <div class="document-type-legend">
              <div v-for="item in documentTypeStats" :key="item.type" class="legend-row">
                <span class="legend-name">
                  <i :style="{ backgroundColor: item.color }"></i>
                  {{ item.name }}
                </span>
                <span class="legend-values">
                  <strong>{{ formatMetricValue(item.count) }}</strong>
                  <span>{{ item.percentage.toFixed(1) }}%</span>
                </span>
              </div>
            </div>
          </div>
          <div v-else class="empty-state document-type-empty">暂无文档类型数据</div>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.dashboard-workbench {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  padding: 28px;
  background: #f7f8fb;
}

.dashboard-scroll {
  flex: 1;
  min-height: 0;
}

.welcome-banner {
  display: flex;
  flex: 0 0 auto;
  min-height: 132px;
  align-items: center;
  justify-content: space-between;
  border-radius: 8px;
  background: #e9f8ff;
  padding: 32px;
}

.welcome-main h1 {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0;
  color: #0f172a;
  font-size: 24px;
  font-weight: 800;
  letter-spacing: 0;
}

.welcome-main p {
  margin: 14px 0 0;
  color: #475569;
  font-size: 15px;
}

.pending-task-link {
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: #2563eb;
  cursor: pointer;
  font: inherit;
  font-weight: 700;
  line-height: inherit;
  padding: 0 2px;
}

.pending-task-link:hover {
  color: #1d4ed8;
  text-decoration: underline;
  text-underline-offset: 3px;
}

.pending-task-link:focus-visible {
  outline: 2px solid rgba(37, 99, 235, 0.35);
  outline-offset: 2px;
}

.wave {
  font-size: 28px;
  line-height: 1;
}

.wave.small {
  font-size: 18px;
}

.login-meta {
  display: flex;
  min-width: 132px;
  flex-direction: column;
  align-items: flex-end;
  color: #64748b;
  font-size: 14px;
}

.login-meta strong {
  margin-top: 6px;
  color: #1f2937;
  font-size: 20px;
  font-weight: 500;
}

.metric-grid,
.quick-action-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 24px;
  margin-top: 24px;
}

.metric-card,
.quick-action-card,
.dashboard-panel {
  border: 1px solid #eef2f7;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.03);
}

.metric-card {
  display: flex;
  min-height: 128px;
  align-items: center;
  gap: 18px;
  padding: 24px;
}

.metric-icon,
.action-icon {
  display: grid;
  flex: 0 0 auto;
  place-items: center;
  border-radius: 8px;
}

.metric-icon {
  width: 48px;
  height: 48px;
  font-size: 24px;
}

.metric-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  flex-direction: column;
  justify-content: center;
  text-align: center;
}

.metric-card strong {
  display: block;
  color: #0f172a;
  font-size: 32px;
  font-weight: 800;
  line-height: 1.1;
}

.metric-copy > span {
  display: block;
  margin-top: 8px;
  color: #475569;
  font-size: 14px;
}

.quick-action-card {
  display: flex;
  height: auto;
  min-height: 104px;
  align-items: center;
  justify-content: flex-start;
  gap: 14px;
  padding: 24px;
  text-align: left;
  transition:
    transform 0.16s ease,
    box-shadow 0.16s ease;
}

.quick-action-card :deep(.t-button__text) {
  display: flex;
  width: 100%;
  min-width: 0;
  align-items: center;
  gap: 14px;
}

.quick-action-card:hover {
  box-shadow: 0 14px 28px rgba(15, 23, 42, 0.08);
  transform: translateY(-1px);
}

.quick-action-card.highlighted {
  background: #ecfff4;
}

.action-icon {
  width: 40px;
  height: 40px;
  font-size: 22px;
}

.action-copy {
  display: flex;
  flex: 1;
  min-width: 0;
  align-items: center;
  flex-direction: column;
  text-align: center;
}

.action-copy strong {
  max-width: 100%;
  overflow: hidden;
  color: #111827;
  font-size: 16px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.action-copy small {
  max-width: 100%;
  overflow: hidden;
  margin-top: 4px;
  color: #64748b;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.content-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) minmax(340px, 1fr);
  gap: 24px;
  margin-top: 24px;
}

.dashboard-panel {
  min-height: 588px;
  padding: 26px 24px 24px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 28px;
}

.panel-header h2 {
  margin: 0;
  color: #0f172a;
  font-size: 18px;
  font-weight: 800;
  letter-spacing: 0;
}

.empty-state {
  display: grid;
  min-height: 344px;
  place-items: center;
  border-radius: 8px;
  color: #94a3b8;
  font-size: 14px;
}

.document-type-empty {
  min-height: 344px;
}

.knowledge-assets-state {
  min-height: 390px;
}

.knowledge-assets-chart {
  position: relative;
  display: flex;
  min-width: 0;
  padding-top: 12px;
  flex-direction: column;
  gap: 22px;
}

.asset-row {
  display: grid;
  min-width: 0;
  align-items: center;
  grid-template-columns: minmax(86px, 118px) minmax(80px, 1fr) minmax(54px, 72px);
  gap: 10px;
}

.asset-name {
  overflow: hidden;
  color: #334155;
  font-size: 13px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-bar-track {
  height: 18px;
  overflow: hidden;
  border-radius: 4px;
  background: #f1f5f9;
}

.asset-bar {
  display: block;
  min-width: 2px;
  height: 100%;
  border-radius: 4px;
  background: #7b8da8;
}

.asset-bar.enterprise {
  background: #4ea3f7;
}

.asset-bar.other {
  background: #a8b3c3;
}

.asset-count {
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  text-align: right;
  white-space: nowrap;
}

.asset-tooltip {
  position: absolute;
  z-index: 4;
  display: flex;
  min-width: 190px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(15 23 42 / 14%);
  color: #475569;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  line-height: 1.4;
  pointer-events: none;
  transform: translate(-50%, -100%);
  white-space: nowrap;
}

.asset-tooltip strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
}

.qa-trend-body {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.qa-trend-summary {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
  margin-bottom: 18px;
}

.qa-trend-summary span {
  min-width: 0;
  text-align: center;
}

.qa-trend-summary strong,
.qa-trend-summary small {
  display: block;
}

.qa-trend-summary strong {
  color: #0f172a;
  font-size: 20px;
  line-height: 1.3;
}

.qa-trend-summary small {
  overflow: hidden;
  margin-top: 3px;
  color: #64748b;
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qa-trend-legend {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 24px;
  color: #475569;
  font-size: 13px;
}

.qa-trend-legend span {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.qa-trend-legend i {
  width: 18px;
  height: 3px;
  border-radius: 2px;
}

.qa-trend-legend .enterprise {
  background: #4ea3f7;
}

.qa-trend-legend .project {
  background: #b678f4;
}

.qa-trend-chart-wrap {
  position: relative;
  width: 100%;
  min-width: 0;
  margin-top: 12px;
}

.qa-trend-chart {
  display: block;
  width: 100%;
  max-height: 300px;
  overflow: visible;
}

.trend-grid line {
  stroke: #e8edf3;
  stroke-width: 1;
}

.trend-grid text {
  fill: #94a3b8;
  font-size: 11px;
  text-anchor: end;
}

.trend-line {
  fill: none;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 3;
}

.trend-line.enterprise,
.trend-point.enterprise {
  stroke: #4ea3f7;
}

.trend-line.project,
.trend-point.project {
  stroke: #b678f4;
}

.trend-point {
  fill: #fff;
  stroke-width: 3;
}

.trend-hover-area {
  fill: transparent;
  cursor: default;
  pointer-events: all;
}

.trend-x-label {
  fill: #64748b;
  font-size: 11px;
  text-anchor: middle;
}

.qa-trend-tooltip {
  position: absolute;
  z-index: 2;
  display: flex;
  width: 200px;
  box-sizing: border-box;
  flex-direction: column;
  gap: 7px;
  padding: 12px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.98);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.14);
  color: #334155;
  font-size: 12px;
  line-height: 1.4;
  pointer-events: none;
  transform: translate(-50%, -100%);
}

.qa-trend-tooltip strong {
  color: #0f172a;
  font-size: 13px;
}

.qa-trend-tooltip span {
  display: flex;
  align-items: center;
  gap: 7px;
  white-space: nowrap;
}

.qa-trend-tooltip i {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  border-radius: 50%;
}

.qa-trend-tooltip i.enterprise {
  background: #4ea3f7;
}

.qa-trend-tooltip i.project {
  background: #b678f4;
}

.qa-trend-tooltip .total {
  padding-top: 6px;
  border-top: 1px solid #eef2f7;
  color: #0f172a;
  font-weight: 600;
}

.qa-trend-empty {
  position: absolute;
  inset: 40% 0 auto;
  color: #94a3b8;
  font-size: 14px;
  text-align: center;
  pointer-events: none;
}

.qa-trend-state {
  min-height: 390px;
}

.document-type-body {
  display: flex;
  min-height: 0;
  flex-direction: column;
  justify-content: flex-start;
  padding-top: 12px;
}

.donut-chart-wrap {
  position: relative;
  width: 220px;
  height: 220px;
  margin: 8px auto 20px;
}

.donut-chart {
  display: block;
  width: 100%;
  height: 100%;
}

.donut-track {
  fill: none;
  stroke: #eef2f7;
}

.donut-segment {
  fill: none;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 72px 72px;
  cursor: default;
}

.document-type-tooltip {
  position: absolute;
  z-index: 3;
  display: flex;
  min-width: 138px;
  padding: 10px 12px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
  box-shadow: 0 8px 24px rgb(15 23 42 / 14%);
  color: #475569;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  line-height: 1.4;
  pointer-events: none;
  transform: translate(-50%, -100%);
  white-space: nowrap;
}

.document-type-tooltip strong {
  color: #0f172a;
  font-size: 14px;
  font-weight: 600;
}

.document-type-legend {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.legend-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  color: #334155;
  font-size: 14px;
}

.legend-name {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.legend-name i {
  width: 12px;
  height: 12px;
  border-radius: 999px;
}

.legend-values {
  display: grid;
  min-width: 116px;
  grid-template-columns: minmax(52px, 1fr) 54px;
  gap: 10px;
  text-align: right;
  white-space: nowrap;
}

.legend-row strong {
  color: #1f2937;
  font-weight: 500;
}

.tone-blue {
  background: #dcebff;
  color: #2563eb;
}

.tone-purple {
  background: #f1ddff;
  color: #9333ea;
}

.tone-orange {
  background: #ffead1;
  color: #ea580c;
}

.tone-pink {
  background: #ffe0ef;
  color: #db2777;
}

.tone-green {
  background: #dffbea;
  color: #16a34a;
}

@media (max-width: 1360px) {
  .dashboard-workbench {
    padding: 24px;
  }

  .metric-grid,
  .quick-action-grid,
  .content-grid {
    gap: 18px;
  }

  .content-grid {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }

  .document-type-panel {
    grid-column: 1 / -1;
  }
}
</style>
