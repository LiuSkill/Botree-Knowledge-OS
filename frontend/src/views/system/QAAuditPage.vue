<!--
  QA Audit Page

  负责：
  1. 使用 TDesign 组件展示用户会话记录和问答详情
  2. 支持按用户、项目、时间和反馈状态筛选
  3. 通过服务端分页控制审计数据加载规模
-->
<script setup lang="ts">
import { FileSearchIcon, RefreshIcon } from 'tdesign-icons-vue-next';
import { computed, onMounted, ref } from 'vue';

import { listProjects } from '@/api/projects';
import { listQAAudits, listQAAuditSessions } from '@/api/system';
import { listUsers } from '@/api/users';
import botreeLogo from '@/assets/botree-logo.png';
import AgentTracePanel from '@/components/AgentTracePanel.vue';
import ChatRichContent from '@/components/ChatRichContent.vue';
import CitationList from '@/components/CitationList.vue';
import TableActionButton from '@/components/TableActionButton.vue';
import UserAvatar from '@/components/UserAvatar.vue';
import type {
  AgentTraceStep,
  PageResult,
  ProjectInfo,
  QAAuditDetail,
  QAAuditFeedbackFilter,
  QAAuditFilters,
  QAAuditSession,
  UserInfo,
} from '@/types/api';
import { formatDateTime } from '@/utils/format';

type AuditTab = 'sessions' | 'details';
type DetailDrawerTab = 'citations' | 'trace';
type TagTheme = 'default' | 'primary' | 'success' | 'warning' | 'danger';

interface PaginationInfo {
  current: number;
  pageSize: number;
}

const DEFAULT_PAGE_SIZE = 10;
const PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

const activeTab = ref<AuditTab>('sessions');
const users = ref<UserInfo[]>([]);
const projects = ref<ProjectInfo[]>([]);
const selectedUserId = ref<number | null>(null);
const selectedProjectId = ref<number | null>(null);
const dateRange = ref<string[]>([]);
const feedbackStatus = ref<QAAuditFeedbackFilter | ''>('');

const sessionPage = ref(1);
const sessionPageSize = ref(DEFAULT_PAGE_SIZE);
const detailPage = ref(1);
const detailPageSize = ref(DEFAULT_PAGE_SIZE);
const sessionResult = ref<PageResult<QAAuditSession>>(createEmptyPageResult<QAAuditSession>());
const detailResult = ref<PageResult<QAAuditDetail>>(createEmptyPageResult<QAAuditDetail>());
const sessionLoading = ref(false);
const detailLoading = ref(false);
const optionLoading = ref(false);
const selectedDetail = ref<QAAuditDetail | null>(null);
const detailDrawerVisible = ref(false);
const detailDrawerTab = ref<DetailDrawerTab>('citations');

const sessionColumns = [
  { colKey: 'user', title: '用户', width: 120 },
  { colKey: 'project', title: '项目', width: 150 },
  { colKey: 'title', title: '会话', width: 180, ellipsis: true },
  { colKey: 'chat_type', title: '类型', width: 110 },
  { colKey: 'question_count', title: '问题数', width: 80, align: 'center' },
  { colKey: 'answer_count', title: '回答数', width: 80, align: 'center' },
  { colKey: 'citation_count', title: '引用数', width: 80, align: 'center' },
  { colKey: 'latest_question', title: '最近问题', minWidth: 240 },
  { colKey: 'latest_qa_at', title: '最近回答时间', width: 150 },
];

const detailColumns = [
  { colKey: 'user', title: '用户', width: 120 },
  { colKey: 'project', title: '项目', width: 150 },
  { colKey: 'question', title: '问题', minWidth: 240 },
  { colKey: 'feedback_status', title: '反馈', width: 100 },
  { colKey: 'citation_count', title: '引用数', width: 80, align: 'center' },
  { colKey: 'session_title', title: '会话', width: 180, ellipsis: true },
  { colKey: 'retrievers', title: '检索器', width: 160 },
  { colKey: 'answered_at', title: '回答时间', width: 150 },
  { colKey: 'operation', title: '操作', width: 72, fixed: 'right' },
];

