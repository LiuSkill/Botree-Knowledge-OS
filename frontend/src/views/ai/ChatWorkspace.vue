<!--
  Chat Workspace

  负责：
  1. 复用项目问答和基础问答布局
  2. 使用 TDesign Chat 组件承载消息、推理过程和发送器
  3. 接入后端流式问答，并展示引用来源、执行过程和知识范围
-->
<script setup lang="ts">
import { ChatContent as TChatContent, ChatMessage as TChatMessage, ChatSender as TChatSender, ChatThinking as TChatThinking } from '@tdesign-vue-next/chat';
import { CloseIcon, QuoteIcon, TaskIcon, ThumbDownIcon, ThumbUpIcon } from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, nextTick, onMounted, provide, ref } from 'vue';

import { listChatMessages, listChatSessions, streamKnowledgeAgent, updateMessageFeedback, type ChatFeedbackStatus } from '@/api/chat';
import { listProjects } from '@/api/projects';
import botreeLogo from '@/assets/botree-logo.png';
import AgentTracePanel from '@/components/AgentTracePanel.vue';
import ChatRichContent from '@/components/ChatRichContent.vue';
import CitationList from '@/components/CitationList.vue';
import UserAvatar from '@/components/UserAvatar.vue';
import { useAuthStore } from '@/stores/auth';
import type {
  AgentTraceStep,
  ChatMessage,
  ChatSession,
  ChatStreamDoneEvent,
  ChatTraceDeltaEvent,
  Citation,
  ProjectInfo,
} from '@/types/api';
import { formatDateTime } from '@/utils/format';

interface UiChatMessage extends Omit<ChatMessage, 'id' | 'citations'> {
  id: number | string;
  citations: Citation[];
  agentTrace: AgentTraceStep[];
  status?: '' | 'streaming' | 'complete' | 'stop' | 'error';
  streaming?: boolean;
}

type DetailMode = 'citations' | 'trace';

const props = defineProps<{
  chatType: 'project_chat' | 'base_chat';
  notice: string;
  requireProject: boolean;
}>();

const authStore = useAuthStore();
const sessions = ref<ChatSession[]>([]);
const messages = ref<UiChatMessage[]>([]);
const projects = ref<ProjectInfo[]>([]);
const activeSessionId = ref<number | null>(null);
const projectId = ref<number | null>(null);
const question = ref('');
const streaming = ref(false);
const citations = ref<Citation[]>([]);
const trace = ref<AgentTraceStep[]>([]);
const queryScope = ref('');
const chatHistoryRef = ref<HTMLElement | null>(null);
const senderShellRef = ref<HTMLElement | null>(null);
const streamAbortController = ref<AbortController | null>(null);
const thinkingCollapsedMap = ref<Record<string, boolean>>({});
const activeDetailMode = ref<DetailMode | null>(null);
const activeDetailMessageId = ref<number | string | null>(null);
const feedbackUpdatingMap = ref<Record<number, boolean>>({});
// 正文通过插槽渲染，外层 TChatMessage 保持空状态，避免底层加载态替换插槽内容。
const chatMessageStatus = '';

const isExternalUser = computed(() =>
  Boolean(authStore.user?.roles.some((role) => role.code === 'external' || role.name.includes('外部'))),
);
const senderDisabled = computed(
  () => streaming.value || (props.requireProject && !projectId.value) || (props.chatType === 'base_chat' && isExternalUser.value),
);
const sessionEmptyDescription = computed(() =>
  props.chatType === 'project_chat' && !projectId.value ? '请先选择项目' : '暂无会话',
);
const userAvatarLabel = computed(() => authStore.user?.real_name || authStore.user?.username || 'User');
const activeDetailMessage = computed(
  () => messages.value.find((item) => item.role === 'assistant' && item.id === activeDetailMessageId.value) || null,
);
const isDetailOpen = computed(() => Boolean(activeDetailMode.value && activeDetailMessage.value));
const detailPanelTitle = computed(() => (activeDetailMode.value === 'citations' ? '引用来源' : '执行过程'));
const activeDetailCitations = computed(() => activeDetailMessage.value?.citations || []);
const activeDetailTrace = computed(() => activeDetailMessage.value?.agentTrace || []);
const activeDetailQuestion = computed(() => (activeDetailMessage.value ? questionForAssistant(activeDetailMessage.value) : ''));

provide('role', computed(() => 'assistant'));

