<!--
  Chat Workspace

  负责：
  1. 复用项目问答和基础问答布局
  2. 使用 TDesign Chat 组件承载消息、推理过程和发送器
  3. 接入后端流式问答，并展示引用来源、执行过程和知识范围
-->
<script setup lang="ts">
import { ChatContent as TChatContent, ChatMessage as TChatMessage, ChatReasoning as TChatReasoning, ChatSender as TChatSender } from '@tdesign-vue-next/chat';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, nextTick, onMounted, provide, ref } from 'vue';

import { listChatMessages, listChatSessions, streamKnowledgeAgent } from '@/api/chat';
import { listProjects } from '@/api/projects';
import AgentTracePanel from '@/components/AgentTracePanel.vue';
import CitationList from '@/components/CitationList.vue';
import PageContainer from '@/components/PageContainer.vue';
import { useAuthStore } from '@/stores/auth';
import type {
  AgentTraceStep,
  ChatMessage,
  ChatStreamDoneEvent,
  Citation,
  ProjectInfo,
} from '@/types/api';
import { formatDateTime } from '@/utils/format';

interface UiChatMessage extends Omit<ChatMessage, 'id' | 'citations'> {
  id: number | string;
  citations: Citation[];
  agentTrace: AgentTraceStep[];
  status?: '' | 'error';
  streaming?: boolean;
}

const props = defineProps<{
  chatType: 'project_chat' | 'base_chat';
  title: string;
  subtitle: string;
  notice: string;
  requireProject: boolean;
}>();

const assistantContentProps = {
  markdownProps: {
    engine: 'marked' as const,
  },
};

const authStore = useAuthStore();
const sessions = ref<Array<{ id: number; title: string; project_id?: number | null; created_at: string }>>([]);
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
const streamAbortController = ref<AbortController | null>(null);

const currentSession = computed(() => sessions.value.find((item) => item.id === activeSessionId.value) || null);
const selectedProject = computed(() => projects.value.find((item) => item.id === projectId.value) || null);
const isExternalUser = computed(() =>
  Boolean(authStore.user?.roles.some((role) => role.code === 'external' || role.name.includes('外部'))),
);
const hitKnowledgeBases = computed(() => Array.from(new Set(citations.value.map((item) => `KB-${item.knowledge_base_id}`))));
const senderDisabled = computed(
  () => streaming.value || (props.requireProject && !projectId.value) || (props.chatType === 'base_chat' && isExternalUser.value),
);

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
    citations: [],
    agentTrace: [],
    created_at: new Date().toISOString(),
    status: '',
    streaming: true,
  };
}

function renderTraceSummary(step: AgentTraceStep): string {
  if (step.result) return step.result;
  if (step.output_summary && Object.keys(step.output_summary).length) {
    return JSON.stringify(step.output_summary, null, 2);
  }
  if (step.details && Object.keys(step.details).length) {
    return JSON.stringify(step.details, null, 2);
  }
  return '已执行';
}

async function scrollToBottom(): Promise<void> {
  await nextTick();
  const container = chatHistoryRef.value;
  if (!container) return;
  container.scrollTop = container.scrollHeight;
}

function syncAssistantContext(items: UiChatMessage[]): void {
  const latestAssistant = [...items].reverse().find((item) => item.role === 'assistant');
  citations.value = latestAssistant?.citations || [];
  queryScope.value = latestAssistant?.query_scope || '';
  trace.value = latestAssistant?.agentTrace || [];
}

async function loadBaseData(): Promise<void> {
  const [sessionData, projectData] = await Promise.all([listChatSessions({ chat_type: props.chatType }), listProjects()]);
  sessions.value = sessionData;
  projects.value = projectData;
  if (!activeSessionId.value && sessions.value.length) {
    await selectSession(sessions.value[0]);
  }
}

async function selectSession(session: { id: number; project_id?: number | null }): Promise<void> {
  activeSessionId.value = session.id;
  projectId.value = session.project_id || null;
  const fetchedMessages = await listChatMessages(session.id);
  messages.value = fetchedMessages.map(toUiMessage);
  syncAssistantContext(messages.value);
  await scrollToBottom();
}

function startNewSession(): void {
  if (streaming.value) return;
  activeSessionId.value = null;
  messages.value = [];
  citations.value = [];
  trace.value = [];
  queryScope.value = '';
}

function onProjectChange(value: number | string | Array<number | string> | undefined): void {
  if (Array.isArray(value)) return;
  projectId.value = typeof value === 'number' ? value : value ? Number(value) : null;
  if (props.chatType !== 'project_chat') return;
  startNewSession();
}

function stopStreaming(): void {
  streamAbortController.value?.abort();
}

async function refreshSessionState(sessionId: number): Promise<void> {
  const [sessionData, fetchedMessages] = await Promise.all([
    listChatSessions({ chat_type: props.chatType }),
    listChatMessages(sessionId),
  ]);
  sessions.value = sessionData;
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
      if (currentAssistant) currentAssistant.status = 'error';
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
    streamAbortController.value = null;
    await scrollToBottom();
  }
}

onMounted(loadBaseData);
</script>

