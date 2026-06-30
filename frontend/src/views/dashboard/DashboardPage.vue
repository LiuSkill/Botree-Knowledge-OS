<!--
  Dashboard Page

  负责：
  1. 按首页工作台原型展示欢迎区、指标卡片和快捷入口
  2. 展示最近上传文档、最近 AI 问答和知识分类统计
  3. 只展示后端工作台接口返回的真实业务数据
-->
<script setup lang="ts">
import {
  AddIcon,
  CatalogIcon,
  ChatBubbleHelpIcon,
  CloudUploadIcon,
  DataBaseIcon,
  FileExcelFilledIcon,
  FilePdfFilledIcon,
  FilePowerpointFilledIcon,
  FileWordFilledIcon,
  FlashlightIcon,
  FolderAddIcon,
  FolderIcon,
} from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, onMounted, ref, type Component } from 'vue';
import { useRouter } from 'vue-router';

import { getDashboardStats } from '@/api/system';
import { PERMISSIONS } from '@/constants/permissions';
import { ROUTE_PATHS } from '@/shared/constants/routes';
import { useAuthStore } from '@/stores/auth';
import type { DashboardAiQuestion, DashboardCategoryStat, DashboardDocumentSummary, DashboardStats } from '@/types/api';
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

interface DocumentDisplayItem {
  id: number;
  name: string;
  time: string;
  icon: Component;
  tone: ToneName | 'red';
}

const router = useRouter();
const authStore = useAuthStore();
const stats = ref<DashboardStats | null>(null);
const loading = ref(false);

const DONUT_RADIUS = 48;
const DONUT_CENTER = 72;
const DONUT_STROKE_WIDTH = 18;
const DONUT_GAP_LENGTH = 7;
const DONUT_CIRCUMFERENCE = 2 * Math.PI * DONUT_RADIUS;

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
const canViewKnowledge = computed(() => authStore.hasActionPermission(PERMISSIONS.KNOWLEDGE_VIEW));
const canViewBaseChat = computed(() => authStore.hasActionPermission(PERMISSIONS.AI_BASE_CHAT_VIEW));
const canViewProjectChat = computed(() => authStore.hasActionPermission(PERMISSIONS.AI_PROJECT_CHAT_VIEW));

const recentDocuments = computed<DocumentDisplayItem[]>(() => {
  /**
   * 将后端最近文档转换为首页列表样式所需字段。
   */
  return (stats.value?.recent_documents || []).slice(0, 4).map((document) => {
    const fileMeta = getFileVisualMeta(document);
    return {
      id: document.id,
      name: document.file_name,
      time: formatDateTime(document.created_at),
      icon: fileMeta.icon,
      tone: fileMeta.tone,
    };
  });
});

const recentQuestions = computed<DashboardAiQuestion[]>(() => {
  /**
   * 最近问答完全来自后端接口，不做前端样例补齐。
   */
  return (stats.value?.recent_ai_questions || []).slice(0, 4);
});
const visibleRecentQuestions = computed(() =>
  recentQuestions.value.filter((question) =>
    question.chat_type === 'project_chat' ? canViewProjectChat.value : canViewBaseChat.value,
  ),
);

const categoryStats = computed<DashboardCategoryStat[]>(() => {
  /**
   * 分类统计完全来自后端接口，接口为空时页面展示空状态。
   */
  return stats.value?.knowledge_category_stats?.filter((item) => item.percent > 0) || [];
});

