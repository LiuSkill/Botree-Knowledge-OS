import type { ActionPermissionGroup, ActionPermissionInfo, SystemMenuNode } from '@/types/api';

export const MENU_PERMISSIONS = {
  DASHBOARD: 'dashboard',
  KNOWLEDGE: 'knowledge',
  PROJECT: 'project',
  AUTHORIZATION: 'authorization',
  REVIEW: 'review',
  AI_PROJECT_CHAT: 'ai:project-chat',
  AI_BASE_CHAT: 'ai:base-chat',
  SYSTEM_USER: 'system:user',
  SYSTEM_PERMISSION: 'system:permission',
  SYSTEM_MODEL: 'system:model-config',
  SYSTEM_LOG: 'system:operation-log',
  SYSTEM_QA_AUDIT: 'system:qa-audit',
} as const;

export const ACTION_PERMISSIONS = {
  DASHBOARD_VIEW: 'dashboard:view',

  KNOWLEDGE_VIEW: 'knowledge:view',
  KNOWLEDGE_CREATE: 'knowledge:create',
  KNOWLEDGE_EDIT: 'knowledge:edit',
  KNOWLEDGE_DELETE: 'knowledge:delete',
  KNOWLEDGE_UPLOAD: 'knowledge:upload',
  KNOWLEDGE_SUBMIT_REVIEW: 'knowledge:submit-review',
  KNOWLEDGE_DOWNLOAD: 'knowledge:download',

  PROJECT_VIEW: 'project:view',
  PROJECT_CREATE: 'project:create',
  PROJECT_EDIT: 'project:edit',
  PROJECT_DELETE: 'project:delete',
  PROJECT_CHAT: 'project:chat',
  PROJECT_DIRECTORY_CREATE: 'project:directory:create',
  PROJECT_DIRECTORY_EDIT: 'project:directory:edit',
  PROJECT_DIRECTORY_DELETE: 'project:directory:delete',
  PROJECT_UPLOAD: 'project:upload',
  PROJECT_SUBMIT_REVIEW: 'project:submit-review',
  PROJECT_DOCUMENT_EDIT: 'project:document:edit',
  PROJECT_DOCUMENT_DELETE: 'project:document:delete',
  PROJECT_DOCUMENT_PREVIEW: 'project:document:preview',
  PROJECT_DOCUMENT_DOWNLOAD: 'project:document:download',
  PROJECT_DOCUMENT_RETRY_PARSE: 'project:document:retry-parse',
  PROJECT_DOCUMENT_RETRY_INDEX: 'project:document:retry-index',
  PROJECT_DOCUMENT_SECURITY_UPDATE: 'project:document:security-update',
  PROJECT_DOCUMENT_VERSION_VIEW: 'project:document:version-view',
  PROJECT_DOCUMENT_VERSION_CREATE: 'project:document:version-create',
  PROJECT_DOCUMENT_VERSION_SET_CURRENT: 'project:document:version-set-current',

  AUTHORIZATION_VIEW: 'authorization:view',

  REVIEW_VIEW: 'review:view',
  REVIEW_APPROVE: 'review:approve',
  REVIEW_REJECT: 'review:reject',
  REVIEW_BUILD_INDEX: 'review:build-index',

  AI_PROJECT_CHAT_VIEW: 'ai:project-chat:view',
  AI_PROJECT_CHAT_CREATE_SESSION: 'ai:project-chat:create-session',
  AI_PROJECT_CHAT_SEND_MESSAGE: 'ai:project-chat:send-message',
  AI_PROJECT_CHAT_MANAGE_SESSION: 'ai:project-chat:manage-session',
  AI_PROJECT_CHAT_DELETE_SESSION: 'ai:project-chat:delete-session',
  AI_PROJECT_CHAT_FEEDBACK: 'ai:project-chat:feedback',

  AI_BASE_CHAT_VIEW: 'ai:base-chat:view',
  AI_BASE_CHAT_CREATE_SESSION: 'ai:base-chat:create-session',
  AI_BASE_CHAT_SEND_MESSAGE: 'ai:base-chat:send-message',
  AI_BASE_CHAT_MANAGE_SESSION: 'ai:base-chat:manage-session',
  AI_BASE_CHAT_DELETE_SESSION: 'ai:base-chat:delete-session',
  AI_BASE_CHAT_FEEDBACK: 'ai:base-chat:feedback',

  SYSTEM_USER_VIEW: 'system:user:view',
  SYSTEM_USER_CREATE: 'system:user:create',
  SYSTEM_USER_EDIT: 'system:user:edit',
  SYSTEM_USER_DISABLE: 'system:user:disable',
  SYSTEM_USER_RESET_PASSWORD: 'system:user:reset-password',
  SYSTEM_USER_DELETE: 'system:user:delete',

  SYSTEM_PERMISSION_VIEW: 'system:permission:view',
  SYSTEM_PERMISSION_CREATE_ROLE: 'system:permission:create-role',
  SYSTEM_PERMISSION_EDIT_ROLE: 'system:permission:edit-role',
  SYSTEM_PERMISSION_DELETE_ROLE: 'system:permission:delete-role',
  SYSTEM_PERMISSION_SAVE: 'system:permission:save',

  SYSTEM_MODEL_VIEW: 'system:model:view',
  SYSTEM_MODEL_CREATE: 'system:model:create',
  SYSTEM_MODEL_EDIT: 'system:model:edit',
  SYSTEM_MODEL_TEST: 'system:model:test',
  SYSTEM_MODEL_SET_DEFAULT: 'system:model:set-default',
  SYSTEM_MODEL_DELETE: 'system:model:delete',

  SYSTEM_LOG_VIEW: 'system:log:view',
  SYSTEM_QA_AUDIT_VIEW: 'system:qa-audit:view',
} as const;