<template>
  <PageContainer :title="title" :subtitle="subtitle">
    <div v-if="chatType === 'base_chat' && isExternalUser" class="surface no-access">
      外部用户默认不能访问基础问答，请从项目问答入口进入已授权项目。
    </div>
    <div v-else class="agent-layout">
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
          <t-empty v-if="!sessions.length" size="small" description="暂无会话" />
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
            @change="onProjectChange"
          >
            <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="project.name" />
          </t-select>
          <t-tag v-else variant="light" theme="primary">基础知识库范围</t-tag>
          <span class="notice">{{ notice }}</span>
          <t-tag v-if="currentSession" variant="light" theme="default">会话 #{{ currentSession.id }}</t-tag>
        </div>

        <div ref="chatHistoryRef" class="chat-history">
          <t-empty v-if="!messages.length" description="当前入口只会基于有权限、已审核、已索引资料回答" />
          <div v-for="message in messages" :key="message.id" class="chat-item-row" :class="message.role">
            <TChatMessage
              :role="message.role"
              :name="message.role === 'user' ? '我' : 'Botree Agent'"
              :placement="message.role === 'user' ? 'right' : 'left'"
              :datetime="formatDateTime(message.created_at)"
              :status="message.status"
              variant="outline"
              class="chat-message"
            >
              <TChatContent
                :role="message.role"
                :status="message.status"
                :content="message.role === 'assistant' ? { type: 'markdown', data: message.content } : message.content"
                :markdown-props="assistantContentProps.markdownProps"
              />
            </TChatMessage>

            <div v-if="message.role === 'assistant' && message.citations.length" class="inline-citations">
              <t-tag
                v-for="citation in message.citations.slice(0, 3)"
                :key="`${message.id}-${citation.document_id}-${citation.chunk_id}`"
                size="small"
                variant="light"
                theme="primary"
              >
                {{ citation.file_name }}
                <template v-if="citation.page_number"> P{{ citation.page_number }}</template>
              </t-tag>
            </div>

            <TChatReasoning
              v-if="message.role === 'assistant' && message.agentTrace.length"
              class="message-reasoning"
              :default-collapsed="true"
            >
              <template #header>Agent 执行过程</template>
              <div class="reasoning-list">
                <div v-for="step in message.agentTrace" :key="`${message.id}-${step.step}`" class="reasoning-step">
                  <div class="reasoning-step-header">
                    <strong>{{ step.step }}</strong>
                    <span>{{ step.elapsed_ms ? `${step.elapsed_ms} ms` : '已完成' }}</span>
                  </div>
                  <pre>{{ renderTraceSummary(step) }}</pre>
                </div>
              </div>
            </TChatReasoning>
          </div>
        </div>

        <div class="sender-shell">
          <TChatSender
            v-model="question"
            :loading="streaming"
            :disabled="senderDisabled"
            :stop-disabled="false"
            :send-btn-disabled="senderDisabled"
            placeholder="输入问题"
            :textarea-props="{ autosize: { minRows: 3, maxRows: 6 } }"
            @send="submitQuestion"
            @stop="stopStreaming"
          />
        </div>
      </main>

      <aside class="agent-right surface">
        <t-tabs default-value="citations">
          <t-tab-panel value="citations" label="引用来源">
            <CitationList :citations="citations" :chat-type="chatType" />
          </t-tab-panel>
          <t-tab-panel value="trace" label="执行过程">
            <AgentTracePanel :steps="trace" />
          </t-tab-panel>
          <t-tab-panel value="scope" :label="chatType === 'project_chat' ? '当前知识范围' : '命中的知识库'">
            <div class="scope-panel">
              <div class="scope-title">{{ queryScope || (chatType === 'project_chat' ? '所选项目资料' : '基础知识库资料') }}</div>
              <p v-if="selectedProject">当前项目：{{ selectedProject.name }}（project_id={{ selectedProject.id }}）</p>
              <p v-if="chatType === 'project_chat'">仅检索当前项目资料，不跨项目查询。</p>
              <p v-else>命中知识库：{{ hitKnowledgeBases.join('、') || '暂无命中' }}</p>
            </div>
          </t-tab-panel>
        </t-tabs>
      </aside>
    </div>
  </PageContainer>
</template>

<style scoped>
.agent-layout {
  display: grid;
  grid-template-columns: 280px minmax(0, 1fr) 360px;
  gap: 16px;
  min-height: calc(100vh - 160px);
}

.agent-sidebar,
.agent-right,
.chat-panel,
.no-access {
  padding: 16px;
}

.agent-sidebar,
.chat-panel,
.agent-right,
.no-access {
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
  max-height: calc(100vh - 280px);
  flex-direction: column;
  gap: 8px;
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
  min-height: 0;
  flex-direction: column;
}

.chat-toolbar {
  display: flex;
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
  overflow: auto;
  padding: 8px 4px 16px;
}

.chat-item-row {
  display: flex;
  flex-direction: column;
  margin-bottom: 16px;
}

.chat-item-row.user {
  align-items: flex-end;
}

.chat-message {
  width: min(100%, 780px);
}

.chat-message :deep(.t-chat__text) {
  line-height: 1.8;
  white-space: pre-wrap;
}

.inline-citations,
.message-reasoning {
  width: min(100%, 780px);
}

.inline-citations {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
}

.message-reasoning {
  margin-top: 10px;
}

.reasoning-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.reasoning-step {
  border: 1px solid #eef2f7;
  border-radius: 8px;
  background: #fafcff;
  padding: 12px;
}

.reasoning-step-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
  color: #111827;
  font-size: 13px;
}

.reasoning-step pre {
  margin: 0;
  overflow: auto;
  color: #4b5563;
  font-family: inherit;
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}

.sender-shell {
  border-top: 1px solid #edf0f5;
  padding-top: 16px;
}

.scope-panel {
  color: #4b5563;
  font-size: 13px;
  line-height: 1.7;
}

.scope-title {
  margin-bottom: 10px;
  color: #111827;
  font-weight: 700;
}
</style>