function parseAgentTrace(rawTrace?: string | null): AgentTraceStep[] {
  if (!rawTrace) return [];
  try {
    const parsed = JSON.parse(rawTrace);
    return Array.isArray(parsed) ? (parsed as AgentTraceStep[]) : [];
  } catch {
    return [];
  }
}

function toUiMessage(message: ChatMessage): UiChatMessage {
  return {
    ...message,
    id: message.id,
    citations: message.citations || [],
    agentTrace: parseAgentTrace(message.agent_trace_json),
    status: '',
    streaming: false,
  };
}

function createStreamingAssistantMessage(): UiChatMessage {
  return {
    id: `stream-assistant-${Date.now()}`,
    session_id: activeSessionId.value || 0,
    role: 'assistant',
    content: '',
    query_scope: '',
    agent_trace_json: null,
    feedback_status: null,
    citations: [],
    agentTrace: [],
    created_at: new Date().toISOString(),
    status: 'streaming',
    streaming: true,
  };
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

function renderTraceSummary(step: AgentTraceStep): string {
  if (step.display_text) return step.display_text;
  if (step.result) return step.result;
  if (step.output_summary && Object.keys(step.output_summary).length) {
    return JSON.stringify(step.output_summary, null, 2);
  }
  if (step.details && Object.keys(step.details).length) {
    return JSON.stringify(step.details, null, 2);
  }
  return '已执行';
}

function traceStepKey(message: UiChatMessage, step: AgentTraceStep): string {
  return `${message.id}-${step.sequence ?? step.step}`;
}

function mergeTraceStep(items: AgentTraceStep[], nextStep: AgentTraceStep): AgentTraceStep[] {
  const index =
    nextStep.sequence !== undefined && nextStep.sequence !== null
      ? items.findIndex((item) => item.sequence === nextStep.sequence)
      : items.findIndex((item) => item.step === nextStep.step);
  if (index < 0) return [...items, nextStep];
  const merged = [...items];
  merged[index] = { ...merged[index], ...nextStep };
  return merged;
}

function applyTraceDelta(assistantId: number | string, payload: ChatTraceDeltaEvent): void {
  const currentAssistant = messages.value.find((item) => item.id === assistantId);
  trace.value = mergeTraceStep(trace.value, payload);
  if (!currentAssistant) return;
  currentAssistant.agentTrace = mergeTraceStep(currentAssistant.agentTrace, payload);
}

function thinkingStatus(message: UiChatMessage): 'pending' | 'complete' | 'stop' | 'error' {
  if (message.status === 'error') return 'error';
  if (message.status === 'stop') return 'stop';
  if (message.streaming) return 'pending';
  return 'complete';
}

function chatContentStatus(message: UiChatMessage): '' | 'error' {
  return message.status === 'error' ? 'error' : '';
}

function thinkingContent(message: UiChatMessage): { title: string } {
  return {
    title: message.streaming && !message.content.trim() ? '正在处理...' : '执行过程',
  };
}

function shouldShowThinking(message: UiChatMessage): boolean {
  return !message.content.trim() && (message.streaming || message.agentTrace.length > 0);
}

function shouldShowAssistantActions(message: UiChatMessage): boolean {
  return message.role === 'assistant' && typeof message.id === 'number' && !message.streaming && Boolean(message.content.trim());
}

function questionForAssistant(message: UiChatMessage): string {
  const messageIndex = messages.value.findIndex((item) => item.id === message.id);
  if (messageIndex <= 0) return '';
  for (let index = messageIndex - 1; index >= 0; index -= 1) {
    const candidate = messages.value[index];
    if (candidate.role === 'user') return candidate.content;
  }
  return '';
}

function closeDetailPanel(): void {
  activeDetailMode.value = null;
  activeDetailMessageId.value = null;
}

function closeDetailPanelAndFocus(): void {
  closeDetailPanel();
  void focusQuestionInput();
}

function toggleDetailPanel(message: UiChatMessage, mode: DetailMode): void {
  if (!shouldShowAssistantActions(message)) {
    void focusQuestionInput();
    return;
  }
  const isSamePanel = activeDetailMessageId.value === message.id && activeDetailMode.value === mode;
  if (isSamePanel) {
    closeDetailPanel();
    void focusQuestionInput();
    return;
  }
  activeDetailMessageId.value = message.id;
  activeDetailMode.value = mode;
  void focusQuestionInput();
}

function isDetailButtonActive(message: UiChatMessage, mode: DetailMode): boolean {
  return activeDetailMessageId.value === message.id && activeDetailMode.value === mode;
}

function isFeedbackUpdating(message: UiChatMessage): boolean {
  return typeof message.id === 'number' && Boolean(feedbackUpdatingMap.value[message.id]);
}

async function handleFeedbackClick(message: UiChatMessage, feedbackStatus: Exclude<ChatFeedbackStatus, null>): Promise<void> {
  if (!shouldShowAssistantActions(message) || typeof message.id !== 'number' || isFeedbackUpdating(message)) return;
  const nextStatus: ChatFeedbackStatus = message.feedback_status === feedbackStatus ? null : feedbackStatus;
  const previousStatus = message.feedback_status || null;
  feedbackUpdatingMap.value = { ...feedbackUpdatingMap.value, [message.id]: true };
  message.feedback_status = nextStatus;
  try {
    const result = await updateMessageFeedback(message.id, nextStatus);
    message.feedback_status = result.feedback_status;
  } catch (error) {
    message.feedback_status = previousStatus;
    MessagePlugin.error(error instanceof Error ? error.message : '反馈保存失败');
  } finally {
    const { [message.id]: _removed, ...remaining } = feedbackUpdatingMap.value;
    feedbackUpdatingMap.value = remaining;
    await focusQuestionInput();
  }
}

function shouldCollapseThinking(message: UiChatMessage): boolean {
  const messageKey = String(message.id);
  if (thinkingCollapsedMap.value[messageKey] !== undefined) {
    return thinkingCollapsedMap.value[messageKey];
  }
  if (message.content.trim()) return true;
  return !message.streaming;
}

function onThinkingCollapsedChange(message: UiChatMessage, value: boolean | CustomEvent<boolean | boolean[]>): void {
  const eventDetail = typeof value === 'boolean' ? value : value.detail;
  const collapsed = Array.isArray(eventDetail) ? Boolean(eventDetail[0]) : Boolean(eventDetail);
  thinkingCollapsedMap.value = {
    ...thinkingCollapsedMap.value,
    [String(message.id)]: collapsed,
  };
}

function traceStatusText(step: AgentTraceStep): string {
  if (step.status === 'running') return '进行中';
  if (step.status === 'failed') return '失败';
  return step.elapsed_ms !== undefined && step.elapsed_ms !== null ? `${step.elapsed_ms} ms` : '完成';
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const container = chatHistoryRef.value;
  if (!container) return;
  container.scrollTop = container.scrollHeight;
}

async function focusQuestionInput(): Promise<void> {
  await nextTick();
  if (senderDisabled.value) return;
  const textarea = senderShellRef.value?.querySelector<HTMLTextAreaElement>('textarea');
  if (!textarea || textarea.disabled) return;
  textarea.focus();
  textarea.setSelectionRange(textarea.value.length, textarea.value.length);
}

function syncAssistantContext(items: UiChatMessage[]): void {
  const latestAssistant = [...items].reverse().find((item) => item.role === 'assistant');
  citations.value = latestAssistant?.citations || [];
  queryScope.value = latestAssistant?.query_scope || '';
  trace.value = latestAssistant?.agentTrace || [];
}

async function loadSessionsForCurrentProject(): Promise<void> {
  if (props.chatType === 'project_chat' && projectId.value === null) {
    sessions.value = [];
    return;
  }

  const params: { chat_type: 'project_chat' | 'base_chat'; project_id?: number } = { chat_type: props.chatType };
  if (props.chatType === 'project_chat' && projectId.value !== null) {
    params.project_id = projectId.value;
  }
  sessions.value = await listChatSessions(params);
}

async function loadBaseData(): Promise<void> {
  projects.value = props.requireProject ? await listProjects() : [];
  await loadSessionsForCurrentProject();
  if (props.chatType === 'base_chat' && !activeSessionId.value && sessions.value.length) {
    await selectSession(sessions.value[0]);
  }
  await focusQuestionInput();
}

async function selectSession(session: ChatSession): Promise<void> {
  closeDetailPanel();
  activeSessionId.value = session.id;
  projectId.value = session.project_id || null;
  const fetchedMessages = await listChatMessages(session.id);
  messages.value = fetchedMessages.map(toUiMessage);
  syncAssistantContext(messages.value);
  await scrollToBottom();
  await focusQuestionInput();
}

function startNewSession(): void {
  if (streaming.value) return;
  closeDetailPanel();
  activeSessionId.value = null;
  messages.value = [];
  citations.value = [];
  trace.value = [];
  queryScope.value = '';
  void focusQuestionInput();
}

async function onProjectChange(value: number | string | Array<number | string> | undefined): Promise<void> {
  if (Array.isArray(value)) return;
  const nextProjectId = typeof value === 'number' ? value : value ? Number(value) : null;
  projectId.value = nextProjectId !== null && Number.isFinite(nextProjectId) ? nextProjectId : null;
  if (props.chatType !== 'project_chat') return;
  startNewSession();
  await loadSessionsForCurrentProject();
}

function stopStreaming(): void {
  streamAbortController.value?.abort();
}

async function refreshSessionState(sessionId: number): Promise<void> {
  closeDetailPanel();
  await loadSessionsForCurrentProject();
  const fetchedMessages = await listChatMessages(sessionId);
  messages.value = fetchedMessages.map(toUiMessage);
  activeSessionId.value = sessionId;
  syncAssistantContext(messages.value);
  await scrollToBottom();
}

async function submitQuestion(): Promise<void> {
  const content = question.value.trim();
  if (props.requireProject && !projectId.value) {
    MessagePlugin.warning('请先选择项目');
    return;
  }
  if (props.chatType === 'base_chat' && isExternalUser.value) {
    MessagePlugin.warning('外部用户默认不能访问基础问答');
    return;
  }
  if (!content) {
    MessagePlugin.warning('请输入问题');
    return;
  }
  if (streaming.value) return;

  const userMessage: UiChatMessage = {
    id: `stream-user-${Date.now()}`,
    session_id: activeSessionId.value || 0,
    role: 'user',
    content,
    query_scope: null,
    agent_trace_json: null,
    citations: [],
    agentTrace: [],
    created_at: new Date().toISOString(),
    status: '',
    streaming: false,
  };
  const assistantMessage = createStreamingAssistantMessage();
  const assistantId = assistantMessage.id;
  const originalQuestion = content;
  let finalResult: ChatStreamDoneEvent | null = null;

  messages.value = [...messages.value, userMessage, assistantMessage];
  citations.value = [];
  trace.value = [];
  queryScope.value = '';
  question.value = '';
  streaming.value = true;
  streamAbortController.value = new AbortController();
  await scrollToBottom();

  try {
    await streamKnowledgeAgent(
      {
        chat_type: props.chatType,
        mode: 'auto',
        project_id: props.chatType === 'project_chat' ? projectId.value : null,
        session_id: activeSessionId.value,
        message: originalQuestion,
        agent_enabled: true,
      },
      {
        signal: streamAbortController.value.signal,
        onMeta: (payload) => {
          activeSessionId.value = payload.session_id;
          citations.value = payload.citations;
          trace.value = payload.agent_trace;
          queryScope.value = payload.query_scope;
          const currentAssistant = messages.value.find((item) => item.id === assistantId);
          if (!currentAssistant) return;
          currentAssistant.session_id = payload.session_id;
          currentAssistant.query_scope = payload.query_scope;
          currentAssistant.citations = payload.citations;
          currentAssistant.agentTrace = payload.agent_trace;
        },
        onTraceDelta: (payload) => {
          applyTraceDelta(assistantId, payload);
          void scrollToBottom();
        },
        onDelta: (delta) => {
          const currentAssistant = messages.value.find((item) => item.id === assistantId);
          if (!currentAssistant) return;
          currentAssistant.content += delta;
          void scrollToBottom();
        },
        onDone: (payload) => {
          finalResult = payload;
          citations.value = payload.citations;
          trace.value = payload.agent_trace;
          queryScope.value = payload.query_scope;
        },
      },
    );

    if (finalResult) {
      await refreshSessionState(finalResult.session_id);
    }
  } catch (error) {
    const currentAssistant = messages.value.find((item) => item.id === assistantId);
    if (error instanceof DOMException && error.name === 'AbortError') {
      if (currentAssistant && !currentAssistant.content.trim()) {
        currentAssistant.content = '已停止生成';
      }
      if (currentAssistant) currentAssistant.status = 'stop';
      MessagePlugin.info('已停止本次回答生成');
      return;
    }
    if (currentAssistant) {
      currentAssistant.status = 'error';
      if (!currentAssistant.content.trim()) {
        currentAssistant.content = '回答生成失败，请重试。';
      }
    }
    MessagePlugin.error(error instanceof Error ? error.message : '问答失败');
  } finally {
    streaming.value = false;
    const currentAssistant = messages.value.find((item) => item.id === assistantId);
    if (currentAssistant) {
      currentAssistant.streaming = false;
      if (currentAssistant.status === 'streaming') {
        currentAssistant.status = currentAssistant.content.trim() ? 'complete' : '';
      }
    }
    streamAbortController.value = null;
    await scrollToBottom();
    await focusQuestionInput();
  }
}

onMounted(loadBaseData);
</script>

<template>
  <section class="chat-workspace-page">
    <div v-if="chatType === 'base_chat' && isExternalUser" class="surface no-access">
      外部用户默认不能访问基础问答，请从项目问答入口进入已授权项目。
    </div>
    <div v-else class="agent-layout" :class="{ 'with-detail': isDetailOpen }">
      <aside class="agent-sidebar surface">
        <div class="sidebar-header">
          <div class="agent-title">{{ chatType === 'project_chat' ? '项目问答会话' : '基础问答会话' }}</div>
          <t-button block theme="primary" variant="outline" :disabled="streaming" @click="startNewSession">新建对话</t-button>
        </div>
        <div class="session-list">
          <t-button
            v-for="session in sessions"
            :key="session.id"
            class="session-item"
            :class="{ active: session.id === activeSessionId }"
            block
            variant="text"
            @click="selectSession(session)"
          >
            <span class="truncate">{{ session.title }}</span>
            <small>{{ formatDateTime(session.created_at) }}</small>
          </t-button>
          <t-empty v-if="!sessions.length" size="small" :description="sessionEmptyDescription" />
        </div>
      </aside>

      <main class="chat-panel surface">
        <div class="chat-toolbar">
          <t-select
            v-if="requireProject"
            :model-value="projectId"
            clearable
            placeholder="请选择项目"
            class="project-select"
            :disabled="streaming"
            @change="onProjectChange"
          >
            <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="project.name" />
          </t-select>
  
        </div>

        <div ref="chatHistoryRef" class="chat-history">
          <t-empty v-if="!messages.length" description="当前入口只会基于有权限、已审核、已索引资料回答" />
          <div v-for="message in messages" :key="message.id" class="chat-item-row" :class="message.role">
            <div v-if="message.role === 'assistant'" class="assistant-chat-row">
              <span class="chat-avatar assistant" aria-label="Botree AI" role="img">
                <img :src="botreeLogo" alt="" />
              </span>
              <div class="assistant-chat-stack">
                <TChatThinking
                  v-if="shouldShowThinking(message)"
                  class="message-thinking"
                  layout="border"
                  :status="thinkingStatus(message)"
                  :content="thinkingContent(message)"
                  :collapsed="shouldCollapseThinking(message)"
                  @collapsed-change="onThinkingCollapsedChange(message, $event)"
                >
                  <div class="thinking-list">
                    <div
                      v-for="step in message.agentTrace"
                      :key="traceStepKey(message, step)"
                      class="thinking-step"
                      :class="step.status || 'success'"
                    >
                      <span class="thinking-dot"></span>
                      <div class="thinking-step-body">
                        <div class="thinking-step-header">
                          <strong>{{ step.step }}</strong>
                          <span>{{ traceStatusText(step) }}</span>
                        </div>
                        <p>{{ renderTraceSummary(step) }}</p>
                      </div>
                    </div>
                  </div>
                </TChatThinking>

                <TChatMessage
                  v-if="message.content"
                  :role="message.role"
                  placement="left"
                  :status="chatMessageStatus"
                  variant="outline"
                  class="chat-message assistant-chat-message"
                >
                  <ChatRichContent :content="normalizeMarkdownDisplay(message.content)" />
                  <div v-if="shouldShowAssistantActions(message)" class="message-action-bar">
                    <t-tooltip content="点赞">
                      <t-button
                        class="message-action-button"
                        :class="{ active: message.feedback_status === 'like' }"
                        variant="text"
                        shape="square"
                        :disabled="isFeedbackUpdating(message)"
                        @click="handleFeedbackClick(message, 'like')"
                      >
                        <ThumbUpIcon />
                      </t-button>
                    </t-tooltip>
                    <t-tooltip content="点踩">
                      <t-button
                        class="message-action-button"
                        :class="{ active: message.feedback_status === 'dislike' }"
                        variant="text"
                        shape="square"
                        :disabled="isFeedbackUpdating(message)"
                        @click="handleFeedbackClick(message, 'dislike')"
                      >
                        <ThumbDownIcon />
                      </t-button>
                    </t-tooltip>
                    <t-tooltip content="引用来源">
                      <t-button
                        class="message-action-button"
                        :class="{ active: isDetailButtonActive(message, 'citations') }"
                        variant="text"
                        shape="square"
                        @click="toggleDetailPanel(message, 'citations')"
                      >
                        <QuoteIcon />
                      </t-button>
                    </t-tooltip>
                    <t-tooltip content="执行过程">
                      <t-button
                        class="message-action-button"
                        :class="{ active: isDetailButtonActive(message, 'trace') }"
                        variant="text"
                        shape="square"
                        @click="toggleDetailPanel(message, 'trace')"
                      >
                        <TaskIcon />
                      </t-button>
                    </t-tooltip>
                  </div>
                </TChatMessage>
              </div>
            </div>

            <TChatMessage
              v-else
              :role="message.role"
              placement="right"
              :status="chatMessageStatus"
              variant="outline"
              class="chat-message"
            >
              <template #avatar>
                <UserAvatar
                  class="chat-avatar user"
                  :user-id="authStore.user?.id"
                  :avatar-url="authStore.user?.avatar_url"
                  :avatar-updated-at="authStore.user?.avatar_updated_at"
                  :name="userAvatarLabel"
                  size="32px"
                  shape="circle"
                />
              </template>
              <TChatContent
                :role="message.role"
                :status="chatContentStatus(message)"
                :content="message.content"
              />
            </TChatMessage>
          </div>
        </div>

        <div ref="senderShellRef" class="sender-shell">
          <TChatSender
            v-model="question"
            :loading="streaming"
            :disabled="senderDisabled"
            :stop-disabled="false"
            :send-btn-disabled="senderDisabled"
            :textarea-props="{ autosize: { minRows: 1, maxRows: 2 }, placeholder: '有问题，尽管问' }"
            @send="submitQuestion"
            @stop="stopStreaming"
          />
        </div>
      </main>

      <aside v-if="isDetailOpen" class="agent-right surface">
        <div class="detail-panel-header">
          <div class="detail-panel-heading">
            <span class="detail-panel-label">{{ detailPanelTitle }}</span>
            <p class="detail-panel-question"><span>原始问题：</span>{{ activeDetailQuestion || '未找到原始问题' }}</p>
          </div>
          <t-button variant="text" shape="square" aria-label="关闭详情" @click="closeDetailPanelAndFocus">
            <CloseIcon />
          </t-button>
        </div>
        <div class="detail-panel-body">
          <CitationList v-if="activeDetailMode === 'citations'" :citations="activeDetailCitations" :chat-type="chatType" />
          <AgentTracePanel v-else-if="activeDetailMode === 'trace'" :steps="activeDetailTrace" />
        </div>
      </aside>
    </div>
  </section>
</template>

<style scoped>
.chat-workspace-page {
  display: flex;
  height: 100%;
  min-height: 0;
  flex-direction: column;
  overflow: hidden;
  padding: 24px;
}

.agent-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr);
  flex: 1;
  gap: 16px;
  min-height: 0;
  overflow: hidden;
}

