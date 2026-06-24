/**
 * Chat API Client
 *
 * 负责：
 * 1. 会话列表和消息列表
 * 2. 同步知识问答请求
 * 3. 流式知识问答请求
 */

import { request } from '@/api/request';
import type {
  ChatCompletionResult,
  ChatMessage,
  ChatSession,
  ChatStreamDoneEvent,
  ChatStreamMeta,
  ChatTraceDeltaEvent,
} from '@/types/api';
import { getToken } from '@/utils/auth';

const apiBaseUrl = (import.meta.env.VITE_API_BASE_URL || '/api').replace(/\/$/, '');

export interface AskKnowledgeAgentPayload {
  chat_type: 'project_chat' | 'base_chat';
  mode: string;
  project_id?: number | null;
  session_id?: number | null;
  message: string;
  agent_enabled: boolean;
}

export type ChatFeedbackStatus = 'like' | 'dislike' | null;

interface StreamEventHandlers {
  signal?: AbortSignal;
  onMeta?: (payload: ChatStreamMeta) => void;
  onTraceDelta?: (payload: ChatTraceDeltaEvent) => void;
  onDelta?: (content: string) => void;
  onDone?: (payload: ChatStreamDoneEvent) => void;
}

function resolveApiUrl(path: string): string {
  if (apiBaseUrl.startsWith('http://') || apiBaseUrl.startsWith('https://')) {
    return `${apiBaseUrl}${path}`;
  }
  return `${window.location.origin}${apiBaseUrl}${path}`;
}

function extractErrorMessage(payload: unknown, fallback: string): string {
  if (typeof payload === 'object' && payload && 'message' in payload && typeof payload.message === 'string') {
    return payload.message;
  }
  return fallback;
}

function parseEventBlock(
  block: string,
  handlers: StreamEventHandlers,
): { done: boolean } {
  const lines = block
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  if (!lines.length) return { done: false };

  let event = 'message';
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith('event:')) {
      event = line.slice(6).trim();
      continue;
    }
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trim());
    }
  }

  const rawData = dataLines.join('\n');
  const payload = rawData ? (JSON.parse(rawData) as Record<string, unknown>) : {};
  if (event === 'meta') {
    handlers.onMeta?.(payload as unknown as ChatStreamMeta);
    return { done: false };
  }
  if (event === 'delta') {
    handlers.onDelta?.(typeof payload.content === 'string' ? payload.content : '');
    return { done: false };
  }
  if (event === 'trace_delta') {
    handlers.onTraceDelta?.(payload as unknown as ChatTraceDeltaEvent);
    return { done: false };
  }
  if (event === 'done') {
    handlers.onDone?.(payload as unknown as ChatStreamDoneEvent);
    return { done: true };
  }
  if (event === 'error') {
    throw new Error(extractErrorMessage(payload, '流式问答失败'));
  }
  return { done: false };
}

export function listChatSessions(params?: {
  chat_type?: 'project_chat' | 'base_chat';
  project_id?: number | null;
}): Promise<ChatSession[]> {
  return request.get('/chat/sessions', { params }) as Promise<ChatSession[]>;
}

export function createChatSession(payload: {
  title: string;
  chat_type: 'project_chat' | 'base_chat';
  mode: string;
  project_id?: number | null;
}): Promise<ChatSession> {
  return request.post('/chat/sessions', payload) as Promise<ChatSession>;
}

export function updateChatSession(
  sessionId: number,
  payload: {
    title?: string;
    is_pinned?: boolean;
    is_favorite?: boolean;
  },
): Promise<ChatSession> {
  return request.patch(`/chat/sessions/${sessionId}`, payload) as Promise<ChatSession>;
}

export function listChatMessages(sessionId: number): Promise<ChatMessage[]> {
  return request.get(`/chat/sessions/${sessionId}/messages`) as Promise<ChatMessage[]>;
}

export function deleteChatSession(sessionId: number): Promise<{ deleted: boolean }> {
  return request.delete(`/chat/sessions/${sessionId}`) as Promise<{ deleted: boolean }>;
}

export function askKnowledgeAgent(payload: AskKnowledgeAgentPayload): Promise<ChatCompletionResult> {
  return request.post('/chat/completions', payload) as Promise<ChatCompletionResult>;
}

export function updateMessageFeedback(
  messageId: number,
  feedbackStatus: ChatFeedbackStatus,
): Promise<{ message_id: number; feedback_status: ChatFeedbackStatus }> {
  return request.patch(`/chat/messages/${messageId}/feedback`, { feedback_status: feedbackStatus }) as Promise<{
    message_id: number;
    feedback_status: ChatFeedbackStatus;
  }>;
}

export async function streamKnowledgeAgent(payload: AskKnowledgeAgentPayload, handlers: StreamEventHandlers): Promise<void> {
  const token = getToken();
  const response = await fetch(resolveApiUrl('/chat/completions/stream'), {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(payload),
    signal: handlers.signal,
  });

  if (!response.ok) {
    let errorPayload: unknown = null;
    try {
      errorPayload = await response.json();
    } catch {
      errorPayload = null;
    }
    throw new Error(extractErrorMessage(errorPayload, `流式问答请求失败: HTTP ${response.status}`));
  }
  if (!response.body) {
    throw new Error('当前浏览器环境不支持流式响应');
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

    const blocks = buffer.split('\n\n');
    buffer = blocks.pop() || '';
    for (const block of blocks) {
      const result = parseEventBlock(block, handlers);
      if (result.done) {
        await reader.cancel();
        return;
      }
    }

    if (done) {
      if (buffer.trim()) {
        parseEventBlock(buffer, handlers);
      }
      return;
    }
  }
}