const donutSegments = computed(() => {
  /**
   * 将分类百分比换算为 SVG 圆环线段，使用固定缺口模拟原型分段效果。
   */
  const totalPercent = categoryStats.value.reduce((sum, item) => sum + item.percent, 0) || 100;
  let offset = 0;
  return categoryStats.value.map((item) => {
    const percentRatio = item.percent / totalPercent;
    const segmentLength = Math.max(percentRatio * DONUT_CIRCUMFERENCE - DONUT_GAP_LENGTH, 0);
    const segment = {
      key: item.name,
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
  try {
    stats.value = await getDashboardStats();
  } catch (error) {
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

function getFileVisualMeta(document: DashboardDocumentSummary): { icon: Component; tone: DocumentDisplayItem['tone'] } {
  /**
   * 根据文件类型和扩展名选择文档图标配色。
   */
  const fileMark = `${document.file_type || ''} ${document.file_name}`.toLowerCase();
  if (fileMark.includes('pdf')) return { icon: FilePdfFilledIcon, tone: 'red' };
  if (fileMark.includes('doc') || fileMark.includes('word')) return { icon: FileWordFilledIcon, tone: 'blue' };
  if (fileMark.includes('xls') || fileMark.includes('csv') || fileMark.includes('excel')) {
    return { icon: FileExcelFilledIcon, tone: 'green' };
  }
  if (fileMark.includes('ppt') || fileMark.includes('powerpoint')) {
    return { icon: FilePowerpointFilledIcon, tone: 'orange' };
  }
  return { icon: FolderAddIcon, tone: 'purple' };
}

function openDocument(documentId: number): void {
  /**
   * 打开文档详情。
   */
  if (!canViewKnowledge.value) {
    MessagePlugin.warning('无权限查看知识资料');
    return;
  }
  router.push(ROUTE_PATHS.documentDetail.replace(':id', String(documentId)));
}

function openQuestion(question: DashboardAiQuestion): void {
  /**
   * 根据问答类型进入对应 AI 问答入口。
   */
  if (question.chat_type === 'project_chat' && !canViewProjectChat.value) {
    MessagePlugin.warning('无权限访问项目问答');
    return;
  }
  if (question.chat_type === 'base_chat' && !canViewBaseChat.value) {
    MessagePlugin.warning('无权限访问基础问答');
    return;
  }
  router.push(question.chat_type === 'project_chat' ? ROUTE_PATHS.aiProjectChat : ROUTE_PATHS.aiBaseChat);
}

function navigateTo(route: string): void {
  /**
   * 统一处理工作台入口跳转。
   */
  router.push(route);
}

onMounted(loadData);
</script>

<template>
  <section class="dashboard-workbench" :aria-busy="loading">
    <header class="welcome-banner">
      <div class="welcome-main">
        <h1><span class="wave">👋</span> 欢迎回来，{{ userDisplayName }} <span class="wave small">👋</span></h1>
        <p>今天是 {{ todayText }}，您有 {{ pendingTaskCount }} 个待处理任务</p>
      </div>
      <div class="login-meta">
        <span>上次登录时间</span>
        <strong>{{ lastLoginText }}</strong>
      </div>
    </header>

    <div class="dashboard-scroll data-scroll">
      <div class="metric-grid" aria-label="工作台核心指标">
        <article v-for="item in metricCards" :key="item.key" class="metric-card">
          <div class="metric-top">
            <span class="metric-icon" :class="`tone-${item.tone}`">
              <component :is="item.icon" />
            </span>
          </div>
          <strong>{{ formatMetricValue(item.value) }}</strong>
          <span>{{ item.title }}</span>
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
        <section class="dashboard-panel recent-documents-panel">
          <header class="panel-header">
            <h2>最近上传文档</h2>
            <t-button v-if="canViewKnowledge" size="small" variant="text" @click="navigateTo(ROUTE_PATHS.knowledge)">查看全部</t-button>
          </header>
          <div v-if="recentDocuments.length && canViewKnowledge" class="document-list">
            <t-button
              v-for="document in recentDocuments"
              :key="`${document.name}-${document.time}`"
              class="document-row"
              block
              variant="text"
              @click="openDocument(document.id)"
            >
              <span class="document-icon" :class="`tone-${document.tone}`">
                <component :is="document.icon" />
              </span>
              <span class="document-copy">
                <strong>{{ document.name }}</strong>
                <small>{{ document.time }}</small>
              </span>
            </t-button>
          </div>
          <div v-else class="empty-state">暂无上传文档</div>
        </section>

        <section class="dashboard-panel recent-questions-panel">
          <header class="panel-header">
            <h2>最近 AI 问答</h2>
            <t-button v-if="canViewBaseChat" size="small" variant="text" @click="navigateTo(ROUTE_PATHS.aiBaseChat)">查看全部</t-button>
          </header>
          <div v-if="visibleRecentQuestions.length" class="question-list">
            <t-button
              v-for="question in visibleRecentQuestions"
              :key="`${question.id}-${question.question}`"
              class="question-card"
              block
              variant="outline"
              @click="openQuestion(question)"
            >
              <strong><span>问：</span>{{ question.question }}</strong>
              <small>{{ formatDateTime(question.created_at) }}</small>
            </t-button>
          </div>
          <div v-else class="empty-state">暂无 AI 问答记录</div>
        </section>

        <section class="dashboard-panel category-panel">
          <header class="panel-header">
            <h2>知识分类统计</h2>
            <t-button v-if="canViewKnowledge" size="small" variant="text" @click="navigateTo(ROUTE_PATHS.knowledge)">查看全部</t-button>
          </header>
          <div v-if="categoryStats.length" class="category-body">
            <svg class="donut-chart" viewBox="0 0 144 144" role="img" aria-label="知识分类统计环图">
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
              />
            </svg>
            <div class="category-legend">
              <div v-for="item in categoryStats" :key="item.name" class="legend-row">
                <span class="legend-name">
                  <i :style="{ backgroundColor: item.color }"></i>
                  {{ item.name }}
                </span>
                <strong>{{ item.percent }}%</strong>
              </div>
            </div>
          </div>
          <div v-else class="empty-state category-empty">暂无知识分类数据</div>
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
  min-height: 172px;
  padding: 24px;
}

.metric-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 18px;
}

.metric-icon,
.action-icon,
.document-icon {
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

.metric-card strong {
  display: block;
  color: #0f172a;
  font-size: 32px;
  font-weight: 800;
  line-height: 1.1;
}

.metric-card > span:last-child {
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
  min-width: 0;
  flex-direction: column;
}

.action-copy strong {
  color: #111827;
  font-size: 16px;
  font-weight: 800;
}

.action-copy small {
  margin-top: 4px;
  color: #64748b;
  font-size: 13px;
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

.document-list {
  display: flex;
  flex-direction: column;
  gap: 28px;
}

.empty-state {
  display: grid;
  min-height: 344px;
  place-items: center;
  border: 1px dashed #dbe2eb;
  border-radius: 8px;
  color: #94a3b8;
  font-size: 14px;
}

.category-empty {
  min-height: 466px;
}

.document-row {
  display: flex;
  width: 100%;
  height: auto;
  min-height: 48px;
  align-items: center;
  justify-content: flex-start;
  gap: 12px;
  padding: 0 12px;
  text-align: left;
}

.document-row :deep(.t-button__text) {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 12px;
}

.document-icon {
  width: 40px;
  height: 40px;
  font-size: 22px;
}

.document-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
}

.document-copy strong {
  overflow: hidden;
  color: #1f2937;
  font-size: 14px;
  font-weight: 500;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-copy small,
.question-card small {
  color: #64748b;
  font-size: 13px;
}

.question-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.question-card {
  display: flex;
  height: auto;
  min-height: 110px;
  width: 100%;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
  border-radius: 8px;
  color: #1f2937;
  padding: 16px;
  text-align: left;
}

.question-card :deep(.t-button__text) {
  display: flex;
  width: 100%;
  flex-direction: column;
  align-items: flex-start;
  justify-content: center;
}

.question-card span {
  color: #475569;
  font-size: 14px;
}

.question-card strong {
  margin: 8px 0 14px;
  color: #111827;
  font-size: 14px;
  font-weight: 500;
  line-height: 1.5;
}

.category-body {
  display: flex;
  min-height: 466px;
  flex-direction: column;
  justify-content: center;
}

.donut-chart {
  display: block;
  width: 250px;
  height: 250px;
  margin: 12px auto 36px;
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
}

.category-legend {
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

.tone-red {
  background: #eaf3ff;
  color: #ef1d26;
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

  .category-panel {
    grid-column: 1 / -1;
  }
}
</style>