.agent-layout.with-detail {
  grid-template-columns: 280px minmax(0, 1fr) 360px;
}

.agent-sidebar,
.agent-right,
.chat-panel,
.no-access {
  height: 100%;
  min-height: 0;
  overflow: hidden;
  padding: 16px;
}

.agent-sidebar,
.chat-panel,
.agent-right,
.no-access {
  display: flex;
  min-height: 0;
  flex-direction: column;
}

.no-access {
  flex: 1;
  min-height: 0;
}

.sidebar-header {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 12px;
}

.agent-title {
  color: #111827;
  font-weight: 700;
}

.session-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
  overflow: auto;
}

.session-item {
  display: flex;
  width: 100%;
  height: auto;
  min-height: 56px;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  border-radius: 8px;
  padding: 10px;
  text-align: left;
}

.session-item :deep(.t-button__text) {
  display: flex;
  width: 100%;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
}

.session-item.active {
  background: #eaf2ff;
  color: #1d4ed8;
  font-weight: 700;
}

.chat-panel {
  display: flex;
  flex-direction: column;
}

.chat-toolbar {
  display: flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 12px;
  padding-bottom: 12px;
}

.project-select {
  width: 280px;
  flex: 0 0 280px;
}

.notice {
  color: #4b5563;
}

.chat-history {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding: 8px 10px 16px;
}

