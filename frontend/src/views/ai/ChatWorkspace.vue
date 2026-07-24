<!--
  Chat Workspace

  负责：
  1. 复用项目问答和基础问答布局
  2. 使用 TDesign Chat 组件承载消息和发送器
  3. 接入后端流式问答，并展示引用来源、处理进度和知识范围
-->
<script setup lang="ts">
import { ChatContent as TChatContent, ChatMessage as TChatMessage, ChatSender as TChatSender } from '@tdesign-vue-next/chat';
import {
  AddIcon,
  ChevronDownSIcon,
  ChevronRightSIcon,
  CloseIcon,
  DeleteIcon,
  EditIcon,
  EllipsisIcon,
  PinFilledIcon,
  PinIcon,
  QuoteIcon,
  StarFilledIcon,
  StarIcon,
  TaskIcon,
  ThumbDownIcon,
  ThumbUpIcon,
} from 'tdesign-icons-vue-next';
import { MessagePlugin } from 'tdesign-vue-next';
import { computed, nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue';
import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router';

import {
  deleteChatSession,
  getMessageTrace,
  listChatMessages,
  listChatSessions,
  streamKnowledgeAgent,
  updateChatSession,
  updateMessageFeedback,
  type ChatFeedbackStatus,
} from '@/api/chat';
import { listProjects } from '@/api/projects';
import botreeLogo from '@/assets/botree-logo.png';
import AgentTracePanel from '@/components/AgentTracePanel.vue';
import ChatRichContent from '@/components/ChatRichContent.vue';
import CitationList from '@/components/CitationList.vue';
import ProcessingProgressPanel from '@/components/ProcessingProgressPanel.vue';
import { showConfirmDialog } from '@/utils/confirmDialog';
import UserAvatar from '@/components/UserAvatar.vue';
import { PERMISSIONS } from '@/constants/permissions';
import { useAuthStore } from '@/stores/auth';
import { useChatRunStore, type ChatRunState } from '@/stores/chatRun';
import type {
  AgentTraceStep,
  ChatMessage,
  ChatProgressEvent,
  ChatSession,
  ChatStreamDoneEvent,
  ChatTraceDeltaEvent,
  Citation,
  ProjectInfo,
} from '@/types/api';
import {
  markProgressComplete,
  mergeProgressEvent,
  parseProgressJson,
  progressEventFromTrace,
  progressEventsFromTrace,
  normalizeProgressEvents,
} from '@/utils/chatProgress';

interface UiChatMessage extends Omit<ChatMessage, 'id' | 'citations'> {
  id: number | string;
  citations: Citation[];
  progressEvents: ChatProgressEvent[];
  status?: '' | 'streaming' | 'complete' | 'stop' | 'error';
  streaming?: boolean;
  securityNotice?: string | null;
}

type DetailMode = 'citations' | 'trace';
type SessionGroupKey = 'pinned' | 'recent' | 'favorite';

const props = defineProps<{
  chatType: 'project_chat' | 'base_chat';
  notice: string;
  requireProject: boolean;
}>();

const authStore = useAuthStore();
const chatRunStore = useChatRunStore();
const route = useRoute();
const router = useRouter();
const sessions = ref<ChatSession[]>([]);
const messages = ref<UiChatMessage[]>([]);
const projects = ref<ProjectInfo[]>([]);
const projectsLoaded = ref(false);
const activeSessionId = ref<number | null>(null);
const projectId = ref<number | null>(null);
const question = ref('');
const streaming = ref(false);
const processingSessionId = ref<number | null>(null);
const citations = ref<Citation[]>([]);
const trace = ref<ChatProgressEvent[]>([]);
const queryScope = ref('');
const chatHistoryRef = ref<HTMLElement | null>(null);
const senderShellRef = ref<HTMLElement | null>(null);
const activeDetailMode = ref<DetailMode | null>(null);
const activeDetailMessageId = ref<number | string | null>(null);
const feedbackUpdatingMap = ref<Record<number, boolean>>({});
const openSessionMenuId = ref<number | null>(null);
const renamingSession = ref<ChatSession | null>(null);
const renameTitle = ref('');
const renameDialogVisible = ref(false);
const renameSubmitting = ref(false);
const collapsedSessionGroups = ref<Record<SessionGroupKey, boolean>>({
  pinned: false,
  recent: false,
  favorite: false,
});
const traceDetailCache = ref<Record<number, AgentTraceStep[] | null>>({});
const traceDetailLoadingMap = ref<Record<number, boolean>>({});
const traceDetailErrorMap = ref<Record<number, string>>({});
// 正文通过插槽渲染，外层 TChatMessage 保持空状态，避免底层加载态替换插槽内容。
const chatMessageStatus = '';

const chatPermissionSet = computed(() => {
  if (props.chatType === 'project_chat') {
    return {
      view: PERMISSIONS.AI_PROJECT_CHAT_VIEW,
      createSession: PERMISSIONS.AI_PROJECT_CHAT_CREATE_SESSION,
      sendMessage: PERMISSIONS.AI_PROJECT_CHAT_SEND_MESSAGE,
      manageSession: PERMISSIONS.AI_PROJECT_CHAT_MANAGE_SESSION,
      deleteSession: PERMISSIONS.AI_PROJECT_CHAT_DELETE_SESSION,
      feedback: PERMISSIONS.AI_PROJECT_CHAT_FEEDBACK,
    };
  }
  return {
    view: PERMISSIONS.AI_BASE_CHAT_VIEW,
    createSession: PERMISSIONS.AI_BASE_CHAT_CREATE_SESSION,
    sendMessage: PERMISSIONS.AI_BASE_CHAT_SEND_MESSAGE,
    manageSession: PERMISSIONS.AI_BASE_CHAT_MANAGE_SESSION,
    deleteSession: PERMISSIONS.AI_BASE_CHAT_DELETE_SESSION,
    feedback: PERMISSIONS.AI_BASE_CHAT_FEEDBACK,
  };
});

const isExternalUser = computed(() =>
  Boolean(authStore.user?.roles.some((role) => role.code === 'external' || role.name.includes('外部'))),
);
const canViewChat = computed(() => authStore.hasActionPermission(chatPermissionSet.value.view));
const canCreateSession = computed(() => authStore.hasActionPermission(chatPermissionSet.value.createSession));
const canSendMessage = computed(() => authStore.hasActionPermission(chatPermissionSet.value.sendMessage));
const canManageSession = computed(() => authStore.hasActionPermission(chatPermissionSet.value.manageSession));
const canDeleteSession = computed(() => authStore.hasActionPermission(chatPermissionSet.value.deleteSession));
const canFeedbackMessage = computed(() => authStore.hasActionPermission(chatPermissionSet.value.feedback));
const hasRunningChat = computed(() => chatRunStore.runs[props.chatType]?.status === 'running');
const senderDisabled = computed(
  () =>
    streaming.value ||
    hasRunningChat.value ||
    !canSendMessage.value ||
    (props.requireProject && !projectId.value) ||
    (props.chatType === 'base_chat' && isExternalUser.value),
);
const newSessionDisabled = computed(
  () =>
    streaming.value ||
    hasRunningChat.value ||
    !canCreateSession.value ||
    (props.requireProject && !projectId.value),
);
const sessionEmptyDescription = computed(() => {
  if (props.chatType === 'project_chat' && !projectsLoaded.value) return '正在加载项目';
  if (props.chatType === 'project_chat' && !projects.value.length) return '暂无可访问项目';
  if (props.chatType === 'project_chat' && !projectId.value) return '请先选择项目';
  return '暂无会话';
});
const chatEmptyDescription = computed(() => {
  if (props.chatType === 'project_chat' && !projectsLoaded.value) return '正在加载项目问答';
  if (props.chatType === 'project_chat' && !projects.value.length) return '暂无可访问项目，无法发起项目问答';
  return '当前入口只会基于有权限、已审核、已索引资料回答';
});
const projectSelectPlaceholder = computed(() => {
  if (!projectsLoaded.value) return '正在加载项目';
  return projects.value.length ? '请选择项目' : '暂无可访问项目';
});
const userAvatarLabel = computed(() => authStore.user?.real_name || authStore.user?.username || 'User');
const activeDetailMessage = computed(
  () => messages.value.find((item) => item.role === 'assistant' && item.id === activeDetailMessageId.value) || null,
);
const isDetailOpen = computed(() => Boolean(activeDetailMode.value && activeDetailMessage.value));
const detailPanelTitle = computed(() => (activeDetailMode.value === 'citations' ? '引用来源' : '生成过程'));
const activeDetailCitations = computed(() => activeDetailMessage.value?.citations || []);
const activeDetailQuestion = computed(() => (activeDetailMessage.value ? questionForAssistant(activeDetailMessage.value) : ''));
const activeTraceMessageId = computed(() => (typeof activeDetailMessageId.value === 'number' ? activeDetailMessageId.value : null));
const activeDetailTraceState = computed(() => {
  const messageId = activeTraceMessageId.value;
  if (messageId === null) {
    return { steps: [] as AgentTraceStep[], loaded: false, loading: false, error: '' };
  }
  return {
    steps: traceDetailCache.value[messageId] || [],
    loaded: Object.prototype.hasOwnProperty.call(traceDetailCache.value, messageId),
    loading: Boolean(traceDetailLoadingMap.value[messageId]),
    error: traceDetailErrorMap.value[messageId] || '',
  };
});
const sessionGroups = computed(() => {
  const pinnedSessions = sessions.value.filter((session) => session.is_pinned);
  const recentSessions = sessions.value.filter((session) => !session.is_pinned && !session.is_favorite);
  const favoriteSessions = sessions.value.filter((session) => session.is_favorite);
  const groups: Array<{ key: SessionGroupKey; title: string; items: ChatSession[] }> = [
    { key: 'pinned', title: '置顶', items: pinnedSessions },
    { key: 'recent', title: '最近', items: recentSessions },
    { key: 'favorite', title: '收藏', items: favoriteSessions },
  ];
  return groups.filter((group) => group.items.length > 0);
});

function toggleSessionGroup(groupKey: SessionGroupKey): void {
  collapsedSessionGroups.value = {
    ...collapsedSessionGroups.value,
    [groupKey]: !collapsedSessionGroups.value[groupKey],
  };
}

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
  const fallbackTrace = parseAgentTrace(message.agent_trace_json);
  const progressEvents = parseProgressJson(message.progress_json);
  return {
    ...message,
    id: message.id,
    citations: message.citations || [],
    progressEvents: progressEvents.length ? progressEvents : progressEventsFromTrace(fallbackTrace, Boolean(message.content.trim())),
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
    progress_json: null,
    feedback_status: null,
    citations: [],
    progressEvents: [],
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

function applyProgressEvent(assistantId: number | string, payload: ChatProgressEvent | null): void {
  if (!payload) return;
  const currentAssistant = messages.value.find((item) => item.id === assistantId);
  trace.value = mergeProgressEvent(trace.value, payload);
  if (!currentAssistant) return;
  currentAssistant.progressEvents = mergeProgressEvent(currentAssistant.progressEvents, payload);
}

function chatContentStatus(message: UiChatMessage): '' | 'error' {
  return message.status === 'error' ? 'error' : '';
}

function shouldShowProgress(message: UiChatMessage): boolean {
  return message.role === 'assistant' && (message.streaming || message.progressEvents.length > 0);
}

function streamingAssistantFromRun(run: ChatRunState): UiChatMessage {
  return {
    id: run.assistantMessageId,
    session_id: run.sessionId || 0,
    role: 'assistant',
    content: run.answer,
    query_scope: run.queryScope,
    agent_trace_json: null,
    progress_json: null,
    feedback_status: null,
    citations: run.citations,
    progressEvents: run.progressEvents,
    created_at: run.startedAt,
    status: 'streaming',
    streaming: true,
    securityNotice: run.securityNotice,
  };
}

function syncRunningSnapshot(run: ChatRunState): void {
  if (run.status !== 'running') return;
  streaming.value = true;
  processingSessionId.value = run.sessionId;
  if (run.sessionId) {
    activeSessionId.value = run.sessionId;
    showStreamingSession(run.sessionId, run.question, run.projectId);
  }
  if (props.chatType === 'project_chat') {
    projectId.value = run.projectId;
  }
  citations.value = run.citations;
  trace.value = run.progressEvents;
  queryScope.value = run.queryScope;

  let currentAssistant = messages.value.find((item) => item.id === run.assistantMessageId);
  if (!currentAssistant) {
    currentAssistant = streamingAssistantFromRun(run);
    messages.value = [...messages.value, currentAssistant];
  }
  currentAssistant.session_id = run.sessionId || 0;
  currentAssistant.content = run.answer;
  currentAssistant.query_scope = run.queryScope;
  currentAssistant.citations = run.citations;
  currentAssistant.progressEvents = run.progressEvents;
  currentAssistant.securityNotice = run.securityNotice;
  currentAssistant.status = 'streaming';
  currentAssistant.streaming = true;
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
  if (mode === 'trace') {
    void loadDetailTrace(message);
  }
  void focusQuestionInput();
}

async function loadDetailTrace(message: UiChatMessage): Promise<void> {
  if (typeof message.id !== 'number') return;
  const messageId = message.id;
  if (
    Object.prototype.hasOwnProperty.call(traceDetailCache.value, messageId) ||
    traceDetailLoadingMap.value[messageId]
  ) {
    return;
  }

  traceDetailErrorMap.value = { ...traceDetailErrorMap.value, [messageId]: '' };
  traceDetailLoadingMap.value = { ...traceDetailLoadingMap.value, [messageId]: true };
  try {
    const detail = await getMessageTrace(messageId);
    const steps = parseAgentTrace(detail.trace_json);
    traceDetailCache.value = { ...traceDetailCache.value, [messageId]: steps.length ? steps : null };
  } catch (error) {
    traceDetailErrorMap.value = {
      ...traceDetailErrorMap.value,
      [messageId]: error instanceof Error ? error.message : '生成过程加载失败',
    };
  } finally {
    const { [messageId]: _removed, ...remaining } = traceDetailLoadingMap.value;
    traceDetailLoadingMap.value = remaining;
  }
}

function isDetailButtonActive(message: UiChatMessage, mode: DetailMode): boolean {
  return activeDetailMessageId.value === message.id && activeDetailMode.value === mode;
}

function isFeedbackUpdating(message: UiChatMessage): boolean {
  return typeof message.id === 'number' && Boolean(feedbackUpdatingMap.value[message.id]);
}

async function handleFeedbackClick(message: UiChatMessage, feedbackStatus: Exclude<ChatFeedbackStatus, null>): Promise<void> {
  if (!shouldShowAssistantActions(message) || typeof message.id !== 'number' || isFeedbackUpdating(message)) return;
  if (!canFeedbackMessage.value) {
    MessagePlugin.warning('无权限反馈答案');
    return;
  }
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
  trace.value = latestAssistant?.progressEvents || [];
}

function resetConversationState(): void {
  closeDetailPanel();
  closeSessionMenu();
  activeSessionId.value = null;
  messages.value = [];
  citations.value = [];
  trace.value = [];
  queryScope.value = '';
}

function projectOptionLabel(project: ProjectInfo): string {
  return project.project_name || project.name || `项目 #${project.id}`;
}

function parseProjectIdValue(value: unknown): number | null {
  const rawValue = Array.isArray(value) ? value[0] : value;
  if (rawValue === null || rawValue === undefined || rawValue === '') return null;
  const numericValue = Number(rawValue);
  return Number.isInteger(numericValue) && numericValue > 0 ? numericValue : null;
}

function routeProjectId(): number | null {
  return parseProjectIdValue(route.query.projectId ?? route.query.project_id);
}

function hasRouteProjectQuery(): boolean {
  return route.query.projectId !== undefined || route.query.project_id !== undefined;
}

function resolveAccessibleProjectId(requestedProjectId: number | null): number | null {
  if (!projects.value.length) return null;
  if (requestedProjectId && projects.value.some((project) => project.id === requestedProjectId)) return requestedProjectId;
  return projects.value[0].id;
}

function replaceProjectQuery(nextProjectId: number | null): void {
  const nextQuery: LocationQueryRaw = { ...route.query };
  delete nextQuery.project_id;
  if (nextProjectId) {
    nextQuery.projectId = String(nextProjectId);
  } else {
    delete nextQuery.projectId;
  }
  void router.replace({ path: route.path, query: nextQuery });
}

async function applyProjectSelection(nextProjectId: number | null, forceReload = false): Promise<void> {
  if (props.chatType !== 'project_chat') return;
  if (!forceReload && projectId.value === nextProjectId) return;

  projectId.value = nextProjectId;
  resetConversationState();
  const loadedSessions = await loadSessionsForCurrentProject();
  if (loadedSessions.length) {
    await selectSession(loadedSessions[0]);
    return;
  }
  await focusQuestionInput();
}

async function applyRouteProjectSelection(forceReload = false): Promise<void> {
  const requestedProjectId = routeProjectId();
  const routeHasProject = hasRouteProjectQuery();
  const nextProjectId = resolveAccessibleProjectId(requestedProjectId);
  const shouldWarnFallback = routeHasProject && nextProjectId !== null && nextProjectId !== requestedProjectId;

  if (shouldWarnFallback) {
    MessagePlugin.info('当前项目无权限或不存在，已切换到第一个可访问项目');
  }

  await applyProjectSelection(nextProjectId, forceReload);
  if (routeHasProject && nextProjectId !== requestedProjectId) {
    replaceProjectQuery(nextProjectId);
  }
}

async function loadSessionsForCurrentProject(): Promise<ChatSession[]> {
  if (!canViewChat.value) {
    sessions.value = [];
    return sessions.value;
  }
  if (props.chatType === 'project_chat' && projectId.value === null) {
    sessions.value = [];
    return sessions.value;
  }

  const params: { chat_type: 'project_chat' | 'base_chat'; project_id?: number } = { chat_type: props.chatType };
  if (props.chatType === 'project_chat' && projectId.value !== null) {
    params.project_id = projectId.value;
  }
  sessions.value = sortSessions(await listChatSessions(params));
  return sessions.value;
}

async function loadBaseData(): Promise<void> {
  if (!canViewChat.value) {
    projects.value = [];
    projectsLoaded.value = true;
    sessions.value = [];
    return;
  }
  projects.value = props.requireProject ? await listProjects() : [];
  projectsLoaded.value = true;
  if (props.chatType === 'project_chat') {
    await applyRouteProjectSelection(true);
  } else {
    await loadSessionsForCurrentProject();
  }
  if (props.chatType === 'base_chat' && !activeSessionId.value && sessions.value.length) {
    await selectSession(sessions.value[0]);
  }
  await focusQuestionInput();
}

async function selectSession(session: ChatSession): Promise<void> {
  if (!canViewChat.value) {
    MessagePlugin.warning('无权限查看会话');
    return;
  }
  closeDetailPanel();
  closeSessionMenu();
  activeSessionId.value = session.id;
  if (props.chatType === 'project_chat') {
    projectId.value = session.project_id || projectId.value;
  } else {
    projectId.value = session.project_id || null;
  }
  const fetchedMessages = await listChatMessages(session.id);
  messages.value = fetchedMessages.map(toUiMessage);
  syncAssistantContext(messages.value);
  await scrollToBottom();
  await focusQuestionInput();
}

function startNewSession(): void {
  if (streaming.value || hasRunningChat.value) return;
  if (!canCreateSession.value) {
    MessagePlugin.warning('无权限新建会话');
    return;
  }
  if (props.requireProject && !projectId.value) {
    MessagePlugin.warning(projects.value.length ? '请先选择项目' : '暂无可访问项目');
    return;
  }
  resetConversationState();
  void focusQuestionInput();
}

function sortSessions(items: ChatSession[]): ChatSession[] {
  return [...items].sort((left, right) => {
    if (left.is_pinned !== right.is_pinned) return left.is_pinned ? -1 : 1;
    const timeDiff = Date.parse(right.updated_at || right.created_at) - Date.parse(left.updated_at || left.created_at);
    return timeDiff || right.id - left.id;
  });
}

function replaceSession(updatedSession: ChatSession): void {
  const nextSessions = sessions.value.map((session) => (session.id === updatedSession.id ? updatedSession : session));
  if (!nextSessions.some((session) => session.id === updatedSession.id)) {
    nextSessions.push(updatedSession);
  }
  sessions.value = sortSessions(nextSessions);
}

function showStreamingSession(sessionId: number, title: string, currentProjectId: number | null): void {
  if (sessions.value.some((session) => session.id === sessionId)) return;
  const createdAt = new Date().toISOString();
  replaceSession({
    id: sessionId,
    user_id: authStore.user?.id || 0,
    title: title.slice(0, 30) || '新的知识问答',
    chat_type: props.chatType,
    mode: 'auto',
    project_id: currentProjectId,
    is_pinned: false,
    is_favorite: false,
    created_at: createdAt,
    updated_at: createdAt,
  });
}

function closeSessionMenu(): void {
  openSessionMenuId.value = null;
}

function toggleSessionMenu(sessionId: number): void {
  if (!canManageSession.value && !canDeleteSession.value) return;
  openSessionMenuId.value = openSessionMenuId.value === sessionId ? null : sessionId;
}

async function togglePinnedSession(session: ChatSession): Promise<void> {
  if (!canManageSession.value) {
    MessagePlugin.warning('无权限管理会话');
    return;
  }
  closeSessionMenu();
  try {
    replaceSession(await updateChatSession(session.id, { is_pinned: !session.is_pinned }));
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '置顶状态更新失败');
  } finally {
    await focusQuestionInput();
  }
}

async function toggleFavoriteSession(session: ChatSession): Promise<void> {
  if (!canManageSession.value) {
    MessagePlugin.warning('无权限管理会话');
    return;
  }
  closeSessionMenu();
  try {
    replaceSession(await updateChatSession(session.id, { is_favorite: !session.is_favorite }));
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '收藏状态更新失败');
  } finally {
    await focusQuestionInput();
  }
}

