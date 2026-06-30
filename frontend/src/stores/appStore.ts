/**
 * Botree Knowledge OS App Store
 *
 * 负责：
 * 1. 管理全局 UI 状态与 Mock 业务数据
 * 2. 提供增删改与开关类基础 action
 * 3. 保证后续页面统一从 Zustand 读取数据
 */
import { create } from 'zustand';

import type { AppLanguage } from '@/i18n/dictionary';
import {
  mockAiSessions,
  mockAuthorizationConfigs,
  mockCurrentUser,
  mockKnowledgeDocuments,
  mockProjectFiles,
  mockProjectMembers,
  mockProjects,
} from '@/mocks/mockData';
import type {
  AiMessage,
  AiSession,
  AuthorizationConfig,
  EntityId,
  KnowledgeDocument,
  Project,
  ProjectFile,
  ProjectMember,
  UserInfo,
} from '@/types/domain';

interface AppUiState {
  /**
   * 当前界面语言
   */
  language: AppLanguage;

  /**
   * 侧边区域是否处于收起状态
   */
  sidebarCollapsed: boolean;
}

interface AppDataState {
  /**
   * 当前登录用户信息
   */
  currentUser: UserInfo;

  /**
   * 知识文档列表
   */
  knowledgeDocuments: KnowledgeDocument[];

  /**
   * 项目列表
   */
  projects: Project[];

  /**
   * 项目资料列表
   */
  projectFiles: ProjectFile[];

  /**
   * 项目成员列表
   */
  projectMembers: ProjectMember[];

  /**
   * 知识授权配置列表
   */
  authorizationConfigs: AuthorizationConfig[];

  /**
   * AI 会话列表
   */
  aiSessions: AiSession[];
}

interface AppActions {
  /**
   * 设置当前界面语言
   */
  setLanguage: (language: AppLanguage) => void;

  /**
   * 在中文与英文之间切换
   */
  toggleLanguage: () => void;

  /**
   * 设置侧边区域收起状态
   */
  setSidebarCollapsed: (collapsed: boolean) => void;

  /**
   * 切换侧边区域收起状态
   */
  toggleSidebar: () => void;

  /**
   * 更新当前用户基础信息
   */
  updateCurrentUser: (patch: Partial<UserInfo>) => void;

  /**
   * 新增知识文档
   */
  addKnowledgeDocument: (document: Omit<KnowledgeDocument, 'id'>) => EntityId;

  /**
   * 更新知识文档
   */
  updateKnowledgeDocument: (id: EntityId, patch: Partial<KnowledgeDocument>) => void;

  /**
   * 删除知识文档
   */
  removeKnowledgeDocument: (id: EntityId) => void;

  /**
   * 新增项目
   */
  addProject: (project: Omit<Project, 'id'>) => EntityId;

  /**
   * 更新项目
   */
  updateProject: (id: EntityId, patch: Partial<Project>) => void;

  /**
   * 删除项目
   */
  removeProject: (id: EntityId) => void;

  /**
   * 将项目归档
   */
  archiveProject: (id: EntityId) => void;

  /**
   * 新增项目资料
   */
  addProjectFile: (file: Omit<ProjectFile, 'id'>) => EntityId;

  /**
   * 更新项目资料
   */
  updateProjectFile: (id: EntityId, patch: Partial<ProjectFile>) => void;

  /**
   * 删除项目资料
   */
  removeProjectFile: (id: EntityId) => void;

  /**
   * 切换项目资料外部可见状态
   */
  toggleProjectFileExternalVisible: (id: EntityId) => void;

  /**
   * 新增项目成员
   */
  addProjectMember: (member: Omit<ProjectMember, 'id'>) => EntityId;

  /**
   * 更新项目成员
   */
  updateProjectMember: (id: EntityId, patch: Partial<ProjectMember>) => void;

  /**
   * 删除项目成员
   */
  removeProjectMember: (id: EntityId) => void;

  /**
   * 新增授权配置
   */
  addAuthorizationConfig: (config: AuthorizationConfig) => void;

  /**
   * 更新授权配置
   */
  updateAuthorizationConfig: (projectId: EntityId, category: string, patch: Partial<AuthorizationConfig>) => void;

  /**
   * 删除授权配置
   */
  removeAuthorizationConfig: (projectId: EntityId, category: string) => void;

  /**
   * 切换授权配置外部可见状态
   */
  toggleAuthorizationExternalVisible: (projectId: EntityId, category: string) => void;

  /**
   * 新增 AI 会话
   */
  addAiSession: (session: Omit<AiSession, 'id'>) => EntityId;

  /**
   * 更新 AI 会话
   */
  updateAiSession: (id: EntityId, patch: Partial<AiSession>) => void;

  /**
   * 删除 AI 会话
   */
  removeAiSession: (id: EntityId) => void;

  /**
   * 向指定 AI 会话追加消息
   */
  addAiMessage: (sessionId: EntityId, message: AiMessage) => void;
}

export type AppState = AppUiState & AppDataState & AppActions;

/**
 * 生成 Mock 实体 ID
 *
 * 参数:
 * - prefix: 实体前缀
 *
 * 返回:
 * - 带前缀的唯一字符串 ID
 */
function createMockId(prefix: string): EntityId {
  return `${prefix}-${Date.now()}-${Math.round(Math.random() * 1000)}`;
}

/**
 * 按 ID 更新数组中的实体
 *
 * 参数:
 * - list: 待更新实体列表
 * - id: 目标实体 ID
 * - patch: 更新字段
 *
 * 返回:
 * - 更新后的实体列表
 */
function updateById<T extends { id: EntityId }>(list: T[], id: EntityId, patch: Partial<T>): T[] {
  return list.map((item) => (item.id === id ? { ...item, ...patch } : item));
}