.chat-item-row {
  display: flex;
  flex-direction: column;
  margin-bottom: 16px;
}

.chat-item-row.user {
  align-items: flex-end;
}

.assistant-chat-row {
  display: flex;
  width: calc(100% - 10em);
  max-width: 100%;
  align-items: flex-start;
  gap: 12px;
}

.assistant-chat-row > .chat-avatar {
  flex: 0 0 auto;
  margin-top: 2px;
}

.assistant-chat-stack {
  display: flex;
  width: 100%;
  max-width: none;
  min-width: 0;
  flex: 1;
  flex-direction: column;
}

.chat-message {
  width: min(100%, 780px);
  --td-chat-item-left-avatar-margin: 0 12px 0 0;
  --td-chat-item-right-avatar-margin: 0 0 0 12px;
  --td-chat-item-avatar-padding: 2px 0 0;
  --td-chat-item-avatar-has-header-padding: 2px 0 0;
}

.assistant-chat-message {
  width: 100%;
  max-width: none;
  --td-chat-item-left-avatar-margin: 0;
  --td-chat-item-avatar-padding: 0;
  --td-chat-item-avatar-has-header-padding: 0;
}

.assistant-chat-message::part(t-chat__item__avatar) {
  display: none;
}

.chat-avatar {
  display: inline-flex;
  width: 32px;
  height: 32px;
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

.chat-avatar.assistant {
  overflow: hidden;
  border-color: transparent;
  background: transparent;
  box-shadow: none;
}

.chat-avatar.assistant img {
  display: block;
  width: 32px;
  height: 32px;
  object-fit: contain;
}

.chat-avatar.user {
  border-radius: 999px;
  background: #2563eb;
}

.chat-message :deep(.t-chat__text) {
  color: #475569;
  font-size: 13px;
  line-height: 1.72;
  white-space: normal;
}

.assistant-chat-message :deep(.t-chat__text) {
  width: 100%;
  max-width: none;
  box-sizing: border-box;
  padding: 4px 0;
  font-size: 13px;
  line-height: 1.62;
}

.assistant-chat-message :deep(.t-chat__text__assistant),
.assistant-chat-message :deep(.t-chat__text__content),
.assistant-chat-message :deep(.t-chat__text p),
.assistant-chat-message :deep(.t-chat__text ul),
.assistant-chat-message :deep(.t-chat__text ol),
.assistant-chat-message :deep(.t-chat__text li) {
  color: #475569;
  font-size: 13px;
  line-height: 1.62;
}

.chat-item-row.user .chat-message :deep(.t-chat__text) {
  font-size: 13px;
  line-height: 1.62;
  white-space: pre-wrap;
}

.chat-item-row.user .chat-message :deep(.t-chat__text pre),
.chat-item-row.user .chat-message :deep(.t-chat__text__content) {
  font-size: 13px;
  line-height: 1.62;
}

.chat-message :deep(.t-chat__text p) {
  margin: 0 0 10px;
}

.chat-message :deep(.t-chat__text p:last-child) {
  margin-bottom: 0;
}

.chat-message :deep(.t-chat__text h1),
.chat-message :deep(.t-chat__text h2),
.chat-message :deep(.t-chat__text h3),
.chat-message :deep(.t-chat__text h4) {
  margin: 18px 0 10px;
  line-height: 1.35;
}

.assistant-chat-message :deep(.t-chat__text h1),
.assistant-chat-message :deep(.t-chat__text h2),
.assistant-chat-message :deep(.t-chat__text h3),
.assistant-chat-message :deep(.t-chat__text h4),
.assistant-chat-message :deep(.t-chat__text h5),
.assistant-chat-message :deep(.t-chat__text h6) {
  margin: 10px 0 6px;
  color: #475569;
  font-size: 13px;
  font-weight: 600;
  line-height: 1.5;
}

.chat-message :deep(.t-chat__text ul),
.chat-message :deep(.t-chat__text ol) {
  margin: 8px 0 10px;
  padding-left: 24px;
}

.chat-message :deep(.t-chat__text li) {
  margin: 4px 0;
}

.chat-message :deep(.t-chat__text pre) {
  white-space: pre-wrap;
}

.message-thinking {
  width: 100%;
}

.message-thinking {
  color: #7a8699;
  font-size: 12px;
  line-height: 1.55;
  margin-bottom: 8px;
}

.message-thinking :deep(.t-collapse-panel__header) {
  cursor: pointer;
}

.message-thinking :deep(.t-chat__item__think__header__content) {
  color: #475569;
  font-size: 13px;
  font-weight: 600;
}

.message-thinking :deep(.t-chat__item__think__inner) {
  color: #7a8699;
  font-size: 12px;
  line-height: 1.55;
  max-height: none;
  overflow: visible;
}

.message-thinking :deep(*) {
  scrollbar-width: none;
}

.message-thinking :deep(*::-webkit-scrollbar) {
  display: none;
}

.thinking-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.thinking-step {
  display: flex;
  gap: 10px;
  color: #7a8699;
  font-size: 12px;
  line-height: 1.55;
}

.thinking-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  margin-top: 8px;
  border-radius: 50%;
  background: #a3b1c6;
}