function openRenameSessionDialog(session: ChatSession): void {
  if (!canManageSession.value) {
    MessagePlugin.warning('无权限管理会话');
    return;
  }
  closeSessionMenu();
  renamingSession.value = session;
  renameTitle.value = session.title;
  renameDialogVisible.value = true;
}

async function confirmRenameSession(): Promise<void> {
  if (!renamingSession.value || renameSubmitting.value) return;
  if (!canManageSession.value) {
    MessagePlugin.warning('无权限管理会话');
    return;
  }
  const title = renameTitle.value.trim();
  if (!title) {
    MessagePlugin.warning('会话名称不能为空');
    return;
  }

  renameSubmitting.value = true;
  try {
    replaceSession(await updateChatSession(renamingSession.value.id, { title }));
    renameDialogVisible.value = false;
    renamingSession.value = null;
    renameTitle.value = '';
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '会话重命名失败');
  } finally {
    renameSubmitting.value = false;
    await focusQuestionInput();
  }
}

async function confirmRemoveSession(session: ChatSession): Promise<void> {
  closeSessionMenu();
  if (!canDeleteSession.value) {
    MessagePlugin.warning('无权限删除会话');
    return;
  }
  if (streaming.value && session.id === activeSessionId.value) {
    MessagePlugin.warning('当前会话正在回答中，暂不能删除');
    return;
  }
  const confirmed = await showConfirmDialog({
    header: '确认删除会话',
    body: `确认删除会话“${session.title}”吗？`,
    theme: 'danger',
    confirmBtn: '删除',
  });
  if (!confirmed) {
    await focusQuestionInput();
    return;
  }

  try {
    await deleteChatSession(session.id);
    sessions.value = sessions.value.filter((item) => item.id !== session.id);
    if (activeSessionId.value === session.id) {
      activeSessionId.value = null;
      messages.value = [];
      citations.value = [];
      trace.value = [];
      queryScope.value = '';
      closeDetailPanel();
    }
    MessagePlugin.success('会话已删除');
  } catch (error) {
    MessagePlugin.error(error instanceof Error ? error.message : '会话删除失败');
  } finally {
    await focusQuestionInput();
  }
}