export const PERMISSIONS = {
  ...MENU_PERMISSIONS,
  ...ACTION_PERMISSIONS,
} as const;

export type MenuPermissionCode = (typeof MENU_PERMISSIONS)[keyof typeof MENU_PERMISSIONS];
export type ActionPermissionCode = (typeof ACTION_PERMISSIONS)[keyof typeof ACTION_PERMISSIONS];
export type PermissionCode = MenuPermissionCode | ActionPermissionCode;

type MenuDefinition = Omit<SystemMenuNode, 'permission_id' | 'children'> & {
  children: MenuDefinition[];
};

type ActionDefinition = Omit<ActionPermissionInfo, 'permission_id'> & {
  code: ActionPermissionCode;
};

export type ActionGroupDefinition = Omit<ActionPermissionGroup, 'actions'> & {
  menu_ids: MenuPermissionCode[];
  actions: ActionDefinition[];
};

export const MENU_PERMISSION_TREE: MenuDefinition[] = [
  { id: MENU_PERMISSIONS.DASHBOARD, name: '首页', path: '/dashboard', children: [] },
  { id: MENU_PERMISSIONS.KNOWLEDGE, name: '知识中心', path: '/knowledge', children: [] },
  { id: MENU_PERMISSIONS.PROJECT, name: '项目中心', path: '/projects', children: [] },
  { id: MENU_PERMISSIONS.AUTHORIZATION, name: '知识授权中心', path: '/authorization', children: [] },
  { id: MENU_PERMISSIONS.REVIEW, name: '审核中心', path: '/reviews', children: [] },
  {
    id: 'ai',
    name: '知识问答',
    path: null,
    children: [
      { id: MENU_PERMISSIONS.AI_PROJECT_CHAT, name: '项目问答', path: '/ai/project-chat', children: [] },
      { id: MENU_PERMISSIONS.AI_BASE_CHAT, name: '基础问答', path: '/ai/base-chat', children: [] },
    ],
  },
  {
    id: 'system',
    name: '系统管理',
    path: '/system',
    children: [
      { id: MENU_PERMISSIONS.SYSTEM_USER, name: '用户管理', path: '/system/users', children: [] },
      { id: MENU_PERMISSIONS.SYSTEM_PERMISSION, name: '权限矩阵', path: '/system/permissions', children: [] },
      { id: MENU_PERMISSIONS.SYSTEM_MODEL, name: '模型配置', path: '/system/model-configs', children: [] },
      { id: MENU_PERMISSIONS.SYSTEM_LOG, name: '操作日志', path: '/system/logs', children: [] },
      { id: MENU_PERMISSIONS.SYSTEM_QA_AUDIT, name: '问答审计', path: '/system/qa-audits', children: [] },
    ],
  },
];