.thinking-step.running .thinking-dot {
  background: #2f6fed;
}

.thinking-step.success .thinking-dot {
  background: #00a870;
}

.thinking-step.failed .thinking-dot {
  background: #d54941;
}

.thinking-step-body {
  flex: 1;
  min-width: 0;
}

.thinking-step-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  color: #667085;
  font-size: 12px;
  font-weight: 600;
}

.thinking-step-header strong {
  font-size: 12px;
  font-weight: 600;
}

.thinking-step-header span {
  color: #8a94a6;
  font-size: 11px;
  font-weight: 500;
}

.thinking-step p {
  margin: 4px 0 0;
  color: #7a8699;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
}

.message-action-bar {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-top: 10px;
  padding-top: 8px;
  border-top: 1px solid #eef2f7;
}

.message-action-button {
  width: 28px;
  height: 28px;
  color: #64748b;
}

.message-action-button :deep(.t-icon) {
  font-size: 16px;
}

.message-action-button:hover,
.message-action-button.active {
  color: #2563eb;
  background: #eff6ff;
}

.sender-shell {
  display: flex;
  flex: 0 0 auto;
  justify-content: center;
  border-top: 1px solid #edf0f5;
  box-sizing: border-box;
  padding: 6px 10px 0;
}

.sender-shell :deep(.t-chat-sender) {
  width: 100%;
  min-width: 0;
  flex: 1 1 auto;
  padding: 0;
}