const selectedDetailTrace = computed<AgentTraceStep[]>(() => parseAgentTrace(selectedDetail.value?.agent_trace_json));
const selectedDetailCitations = computed(() => selectedDetail.value?.citations || []);

function createEmptyPageResult<T>(): PageResult<T> {
  return {
    items: [],
    total: 0,
    page: 1,
    page_size: DEFAULT_PAGE_SIZE,
  };
}

function buildBaseFilters(page: number, pageSize: number): QAAuditFilters {
  const filters: QAAuditFilters = {
    page,
    page_size: pageSize,
  };
  if (selectedUserId.value) filters.user_id = selectedUserId.value;
  if (selectedProjectId.value) filters.project_id = selectedProjectId.value;
  if (dateRange.value[0]) filters.started_at = `${dateRange.value[0]}T00:00:00`;
  if (dateRange.value[1]) filters.ended_at = `${dateRange.value[1]}T23:59:59`;
  return filters;
}

function buildDetailFilters(): QAAuditFilters {
  const filters = buildBaseFilters(detailPage.value, detailPageSize.value);
  if (feedbackStatus.value) {
    filters.feedback_status = feedbackStatus.value;
  }
  return filters;
}

async function loadOptions(): Promise<void> {
  optionLoading.value = true;
  try {
    const [userResult, fetchedProjects] = await Promise.all([listUsers({ page: 1, page_size: 100 }), listProjects()]);
    users.value = userResult.items;
    projects.value = fetchedProjects;
  } finally {
    optionLoading.value = false;
  }
}

async function loadSessions(): Promise<void> {
  sessionLoading.value = true;
  try {
    const result = await listQAAuditSessions(buildBaseFilters(sessionPage.value, sessionPageSize.value));
    sessionResult.value = result;
    sessionPage.value = result.page;
    sessionPageSize.value = result.page_size;
  } finally {
    sessionLoading.value = false;
  }
}

async function loadDetails(): Promise<void> {
  detailLoading.value = true;
  try {
    const result = await listQAAudits(buildDetailFilters());
    detailResult.value = result;
    detailPage.value = result.page;
    detailPageSize.value = result.page_size;
  } finally {
    detailLoading.value = false;
  }
}

async function loadActiveTab(): Promise<void> {
  if (activeTab.value === 'sessions') {
    await loadSessions();
    return;
  }
  await loadDetails();
}

function resetPages(): void {
  sessionPage.value = 1;
  detailPage.value = 1;
}

function handleFilterChange(): void {
  resetPages();
  void loadActiveTab();
}

function handleFeedbackChange(): void {
  detailPage.value = 1;
  if (activeTab.value === 'details') {
    void loadDetails();
  }
}

function handleTabChange(value: unknown): void {
  activeTab.value = value === 'details' ? 'details' : 'sessions';
  if (activeTab.value === 'sessions') {
    sessionPage.value = 1;
  } else {
    detailPage.value = 1;
  }
  void loadActiveTab();
}

function clearFilters(): void {
  selectedUserId.value = null;
  selectedProjectId.value = null;
  dateRange.value = [];
  feedbackStatus.value = '';
  resetPages();
  void loadActiveTab();
}

function handleSessionPaginationChange(pageInfo: PaginationInfo): void {
  sessionPage.value = pageInfo.current;
  sessionPageSize.value = pageInfo.pageSize;
  void loadSessions();
}

function handleDetailPaginationChange(pageInfo: PaginationInfo): void {
  detailPage.value = pageInfo.current;
  detailPageSize.value = pageInfo.pageSize;
  void loadDetails();
}

function openDetailDrawer(row: QAAuditDetail): void {
  selectedDetail.value = row;
  detailDrawerTab.value = 'citations';
  detailDrawerVisible.value = true;
}

function closeDetailDrawer(): void {
  detailDrawerVisible.value = false;
}