/**
 * 按 ID 删除数组中的实体
 *
 * 参数:
 * - list: 待删除实体列表
 * - id: 目标实体 ID
 *
 * 返回:
 * - 删除后的实体列表
 */
function removeById<T extends { id: EntityId }>(list: T[], id: EntityId): T[] {
  return list.filter((item) => item.id !== id);
}

/**
 * 应用级 Zustand Store
 *
 * 返回:
 * - 全局 UI 状态
 * - Mock 业务数据
 * - 增删改与切换 action
 */
export const useAppStore = create<AppState>((set) => ({
  language: 'zh-CN',
  sidebarCollapsed: false,
  currentUser: mockCurrentUser,
  knowledgeDocuments: mockKnowledgeDocuments,
  projects: mockProjects,
  projectFiles: mockProjectFiles,
  projectMembers: mockProjectMembers,
  authorizationConfigs: mockAuthorizationConfigs,
  aiSessions: mockAiSessions,
  setLanguage: (language) => set({ language }),
  toggleLanguage: () =>
    set((state) => ({
      language: state.language === 'zh-CN' ? 'en-US' : 'zh-CN',
    })),
  setSidebarCollapsed: (collapsed: boolean) => set({ sidebarCollapsed: collapsed }),
  toggleSidebar: () =>
    set((state) => ({
      sidebarCollapsed: !state.sidebarCollapsed,
    })),
  updateCurrentUser: (patch) =>
    set((state) => ({
      currentUser: {
        ...state.currentUser,
        ...patch,
      },
    })),
  addKnowledgeDocument: (document) => {
    const id = createMockId('doc');
    set((state) => ({
      knowledgeDocuments: [{ ...document, id }, ...state.knowledgeDocuments],
    }));
    return id;
  },
  updateKnowledgeDocument: (id, patch) =>
    set((state) => ({
      knowledgeDocuments: updateById(state.knowledgeDocuments, id, patch),
    })),
  removeKnowledgeDocument: (id) =>
    set((state) => ({
      knowledgeDocuments: removeById(state.knowledgeDocuments, id),
    })),
  addProject: (project) => {
    const id = createMockId('project');
    set((state) => ({
      projects: [{ ...project, id }, ...state.projects],
    }));
    return id;
  },
  updateProject: (id, patch) =>
    set((state) => ({
      projects: updateById(state.projects, id, patch),
    })),
  removeProject: (id) =>
    set((state) => ({
      projects: removeById(state.projects, id),
      projectFiles: state.projectFiles.filter((file) => file.projectId !== id),
      projectMembers: state.projectMembers.filter((member) => member.projectId !== id),
      authorizationConfigs: state.authorizationConfigs.filter((config) => config.projectId !== id),
    })),
  archiveProject: (id) =>
    set((state) => ({
      projects: updateById(state.projects, id, { status: 'archived' }),
    })),
  addProjectFile: (file) => {
    const id = createMockId('file');
    set((state) => ({
      projectFiles: [{ ...file, id }, ...state.projectFiles],
    }));
    return id;
  },
  updateProjectFile: (id, patch) =>
    set((state) => ({
      projectFiles: updateById(state.projectFiles, id, patch),
    })),
  removeProjectFile: (id) =>
    set((state) => ({
      projectFiles: removeById(state.projectFiles, id),
    })),
  toggleProjectFileExternalVisible: (id) =>
    set((state) => ({
      projectFiles: state.projectFiles.map((file) =>
        file.id === id ? { ...file, externalVisible: !file.externalVisible } : file,
      ),
    })),
  addProjectMember: (member) => {
    const id = createMockId('member');
    set((state) => ({
      projectMembers: [{ ...member, id }, ...state.projectMembers],
    }));
    return id;
  },
  updateProjectMember: (id, patch) =>
    set((state) => ({
      projectMembers: updateById(state.projectMembers, id, patch),
    })),
  removeProjectMember: (id) =>
    set((state) => ({
      projectMembers: removeById(state.projectMembers, id),
    })),
  addAuthorizationConfig: (config) =>
    set((state) => ({
      authorizationConfigs: [config, ...state.authorizationConfigs],
    })),
  updateAuthorizationConfig: (projectId, category, patch) =>
    set((state) => ({
      authorizationConfigs: state.authorizationConfigs.map((config) =>
        config.projectId === projectId && config.knowledgeCategory === category ? { ...config, ...patch } : config,
      ),
    })),
  removeAuthorizationConfig: (projectId, category) =>
    set((state) => ({
      authorizationConfigs: state.authorizationConfigs.filter(
        (config) => !(config.projectId === projectId && config.knowledgeCategory === category),
      ),
    })),
  toggleAuthorizationExternalVisible: (projectId, category) =>
    set((state) => ({
      authorizationConfigs: state.authorizationConfigs.map((config) =>
        config.projectId === projectId && config.knowledgeCategory === category
          ? { ...config, externalVisible: !config.externalVisible }
          : config,
      ),
    })),
  addAiSession: (session) => {
    const id = createMockId('ai');
    set((state) => ({
      aiSessions: [{ ...session, id }, ...state.aiSessions],
    }));
    return id;
  },
  updateAiSession: (id, patch) =>
    set((state) => ({
      aiSessions: updateById(state.aiSessions, id, patch),
    })),
  removeAiSession: (id) =>
    set((state) => ({
      aiSessions: removeById(state.aiSessions, id),
    })),
  addAiMessage: (sessionId, message) =>
    set((state) => ({
      aiSessions: state.aiSessions.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              messages: [...session.messages, message],
              sources: message.sources?.length ? message.sources : session.sources,
            }
          : session,
      ),
    })),
}));