.sender-shell :deep(.t-chat-sender__textarea) {
  min-height: 54px;
  border-radius: 8px;
  padding: 9px 46px 9px 12px;
}

.sender-shell :deep(.t-chat-sender .t-textarea .t-textarea__inner) {
  color: #475569;
  font-size: 13px;
  line-height: 1.62;
}

.sender-shell :deep(.t-chat-sender .t-textarea .t-textarea__inner::placeholder) {
  font-size: 13px;
}

.sender-shell :deep(.t-chat-sender__header),
.sender-shell :deep(.t-chat-sender__inner-header) {
  min-height: 0;
}

.sender-shell :deep(.t-chat-sender__textarea__wrapper) {
  margin-bottom: 0;
  padding-top: 0;
}

.sender-shell :deep(.t-chat-sender__footer) {
  position: absolute;
  right: 8px;
  bottom: 13px;
  min-height: 0;
  padding-top: 0;
  pointer-events: none;
}

.sender-shell :deep(.t-chat-sender__button) {
  pointer-events: auto;
}

.sender-shell :deep(.t-chat-sender__button .t-chat-sender__button__default) {
  width: 28px;
  height: 28px;
}

@media (max-width: 1180px) {
  .assistant-chat-row {
    width: 100%;
  }

  .sender-shell :deep(.t-chat-sender) {
    width: 100%;
    min-width: 0;
  }
}

.detail-panel-header {
  display: flex;
  flex: 0 0 auto;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  border-bottom: 1px solid #edf0f5;
  padding-bottom: 12px;
}

.detail-panel-heading {
  min-width: 0;
}

.detail-panel-label {
  display: block;
  margin-bottom: 6px;
  color: #111827;
  font-size: 14px;
  font-weight: 700;
}

.detail-panel-question {
  display: -webkit-box;
  max-height: 66px;
  margin: 0;
  overflow: hidden;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  color: #475569;
  font-size: 13px;
  line-height: 1.65;
  text-overflow: ellipsis;
  word-break: break-word;
}

.detail-panel-question span {
  color: #334155;
  font-weight: 600;
}

.detail-panel-body {
  flex: 1;
  min-height: 0;
  overflow: auto;
  padding-top: 12px;
}

</style>