function handleDrawerTabChange(value: unknown): void {
  detailDrawerTab.value = value === 'trace' ? 'trace' : 'citations';
}

function parseAgentTrace(rawTrace?: string | null): AgentTraceStep[] {
  if (!rawTrace) return [];
  try {
    const parsed = JSON.parse(rawTrace);
    return Array.isArray(parsed) ? (parsed as AgentTraceStep[]) : [];
  } catch {
    return [];
  }
}

function normalizeMarkdownDisplay(content: string): string {
  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const normalized: string[] = [];
  let blankCount = 0;
  let inCodeFence = false;
  let codeFence = '';

  for (const line of lines) {
    const trimmedLine = line.trim();
    const fenceMatch = trimmedLine.match(/^(```|~~~)/);

    if (fenceMatch) {
      normalized.push(line);
      blankCount = 0;
      if (!inCodeFence) {
        inCodeFence = true;
        codeFence = fenceMatch[1];
      } else if (trimmedLine.startsWith(codeFence)) {
        inCodeFence = false;
        codeFence = '';
      }
      continue;
    }

    if (inCodeFence) {
      normalized.push(line);
      continue;
    }

    if (!trimmedLine) {
      blankCount += 1;
      if (blankCount <= 1) {
        normalized.push('');
      }
      continue;
    }

    blankCount = 0;
    normalized.push(line.replace(/[ \t]+$/u, ''));
  }

  return normalized.join('\n').trim();
}

function userOptionLabel(user: UserInfo): string {
  return `${user.real_name || user.username}（${user.username}）`;
}

function projectOptionLabel(project: ProjectInfo): string {
  return `${project.name}（${project.code}）`;
}

function chatTypeLabel(chatType: QAAuditSession['chat_type'] | QAAuditDetail['chat_type']): string {
  return chatType === 'project_chat' ? '项目问答' : '基础问答';
}

function chatTypeTheme(chatType: QAAuditSession['chat_type'] | QAAuditDetail['chat_type']): TagTheme {
  return chatType === 'project_chat' ? 'primary' : 'success';
}

function feedbackLabel(status?: QAAuditDetail['feedback_status']): string {
  if (status === 'like') return '点赞';
  if (status === 'dislike') return '点踩';
  return '未反馈';
}

function feedbackTheme(status?: QAAuditDetail['feedback_status']): TagTheme {
  if (status === 'like') return 'success';
  if (status === 'dislike') return 'danger';
  return 'default';
}

function userLabel(item: QAAuditSession | QAAuditDetail): string {
  return item.real_name || item.username;
}

function projectLabel(item: QAAuditSession | QAAuditDetail): string {
  return item.project_name || item.project_code || '-';
}

function retrieverLabel(retrievers: string[]): string {
  return retrievers.length ? retrievers.join('、') : '-';
}

function durationLabel(elapsedMs?: number | null): string {
  return elapsedMs === null || elapsedMs === undefined ? '-' : `${elapsedMs} ms`;
}

onMounted(async () => {
  await loadOptions();
  await loadSessions();
});
</script>

<template>
  <div class="system-card scroll-card">
    <t-form class="audit-filter-form" layout="inline" label-align="left" label-width="auto">
      <t-form-item label="用户">
        <t-select
          v-model="selectedUserId"
          class="audit-select"
          clearable
          filterable
          :loading="optionLoading"
          placeholder="全部用户"
          @change="handleFilterChange"
        >
          <t-option v-for="user in users" :key="user.id" :value="user.id" :label="userOptionLabel(user)" />
        </t-select>
      </t-form-item>
      <t-form-item label="项目">
        <t-select
          v-model="selectedProjectId"
          class="audit-select"
          clearable
          filterable
          :loading="optionLoading"
          placeholder="全部项目"
          @change="handleFilterChange"
        >
          <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="projectOptionLabel(project)" />
        </t-select>
      </t-form-item>
      <t-form-item label="问答时间">
        <t-date-range-picker
          v-model="dateRange"
          class="audit-date-range"
          clearable
          value-type="YYYY-MM-DD"
          format="YYYY-MM-DD"
          separator="至"
          :placeholder="['开始日期', '结束日期']"
          @change="handleFilterChange"
        />
      </t-form-item>
      <t-form-item v-if="activeTab === 'details'" label="反馈">
        <t-select v-model="feedbackStatus" class="feedback-select" placeholder="全部反馈" @change="handleFeedbackChange">
          <t-option label="全部反馈" value="" />
          <t-option label="点赞" value="like" />
          <t-option label="点踩" value="dislike" />
          <t-option label="未反馈" value="none" />
        </t-select>
      </t-form-item>
      <t-form-item class="audit-filter-action">
        <t-button @click="clearFilters">重置</t-button>
      </t-form-item>
    </t-form>

    <t-tabs :value="activeTab" @change="handleTabChange">
      <t-tab-panel value="sessions" label="用户会话记录" />
      <t-tab-panel value="details" label="问答详情" />
    </t-tabs>

    <div class="system-section-head">
      <div class="system-section-title">
        <h2>{{ activeTab === 'sessions' ? '用户会话记录' : '问答详情' }}</h2>
        <span>共 {{ activeTab === 'sessions' ? sessionResult.total : detailResult.total }} 条数据</span>
      </div>
      <t-button theme="default" variant="outline" @click="loadActiveTab">
        <template #icon><RefreshIcon /></template>
        刷新
      </t-button>
    </div>

    <section v-if="activeTab === 'sessions'" class="audit-table-section">
      <div class="audit-table-scroll">
        <t-table
          row-key="id"
          bordered
          table-layout="fixed"
          vertical-align="top"
          :data="sessionResult.items"
          :columns="sessionColumns"
          :loading="sessionLoading"
          empty="暂无匹配的会话记录"
        >
          <template #latest_qa_at="{ row }">
            {{ formatDateTime(row.latest_qa_at) }}
          </template>
          <template #user="{ row }">
            {{ userLabel(row) }}
          </template>
          <template #project="{ row }">
            {{ projectLabel(row) }}
          </template>
          <template #chat_type="{ row }">
            <t-tag :theme="chatTypeTheme(row.chat_type)" variant="light">{{ chatTypeLabel(row.chat_type) }}</t-tag>
          </template>
          <template #latest_question="{ row }">
            <div class="audit-summary-text">{{ row.latest_question || '-' }}</div>
          </template>
        </t-table>
      </div>
      <div class="audit-pagination">
        <t-pagination
          :current="sessionPage"
          :page-size="sessionPageSize"
          :total="sessionResult.total"
          :page-size-options="PAGE_SIZE_OPTIONS"
          show-jumper
          @change="handleSessionPaginationChange"
        />
      </div>
    </section>

    <section v-else class="audit-table-section">
      <div class="audit-table-scroll">
        <t-table
          row-key="id"
          bordered
          table-layout="fixed"
          vertical-align="top"
          :data="detailResult.items"
          :columns="detailColumns"
          :loading="detailLoading"
          empty="暂无匹配的问答详情"
        >
          <template #answered_at="{ row }">
            {{ formatDateTime(row.answered_at || row.created_at) }}
          </template>
          <template #user="{ row }">
            {{ userLabel(row) }}
          </template>
          <template #project="{ row }">
            {{ projectLabel(row) }}
          </template>
          <template #question="{ row }">
            <div class="audit-summary-text">{{ row.question || '-' }}</div>
          </template>
          <template #feedback_status="{ row }">
            <t-tag :theme="feedbackTheme(row.feedback_status)" variant="light">{{ feedbackLabel(row.feedback_status) }}</t-tag>
          </template>
          <template #retrievers="{ row }">
            {{ retrieverLabel(row.retrievers) }}
          </template>
          <template #operation="{ row }">
            <TableActionButton label="查看详情" @click="openDetailDrawer(row)">
              <FileSearchIcon />
            </TableActionButton>
          </template>
        </t-table>
      </div>
      <div class="audit-pagination">
        <t-pagination
          :current="detailPage"
          :page-size="detailPageSize"
          :total="detailResult.total"
          :page-size-options="PAGE_SIZE_OPTIONS"
          show-jumper
          @change="handleDetailPaginationChange"
        />
      </div>
    </section>

    <t-drawer
      v-model:visible="detailDrawerVisible"
      class="qa-detail-drawer drawer-scroll"
      header="问答详情"
      placement="right"
      size="min(760px, 96vw)"
      :footer="false"
      @close="closeDetailDrawer"
    >
      <div v-if="selectedDetail" class="qa-detail-drawer-body">
        <div class="qa-detail-meta-grid">
          <div class="qa-detail-meta-item">
            <span>用户</span>
            <strong>{{ userLabel(selectedDetail) }}</strong>
          </div>
          <div class="qa-detail-meta-item">
            <span>项目</span>
            <strong>{{ projectLabel(selectedDetail) }}</strong>
          </div>
          <div class="qa-detail-meta-item">
            <span>会话</span>
            <strong>{{ selectedDetail.session_title || '-' }}</strong>
          </div>
          <div class="qa-detail-meta-item">
            <span>类型</span>
            <t-tag :theme="chatTypeTheme(selectedDetail.chat_type)" variant="light">
              {{ chatTypeLabel(selectedDetail.chat_type) }}
            </t-tag>
          </div>
          <div class="qa-detail-meta-item">
            <span>检索器</span>
            <strong>{{ retrieverLabel(selectedDetail.retrievers) }}</strong>
          </div>
          <div class="qa-detail-meta-item">
            <span>意图</span>
            <strong>{{ selectedDetail.intent || '-' }}</strong>
          </div>
          <div class="qa-detail-meta-item">
            <span>耗时</span>
            <strong>{{ durationLabel(selectedDetail.elapsed_ms) }}</strong>
          </div>
          <div class="qa-detail-meta-item">
            <span>回答时间</span>
            <strong>{{ formatDateTime(selectedDetail.answered_at || selectedDetail.created_at) }}</strong>
          </div>
        </div>

        <div class="qa-chat-thread">
          <div class="qa-chat-row user">
            <div class="qa-chat-message user-message">
              <p>{{ selectedDetail.question || '-' }}</p>
            </div>
            <UserAvatar
              class="qa-chat-avatar user"
              :user-id="selectedDetail.user_id"
              :avatar-url="selectedDetail.avatar_url"
              :avatar-updated-at="selectedDetail.avatar_updated_at"
              :name="userLabel(selectedDetail)"
              size="32px"
              shape="circle"
            />
          </div>
          <div class="qa-chat-row assistant">
            <span class="qa-chat-avatar assistant" aria-label="Botree AI" role="img">
              <img :src="botreeLogo" alt="" />
            </span>
            <div class="qa-chat-message assistant-message">
              <ChatRichContent :content="normalizeMarkdownDisplay(selectedDetail.answer)" />
            </div>
          </div>
        </div>

        <div class="qa-detail-related">
          <t-tabs :value="detailDrawerTab" @change="handleDrawerTabChange">
            <t-tab-panel value="citations" label="引用来源" />
            <t-tab-panel value="trace" label="执行过程" />
          </t-tabs>
          <div class="qa-detail-related-body">
            <CitationList
              v-if="detailDrawerTab === 'citations'"
              :citations="selectedDetailCitations"
              :chat-type="selectedDetail.chat_type"
            />
            <AgentTracePanel v-else :steps="selectedDetailTrace" />
          </div>
        </div>
      </div>
    </t-drawer>
  </div>
</template>

<style scoped>
.system-card {
  display: flex;
  flex: 1 1 0;
  height: 100%;
  min-height: 0;
  min-width: 0;
  flex-direction: column;
  margin-top: 0;
  overflow: hidden;
}

.audit-filter-form {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: nowrap;
  align-items: center;
  margin-bottom: 18px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  padding: 14px 16px;
  overflow-x: auto;
  overflow-y: hidden;
  white-space: nowrap;
}

.audit-filter-form :deep(.t-form__item) {
  flex: 0 0 auto;
  margin-right: 16px;
  margin-bottom: 0;
}

.audit-filter-form :deep(.audit-filter-action) {
  margin-right: 0;
}

.audit-filter-form :deep(.t-form__label) {
  width: auto !important;
  padding-right: 8px;
}

.audit-filter-form :deep(.t-form__controls) {
  margin-left: 0 !important;
}

.system-card :deep(.t-tabs) {
  flex: 0 0 auto;
}

.system-section-head {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 18px 0 10px;
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

.audit-select {
  width: 176px;
}

.audit-date-range {
  width: 268px;
}

.feedback-select {
  width: 132px;
}

.audit-table-section {
  display: flex;
  flex: 1 1 0;
  min-height: 0;
  flex-direction: column;
  margin-top: 0;
  overflow: hidden;
}

.audit-table-scroll {
  flex: 1 1 0;
  min-height: 240px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
  overflow: auto;
  scrollbar-gutter: auto;
}

.audit-table-scroll :deep(.t-table) {
  min-width: 100%;
}

.audit-summary-text {
  display: -webkit-box;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  line-height: 1.6;
  word-break: break-word;
}

.audit-pagination {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  justify-content: flex-end;
  min-height: 48px;
  margin-top: 12px;
  border-top: 1px solid #edf2f7;
  background: #fff;
  padding-top: 12px;
}

.qa-detail-drawer-body {
  display: flex;
  min-height: 0;
  flex-direction: column;
  gap: 18px;
}

.qa-detail-meta-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.qa-detail-meta-item {
  display: flex;
  min-width: 0;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid #edf2f7;
  padding-bottom: 8px;
  color: #64748b;
  font-size: 12px;
}

.qa-detail-meta-item span {
  flex: 0 0 56px;
}

.qa-detail-meta-item strong {
  min-width: 0;
  overflow: hidden;
  color: #334155;
  font-size: 13px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qa-chat-thread {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.qa-chat-row {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 10px;
}

.qa-chat-row.user {
  justify-content: flex-end;
}

.qa-chat-row.assistant {
  justify-content: flex-start;
}

.qa-chat-avatar {
  display: inline-flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border: 1px solid rgba(255, 255, 255, 0.82);
  border-radius: 8px;
  box-shadow: 0 8px 18px rgba(15, 23, 42, 0.12);
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  user-select: none;
}

.qa-chat-avatar.assistant {
  overflow: hidden;
  border-color: transparent;
  background: transparent;
  box-shadow: none;
}

.qa-chat-avatar.assistant img {
  display: block;
  width: 32px;
  height: 32px;
  object-fit: contain;
}

.qa-chat-avatar.user {
  border-radius: 999px;
  background: #2563eb;
}

.qa-chat-message {
  min-width: 0;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 10px 12px;
  color: #475569;
  font-size: 13px;
  line-height: 1.62;
  word-break: break-word;
}

.qa-chat-message.user-message {
  max-width: min(560px, calc(100% - 48px));
  background: #f0fdf4;
  border-color: #bbf7d0;
  color: #14532d;
  white-space: pre-wrap;
}

.qa-chat-message.assistant-message {
  width: calc(100% - 48px);
  background: #fff;
}

.qa-chat-message p {
  margin: 0;
}

.qa-detail-related {
  min-height: 0;
  border-top: 1px solid #edf2f7;
  padding-top: 2px;
}

.qa-detail-related-body {
  padding-top: 12px;
}

@media (max-width: 640px) {
  .qa-detail-meta-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .qa-chat-message.user-message,
  .qa-chat-message.assistant-message {
    max-width: calc(100% - 42px);
    width: calc(100% - 42px);
  }
}
</style>