export const ACTION_PERMISSION_GROUPS: ActionGroupDefinition[] = [
  {
    module: 'dashboard',
    module_name: '首页',
    menu_ids: [MENU_PERMISSIONS.DASHBOARD],
    actions: [{ action: 'view', name: '查看首页统计', code: ACTION_PERMISSIONS.DASHBOARD_VIEW }],
  },
  {
    module: 'knowledge',
    module_name: '知识中心',
    menu_ids: [MENU_PERMISSIONS.KNOWLEDGE],
    actions: [
      { action: 'view', name: '查看知识资料', code: ACTION_PERMISSIONS.KNOWLEDGE_VIEW },
      { action: 'create', name: '新增知识分类', code: ACTION_PERMISSIONS.KNOWLEDGE_CREATE },
      { action: 'edit', name: '编辑知识分类/资料', code: ACTION_PERMISSIONS.KNOWLEDGE_EDIT },
      { action: 'upload', name: '上传知识文档', code: ACTION_PERMISSIONS.KNOWLEDGE_UPLOAD },
      { action: 'submit-review', name: '提交知识资料审核', code: ACTION_PERMISSIONS.KNOWLEDGE_SUBMIT_REVIEW },
      { action: 'download', name: '下载知识资料', code: ACTION_PERMISSIONS.KNOWLEDGE_DOWNLOAD },
      { action: 'delete', name: '删除知识资料', code: ACTION_PERMISSIONS.KNOWLEDGE_DELETE },
    ],
  },
  {
    module: 'project',
    module_name: '项目中心',
    menu_ids: [MENU_PERMISSIONS.PROJECT],
    actions: [
      { action: 'view', name: '查看项目/项目资料', code: ACTION_PERMISSIONS.PROJECT_VIEW },
      { action: 'create', name: '新增项目', code: ACTION_PERMISSIONS.PROJECT_CREATE },
      { action: 'edit', name: '编辑项目', code: ACTION_PERMISSIONS.PROJECT_EDIT },
      { action: 'delete', name: '删除项目', code: ACTION_PERMISSIONS.PROJECT_DELETE },
      { action: 'chat', name: '项目问答跳转', code: ACTION_PERMISSIONS.PROJECT_CHAT },
    ],
  },
  {
    module: 'project-directory',
    module_name: '项目资料目录',
    menu_ids: [MENU_PERMISSIONS.PROJECT],
    actions: [
      { action: 'create', name: '新增项目资料目录', code: ACTION_PERMISSIONS.PROJECT_DIRECTORY_CREATE },
      { action: 'edit', name: '编辑项目资料目录', code: ACTION_PERMISSIONS.PROJECT_DIRECTORY_EDIT },
      { action: 'delete', name: '删除项目资料目录', code: ACTION_PERMISSIONS.PROJECT_DIRECTORY_DELETE },
    ],
  },
  {
    module: 'project-document',
    module_name: '项目资料',
    menu_ids: [MENU_PERMISSIONS.PROJECT],
    actions: [
      { action: 'upload', name: '上传项目资料', code: ACTION_PERMISSIONS.PROJECT_UPLOAD },
      { action: 'submit-review', name: '提交/发布项目资料', code: ACTION_PERMISSIONS.PROJECT_SUBMIT_REVIEW },
      { action: 'edit', name: '编辑项目资料元数据', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_EDIT },
      { action: 'delete', name: '删除项目资料', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_DELETE },
      { action: 'preview', name: '预览项目资料', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_PREVIEW },
      { action: 'download', name: '下载项目资料', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_DOWNLOAD },
      { action: 'retry-parse', name: '重试项目资料解析', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_RETRY_PARSE },
      { action: 'retry-index', name: '重试项目资料索引', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_RETRY_INDEX },
      { action: 'security-update', name: '保存项目资料密级', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_SECURITY_UPDATE },
      { action: 'version-view', name: '查看项目资料版本', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_VERSION_VIEW },
      { action: 'version-create', name: '上传项目资料新版本', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_VERSION_CREATE },
      { action: 'version-set-current', name: '设置项目资料当前版本', code: ACTION_PERMISSIONS.PROJECT_DOCUMENT_VERSION_SET_CURRENT },
    ],
  },
  {
    module: 'authorization',
    module_name: '知识授权中心',
    menu_ids: [MENU_PERMISSIONS.AUTHORIZATION],
    actions: [{ action: 'view', name: '查看授权', code: ACTION_PERMISSIONS.AUTHORIZATION_VIEW }],
  },
  {
    module: 'review',
    module_name: '审核中心',
    menu_ids: [MENU_PERMISSIONS.REVIEW],
    actions: [
      { action: 'view', name: '查看审核记录', code: ACTION_PERMISSIONS.REVIEW_VIEW },
      { action: 'approve', name: '审核通过', code: ACTION_PERMISSIONS.REVIEW_APPROVE },
      { action: 'reject', name: '审核驳回', code: ACTION_PERMISSIONS.REVIEW_REJECT },
      { action: 'build-index', name: '解析并构建索引', code: ACTION_PERMISSIONS.REVIEW_BUILD_INDEX },
    ],
  },
  {
    module: 'ai-project-chat',
    module_name: '项目问答',
    menu_ids: [MENU_PERMISSIONS.AI_PROJECT_CHAT],
    actions: [
      { action: 'view', name: '进入项目问答页面', code: ACTION_PERMISSIONS.AI_PROJECT_CHAT_VIEW },
      { action: 'create-session', name: '新建项目问答会话', code: ACTION_PERMISSIONS.AI_PROJECT_CHAT_CREATE_SESSION },
      { action: 'send-message', name: '发送项目问答消息', code: ACTION_PERMISSIONS.AI_PROJECT_CHAT_SEND_MESSAGE },
      { action: 'manage-session', name: '重命名/置顶/收藏项目问答会话', code: ACTION_PERMISSIONS.AI_PROJECT_CHAT_MANAGE_SESSION },
      { action: 'delete-session', name: '删除项目问答会话', code: ACTION_PERMISSIONS.AI_PROJECT_CHAT_DELETE_SESSION },
      { action: 'feedback', name: '反馈项目问答答案', code: ACTION_PERMISSIONS.AI_PROJECT_CHAT_FEEDBACK },
    ],
  },
  {
    module: 'ai-base-chat',
    module_name: '基础问答',
    menu_ids: [MENU_PERMISSIONS.AI_BASE_CHAT],
    actions: [
      { action: 'view', name: '进入基础问答页面', code: ACTION_PERMISSIONS.AI_BASE_CHAT_VIEW },
      { action: 'create-session', name: '新建基础问答会话', code: ACTION_PERMISSIONS.AI_BASE_CHAT_CREATE_SESSION },
      { action: 'send-message', name: '发送基础问答消息', code: ACTION_PERMISSIONS.AI_BASE_CHAT_SEND_MESSAGE },
      { action: 'manage-session', name: '重命名/置顶/收藏基础问答会话', code: ACTION_PERMISSIONS.AI_BASE_CHAT_MANAGE_SESSION },
      { action: 'delete-session', name: '删除基础问答会话', code: ACTION_PERMISSIONS.AI_BASE_CHAT_DELETE_SESSION },
      { action: 'feedback', name: '反馈基础问答答案', code: ACTION_PERMISSIONS.AI_BASE_CHAT_FEEDBACK },
    ],
  },
  {
    module: 'system-user',
    module_name: '用户管理',
    menu_ids: [MENU_PERMISSIONS.SYSTEM_USER],
    actions: [
      { action: 'view', name: '查看用户列表', code: ACTION_PERMISSIONS.SYSTEM_USER_VIEW },
      { action: 'create', name: '新增用户账号', code: ACTION_PERMISSIONS.SYSTEM_USER_CREATE },
      { action: 'edit', name: '编辑用户资料', code: ACTION_PERMISSIONS.SYSTEM_USER_EDIT },
      { action: 'disable', name: '启用/停用用户', code: ACTION_PERMISSIONS.SYSTEM_USER_DISABLE },
      { action: 'reset-password', name: '重置用户密码', code: ACTION_PERMISSIONS.SYSTEM_USER_RESET_PASSWORD },
      { action: 'delete', name: '删除用户账号', code: ACTION_PERMISSIONS.SYSTEM_USER_DELETE },
    ],
  },
  {
    module: 'system-permission',
    module_name: '权限矩阵',
    menu_ids: [MENU_PERMISSIONS.SYSTEM_PERMISSION],
    actions: [
      { action: 'view', name: '查看权限矩阵', code: ACTION_PERMISSIONS.SYSTEM_PERMISSION_VIEW },
      { action: 'create-role', name: '新增角色', code: ACTION_PERMISSIONS.SYSTEM_PERMISSION_CREATE_ROLE },
      { action: 'edit-role', name: '编辑角色', code: ACTION_PERMISSIONS.SYSTEM_PERMISSION_EDIT_ROLE },
      { action: 'delete-role', name: '删除角色', code: ACTION_PERMISSIONS.SYSTEM_PERMISSION_DELETE_ROLE },
      { action: 'save', name: '保存角色权限', code: ACTION_PERMISSIONS.SYSTEM_PERMISSION_SAVE },
    ],
  },
  {
    module: 'system-model',
    module_name: '模型配置',
    menu_ids: [MENU_PERMISSIONS.SYSTEM_MODEL],
    actions: [
      { action: 'view', name: '查看模型配置', code: ACTION_PERMISSIONS.SYSTEM_MODEL_VIEW },
      { action: 'create', name: '新增模型配置', code: ACTION_PERMISSIONS.SYSTEM_MODEL_CREATE },
      { action: 'edit', name: '编辑/启停模型配置', code: ACTION_PERMISSIONS.SYSTEM_MODEL_EDIT },
      { action: 'test', name: '测试模型连接', code: ACTION_PERMISSIONS.SYSTEM_MODEL_TEST },
      { action: 'set-default', name: '设置默认模型', code: ACTION_PERMISSIONS.SYSTEM_MODEL_SET_DEFAULT },
      { action: 'delete', name: '删除模型配置', code: ACTION_PERMISSIONS.SYSTEM_MODEL_DELETE },
    ],
  },
  {
    module: 'system-log',
    module_name: '操作日志',
    menu_ids: [MENU_PERMISSIONS.SYSTEM_LOG],
    actions: [{ action: 'view', name: '查看操作日志', code: ACTION_PERMISSIONS.SYSTEM_LOG_VIEW }],
  },
  {
    module: 'system-qa-audit',
    module_name: '问答审计',
    menu_ids: [MENU_PERMISSIONS.SYSTEM_QA_AUDIT],
    actions: [{ action: 'view', name: '查看问答审计', code: ACTION_PERMISSIONS.SYSTEM_QA_AUDIT_VIEW }],
  },
];

export const MENU_PERMISSION_CODES = Object.values(MENU_PERMISSIONS);
export const ACTION_PERMISSION_CODES = Object.values(ACTION_PERMISSIONS);
export const CURRENT_PERMISSION_CODES = [...MENU_PERMISSION_CODES, ...ACTION_PERMISSION_CODES];
export const CURRENT_PERMISSION_CODE_SET = new Set<string>(CURRENT_PERMISSION_CODES);
