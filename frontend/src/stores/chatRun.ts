/**
 * 问答运行状态 Store
 *
 * 流式请求的生命周期长于问答页面组件，状态必须保存在全局 Store 中，
 * 才能在站内路由跳转后继续展示进度并允许用户停止生成。
 */

import { defineStore } from 'pinia';

import type { ChatProgressEvent, Citation } from '@/types/api';
import { mergeProgressEvent, normalizeProgressEvents } from '@/utils/chatProgress';

export type ChatRunType = 'project_chat' | 'base_chat';
export type ChatRunStatus = 'running' | 'completed' | 'stopped' | 'failed';

export interface ChatRunState {
  chatType: ChatRunType;
  projectId: number | null;
  sessionId: number | null;
  userMessageId: string;
  assistantMessageId: string;
  question: string;
  answer: string;
  queryScope: string;
  citations: Citation[];
  progressEvents: ChatProgressEvent[];
  securityNotice: string | null;
  status: ChatRunStatus;
  startedAt: string;
}

interface StartChatRunPayload {
  chatType: ChatRunType;
  projectId: number | null;
  sessionId: number | null;
  userMessageId: string;
  assistantMessageId: string;
  question: string;
  controller: AbortController;
}

const controllers = new Map<ChatRunType, AbortController>();

export const useChatRunStore = defineStore('chat-run', {
  state: () => ({
    runs: {
      project_chat: null,
      base_chat: null,
    } as Record<ChatRunType, ChatRunState | null>,
  }),
  actions: {
    startRun(payload: StartChatRunPayload): void {
      controllers.set(payload.chatType, payload.controller);
      this.runs[payload.chatType] = {
        chatType: payload.chatType,
        projectId: payload.projectId,
        sessionId: payload.sessionId,
        userMessageId: payload.userMessageId,
        assistantMessageId: payload.assistantMessageId,
        question: payload.question,
        answer: '',
        queryScope: '',
        citations: [],
        progressEvents: [],
        securityNotice: null,
        status: 'running',
        startedAt: new Date().toISOString(),
      };
    },
    bindSession(
      chatType: ChatRunType,
      sessionId: number,
      queryScope: string,
      citations: Citation[],
      progressEvents: ChatProgressEvent[],
    ): void {
      const run = this.runs[chatType];
      if (!run || run.status !== 'running') return;
      run.sessionId = sessionId;
      run.queryScope = queryScope;
      run.citations = citations;
      run.progressEvents = normalizeProgressEvents(progressEvents);
    },
    mergeProgress(chatType: ChatRunType, progress: ChatProgressEvent | null): void {
      const run = this.runs[chatType];
      if (!run || run.status !== 'running' || !progress) return;
      run.progressEvents = mergeProgressEvent(run.progressEvents, progress);
    },
    appendAnswer(chatType: ChatRunType, delta: string): void {
      const run = this.runs[chatType];
      if (!run || run.status !== 'running') return;
      run.answer += delta;
    },
    completeRun(
      chatType: ChatRunType,
      payload: Pick<ChatRunState, 'sessionId' | 'queryScope' | 'citations' | 'progressEvents' | 'securityNotice'>,
    ): void {
      const run = this.runs[chatType];
      if (!run) return;
      Object.assign(run, payload, { status: 'completed' as const });
      controllers.delete(chatType);
    },
    failRun(chatType: ChatRunType): void {
      const run = this.runs[chatType];
      if (!run) return;
      run.status = 'failed';
      controllers.delete(chatType);
    },
    stopRun(chatType: ChatRunType): void {
      const run = this.runs[chatType];
      if (run) {
        run.status = 'stopped';
        run.progressEvents = [];
      }
      controllers.get(chatType)?.abort();
      controllers.delete(chatType);
    },
    clearRun(chatType: ChatRunType): void {
      controllers.delete(chatType);
      this.runs[chatType] = null;
    },
    clearAllRuns(): void {
      controllers.forEach((controller) => controller.abort());
      controllers.clear();
      this.runs.project_chat = null;
      this.runs.base_chat = null;
    },
  },
});