async function onProjectChange(value: number | string | Array<number | string> | null | undefined): Promise<void> {
  if (Array.isArray(value)) return;
  if (props.chatType !== 'project_chat') return;
  const nextProjectId = resolveAccessibleProjectId(parseProjectIdValue(value));
  await applyProjectSelection(nextProjectId);
  replaceProjectQuery(nextProjectId);
}

function stopStreaming(): void {
  streaming.value = false;
  processingSessionId.value = null;
  trace.value = [];
  const currentAssistant = [...messages.value].reverse().find(
    (item) => item.role === 'assistant' && item.streaming,
  );
  if (currentAssistant) {
    currentAssistant.streaming = false;
    currentAssistant.status = 'stop';
    currentAssistant.progressEvents = [];
    if (!currentAssistant.content.trim()) {
      currentAssistant.content = '已停止生成';
    }
  }
  chatRunStore.stopRun(props.chatType);
}

async function restoreChatRun(): Promise<void> {
  const run = chatRunStore.runs[props.chatType];
  if (!run) return;
  if (run.status !== 'running') {
    if (run.sessionId) await refreshSessionState(run.sessionId);
    chatRunStore.clearRun(props.chatType);
    return;
  }

  if (run.sessionId) {
    if (props.chatType === 'project_chat') projectId.value = run.projectId;
    await refreshSessionState(run.sessionId);
  } else if (!messages.value.some((item) => item.id === run.userMessageId)) {
    messages.value = [
      ...messages.value,
      {
        id: run.userMessageId,
        session_id: 0,
        role: 'user',
        content: run.question,
        query_scope: null,
        agent_trace_json: null,
        citations: [],
        progressEvents: [],
        created_at: run.startedAt,
        status: '',
        streaming: false,
      },
    ];
  }
  syncRunningSnapshot(run);
  await scrollToBottom();
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
  const currentProjectId = props.chatType === 'project_chat' ? projectId.value : null;
  if (!canSendMessage.value) {
    MessagePlugin.warning('无权限发送消息');
    return;
  }
  if (props.requireProject && !currentProjectId) {
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
  if (streaming.value || hasRunningChat.value) return;

  const userMessage: UiChatMessage = {
    id: `stream-user-${Date.now()}`,
    session_id: activeSessionId.value || 0,
    role: 'user',
    content,
    query_scope: null,
    agent_trace_json: null,
    citations: [],
    progressEvents: [],
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
  const streamController = new AbortController();
  chatRunStore.startRun({
    chatType: props.chatType,
    projectId: currentProjectId,
    sessionId: activeSessionId.value,
    userMessageId: String(userMessage.id),
    assistantMessageId: String(assistantId),
    question: originalQuestion,
    controller: streamController,
  });
  await scrollToBottom();

  try {
    await streamKnowledgeAgent(
      {
        chat_type: props.chatType,
        mode: 'auto',
        project_id: currentProjectId,
        session_id: activeSessionId.value,
        message: originalQuestion,
        agent_enabled: true,
      },
      {
        signal: streamController.signal,
        onMeta: (payload) => {
          chatRunStore.bindSession(
            props.chatType,
            payload.session_id,
            payload.query_scope,
            payload.citations,
            payload.progress_events || [],
          );
          activeSessionId.value = payload.session_id;
          processingSessionId.value = payload.session_id;
          showStreamingSession(payload.session_id, originalQuestion, currentProjectId);
          citations.value = payload.citations;
          trace.value = normalizeProgressEvents(payload.progress_events || []);
          queryScope.value = payload.query_scope;
          const currentUser = messages.value.find((item) => item.id === userMessage.id);
          if (currentUser) currentUser.session_id = payload.session_id;
          const currentAssistant = messages.value.find((item) => item.id === assistantId);
          if (!currentAssistant) return;
          currentAssistant.session_id = payload.session_id;
          currentAssistant.query_scope = payload.query_scope;
          currentAssistant.citations = payload.citations;
          currentAssistant.progressEvents = trace.value;
        },
        onProgress: (payload) => {
          chatRunStore.mergeProgress(props.chatType, payload);
          applyProgressEvent(assistantId, payload);
          void scrollToBottom();
        },
        onTraceDelta: (payload) => {
          const progress = progressEventFromTrace(payload);
          chatRunStore.mergeProgress(props.chatType, progress);
          applyProgressEvent(assistantId, progress);
          void scrollToBottom();
        },
        onDelta: (delta) => {
          if (!delta) return;
          chatRunStore.appendAnswer(props.chatType, delta);
          const currentAssistant = messages.value.find((item) => item.id === assistantId);
          if (!currentAssistant) return;
          currentAssistant.content += delta;
          void scrollToBottom();
        },
        onDone: (payload) => {
          finalResult = payload;
          citations.value = payload.citations;
          trace.value = payload.progress_events?.length
            ? markProgressComplete(payload.progress_events)
            : progressEventsFromTrace(payload.agent_trace || [], true);
          queryScope.value = payload.query_scope;
          const currentAssistant = messages.value.find((item) => item.id === assistantId);
          if (currentAssistant) currentAssistant.securityNotice = payload.security_notice;
        },
      },
    );

    if (finalResult) {
      chatRunStore.completeRun(props.chatType, {
        sessionId: finalResult.session_id,
        queryScope: finalResult.query_scope,
        citations: finalResult.citations,
        progressEvents: finalResult.progress_events?.length
          ? markProgressComplete(finalResult.progress_events)
          : progressEventsFromTrace(finalResult.agent_trace || [], true),
        securityNotice: finalResult.security_notice,
      });
      await refreshSessionState(finalResult.session_id);
      const latestAssistant = [...messages.value].reverse().find((item) => item.role === 'assistant');
      if (latestAssistant) latestAssistant.securityNotice = finalResult.security_notice;
    }
  } catch (error) {
    const currentAssistant = messages.value.find((item) => item.id === assistantId);
    if (error instanceof DOMException && error.name === 'AbortError') {
      chatRunStore.stopRun(props.chatType);
      if (currentAssistant && !currentAssistant.content.trim()) {
        currentAssistant.content = '已停止生成';
      }
      if (currentAssistant) {
        currentAssistant.status = 'stop';
        currentAssistant.streaming = false;
        currentAssistant.progressEvents = [];
      }
      MessagePlugin.info('已停止本次回答生成');
      return;
    }
    chatRunStore.failRun(props.chatType);
    if (currentAssistant) {
      currentAssistant.status = 'error';
      if (!currentAssistant.content.trim()) {
        currentAssistant.content = '回答生成失败，请重试。';
      }
    }
    MessagePlugin.error(error instanceof Error ? error.message : '问答失败');
  } finally {
    streaming.value = false;
    processingSessionId.value = null;
    const currentAssistant = messages.value.find((item) => item.id === assistantId);
    if (currentAssistant) {
      currentAssistant.streaming = false;
      if (currentAssistant.status === 'streaming') {
        currentAssistant.status = currentAssistant.content.trim() ? 'complete' : '';
      }
    }
    await scrollToBottom();
    await focusQuestionInput();
  }
}

onMounted(() => {
  void (async () => {
    await loadBaseData();
    await restoreChatRun();
  })();
  document.addEventListener('click', closeSessionMenu);
});

watch(
  () => chatRunStore.runs[props.chatType],
  (run) => {
    if (!run) return;
    if (run.status === 'running') {
      syncRunningSnapshot(run);
      void scrollToBottom();
      return;
    }
    streaming.value = false;
    processingSessionId.value = null;
    if (run.status === 'completed' && run.sessionId) {
      void refreshSessionState(run.sessionId).then(() => chatRunStore.clearRun(props.chatType));
    }
  },
  { deep: true },
);

watch(
  () => [route.query.projectId, route.query.project_id],
  () => {
    if (props.chatType !== 'project_chat' || !projectsLoaded.value) return;
    void applyRouteProjectSelection();
  },
);

onBeforeUnmount(() => {
  document.removeEventListener('click', closeSessionMenu);
});
</script>

<template>
  <section class="chat-workspace-page">
    <div v-if="!canViewChat" class="surface no-access">
      无权限访问当前问答入口。
    </div>
    <div v-else-if="chatType === 'base_chat' && isExternalUser" class="surface no-access">
      外部用户默认不能访问基础问答，请从项目问答入口进入已授权项目。
    </div>
    <div v-else class="agent-layout" :class="{ 'with-detail': isDetailOpen }">
      <aside class="agent-sidebar surface">
        <div class="sidebar-header">
          <div class="agent-title">{{ chatType === 'project_chat' ? '项目问答会话' : '基础问答会话' }}</div>
          <t-select
            v-if="requireProject"
            :model-value="projectId"
            :placeholder="projectSelectPlaceholder"
            class="sidebar-project-select"
            :disabled="streaming || !projects.length"
            @change="onProjectChange"
          >
            <t-option v-for="project in projects" :key="project.id" :value="project.id" :label="projectOptionLabel(project)" />
          </t-select>
          <t-button
            v-permission="chatPermissionSet.createSession"
            block
            theme="primary"
            class="new-session-button"
            :disabled="newSessionDisabled"
            @click="startNewSession"
          >
            <template #icon><AddIcon /></template>
            新建对话
          </t-button>
        </div>
        <div class="session-list">
          <section v-for="group in sessionGroups" :key="group.key" class="session-group">
            <button
              type="button"
              class="session-group-title"
              :aria-expanded="!collapsedSessionGroups[group.key]"
              @click="toggleSessionGroup(group.key)"
            >
              <ChevronRightSIcon v-if="collapsedSessionGroups[group.key]" />
              <ChevronDownSIcon v-else />
              <span>{{ group.title }}</span>
            </button>
            <div
              v-for="session in group.items"
              v-show="!collapsedSessionGroups[group.key]"
              :key="`${group.key}-${session.id}`"
              class="session-item"
              :class="{ active: session.id === activeSessionId, 'menu-open': openSessionMenuId === session.id }"
              role="button"
              tabindex="0"
              @click="selectSession(session)"
              @keydown.enter.prevent="selectSession(session)"
              @keydown.space.prevent="selectSession(session)"
            >
              <span v-if="processingSessionId === session.id" class="session-processing" role="status" aria-live="polite">
                <span class="session-processing-spinner" aria-hidden="true" />
                <span>正在处理</span>
              </span>
              <span v-else class="session-title-text" :title="session.title">{{ session.title }}</span>
              <div v-if="processingSessionId !== session.id && (canManageSession || canDeleteSession)" class="session-actions" @click.stop>
                <t-tooltip v-if="canManageSession" :content="session.is_pinned ? '取消置顶' : '置顶'">
                  <button type="button" class="session-icon-button" @click.stop="togglePinnedSession(session)">
                    <PinFilledIcon v-if="session.is_pinned" />
                    <PinIcon v-else />
                  </button>
                </t-tooltip>
                <div v-if="canManageSession || canDeleteSession" class="session-menu-wrap">
                  <button type="button" class="session-icon-button" @click.stop="toggleSessionMenu(session.id)">
                    <EllipsisIcon />
                  </button>
                  <div v-if="openSessionMenuId === session.id" class="session-menu">
                    <button v-if="canManageSession" type="button" class="session-menu-item" @click.stop="openRenameSessionDialog(session)">
                      <EditIcon />
                      <span>重命名</span>
                    </button>
                    <button v-if="canManageSession" type="button" class="session-menu-item" @click.stop="toggleFavoriteSession(session)">
                      <component :is="session.is_favorite ? StarFilledIcon : StarIcon" />
                      <span>{{ session.is_favorite ? '取消收藏' : '收藏' }}</span>
                    </button>
                    <button v-if="canDeleteSession" type="button" class="session-menu-item danger" @click.stop="confirmRemoveSession(session)">
                      <DeleteIcon />
                      <span>删除</span>
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </section>
          <t-empty v-if="!sessions.length" size="small" :description="sessionEmptyDescription" />
        </div>
      </aside>

      <main class="chat-panel surface">
        <div ref="chatHistoryRef" class="chat-history">
          <t-empty v-if="!messages.length" :description="chatEmptyDescription" />
          <div v-for="message in messages" :key="message.id" class="chat-item-row" :class="message.role">
            <div v-if="message.role === 'assistant'" class="assistant-chat-row">
              <span class="chat-avatar assistant" aria-label="Botree AI" role="img">
                <img :src="botreeLogo" alt="" />
              </span>
              <div class="assistant-chat-stack">
                <ProcessingProgressPanel
                  v-if="shouldShowProgress(message)"
                  class="message-progress"
                  :class="{ 'with-answer': Boolean(message.content.trim()) }"
                  :events="message.progressEvents"
                  :streaming="message.streaming"
                  :title="message.content.trim() ? '处理过程' : '正在处理...'"
                  :collapsible="true"
                  :default-collapsed="Boolean(message.content.trim())"
                />

                <TChatMessage
                  v-if="message.content"
                  :role="message.role"
                  placement="left"
                  :status="chatMessageStatus"
                  variant="outline"
                  class="chat-message assistant-chat-message"
                >
                  <ChatRichContent :content="normalizeMarkdownDisplay(message.content)" />
                  <div v-if="message.securityNotice" class="sensitive-security-notice">
                    {{ message.securityNotice }}
                  </div>
                  <div v-if="shouldShowAssistantActions(message)" class="message-action-bar">
                    <t-tooltip v-if="canFeedbackMessage" content="点赞">
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
                    <t-tooltip v-if="canFeedbackMessage" content="点踩">
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
                    <t-tooltip content="生成过程">
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

        <div ref="senderShellRef" v-permission="chatPermissionSet.sendMessage" class="sender-shell">
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
          <div v-else-if="activeDetailMode === 'trace'" class="detail-trace-panel">
            <div v-if="activeDetailTraceState.loading" class="detail-trace-loading">正在加载生成过程...</div>
            <div v-else-if="activeDetailTraceState.error" class="detail-trace-error">
              {{ activeDetailTraceState.error }}
            </div>
            <AgentTracePanel v-else-if="activeDetailTraceState.steps.length" :steps="activeDetailTraceState.steps" />
            <t-empty v-else size="small" description="暂无生成过程记录" />
          </div>
        </div>
      </aside>
    </div>

    <t-dialog
      v-model:visible="renameDialogVisible"
      header="重命名会话"
      width="420px"
      :confirm-btn="{ content: '保存', loading: renameSubmitting }"
      @confirm="confirmRenameSession"
      @close="renamingSession = null"
    >
      <t-input v-model="renameTitle" placeholder="请输入会话名称" maxlength="100" autofocus />
    </t-dialog>
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

.sidebar-project-select,
.new-session-button {
  width: 100%;
}

.session-list {
  display: flex;
  flex: 1;
  flex-direction: column;
  gap: 4px;
  min-height: 0;
  overflow: auto;
  padding-right: 2px;
  scrollbar-width: none;
}

.session-list::-webkit-scrollbar {
  width: 0;
  height: 0;
}

.session-group-title {
  display: flex;
  width: calc(100% - 8px);
  align-items: center;
  border: 0;
  background: transparent;
  margin: 8px 4px 4px;
  color: #64748b;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  gap: 4px;
  line-height: 20px;
  padding: 0;
  text-align: left;
}

.session-group-title:hover {
  color: #334155;
}

.session-group-title:focus-visible {
  border-radius: 4px;
  outline: 2px solid #2563eb;
  outline-offset: 2px;
}

.session-group-title svg {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
}

.session-item {
  position: relative;
  display: flex;
  width: 100%;
  min-height: 38px;
  align-items: center;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: #0f172a;
  cursor: pointer;
  gap: 8px;
  outline: none;
  padding: 0 6px 0 12px;
  text-align: left;
}

.session-item:hover,
.session-item:focus-visible,
.session-item.menu-open {
  background: #f1f5f9;
}

.session-title-text {
  min-width: 0;
  overflow: hidden;
  flex: 1;
  font-size: 14px;
  line-height: 38px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.session-processing {
  display: inline-flex;
  min-width: 0;
  height: 38px;
  flex: 1;
  align-items: center;
  color: #2563eb;
  font-size: 14px;
  gap: 8px;
}

.session-processing-spinner {
  width: 14px;
  height: 14px;
  flex: 0 0 auto;
  border: 2px solid #bfdbfe;
  border-top-color: #2563eb;
  border-radius: 50%;
  animation: session-processing-spin 0.8s linear infinite;
}

@keyframes session-processing-spin {
  to {
    transform: rotate(360deg);
  }
}

@media (prefers-reduced-motion: reduce) {
  .session-processing-spinner {
    animation-duration: 1.8s;
  }
}

.session-item.active {
  background: #eaf2ff;
  color: #1d4ed8;
  font-weight: 700;
}

.session-actions {
  display: inline-flex;
  flex: 0 0 auto;
  align-items: center;
  gap: 2px;
  opacity: 0;
  transition: opacity 0.16s ease;
}

.session-item:hover .session-actions,
.session-item:focus-within .session-actions,
.session-item.menu-open .session-actions {
  opacity: 1;
}

.session-icon-button {
  display: inline-flex;
  width: 26px;
  height: 26px;
  align-items: center;
  justify-content: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #64748b;
  cursor: pointer;
  padding: 0;
}

.session-icon-button:hover {
  background: #e2e8f0;
  color: #1d4ed8;
}

.session-icon-button svg {
  width: 16px;
  height: 16px;
}

.session-menu-wrap {
  position: relative;
}

.session-menu {
  position: absolute;
  top: 30px;
  right: 0;
  z-index: 20;
  min-width: 120px;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 12px 28px rgba(15, 23, 42, 0.14);
  padding: 6px;
}

.session-menu-item {
  display: flex;
  width: 100%;
  height: 32px;
  align-items: center;
  border: 0;
  border-radius: 6px;
  background: transparent;
  color: #334155;
  cursor: pointer;
  gap: 8px;
  padding: 0 8px;
  text-align: left;
}

.session-menu-item:hover {
  background: #f1f5f9;
  color: #1d4ed8;
}

.session-menu-item.danger {
  color: #dc2626;
}

.session-menu-item.danger:hover {
  background: #fff1f2;
  color: #b91c1c;
}

.session-menu-item svg {
  width: 15px;
  height: 15px;
  flex: 0 0 auto;
}

.session-menu-item span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chat-panel {
  display: flex;
  flex-direction: column;
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

.message-progress {
  width: 100%;
  margin-bottom: 8px;
}

.sensitive-security-notice {
  margin-top: 8px;
  color: var(--td-text-color-secondary);
  font-size: 12px;
  line-height: 20px;
}

.message-progress.with-answer {
  border-bottom: 1px solid #edf0f5;
  margin-bottom: 10px;
  padding-bottom: 8px;
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

.detail-trace-panel {
  min-height: 0;
}

.detail-trace-loading,
.detail-trace-error {
  border: 1px solid #e5eaf3;
  border-radius: 8px;
  background: #f8fafc;
  color: #64748b;
  font-size: 13px;
  line-height: 1.6;
  padding: 12px;
}

.detail-trace-error {
  border-color: #f3d6d4;
  background: #fff7f6;
  color: #b42318;
}

</style>
