/**
 * Botree Knowledge OS Domain Types
 *
 * 负责：
 * 1. 统一声明前端 Mock 阶段的领域模型
 * 2. 约束 Zustand Store 与页面组件的数据结构
 * 3. 为后续对接后端 API 保留清晰的数据契约
 */

export type EntityId = string;

export type KnowledgeCategory =
  | '电池基础'
  | 'LFP回收'
  | 'NCM回收'
  | '黑粉处理'
  | '湿法冶金'
  | '工艺设计'
  | '工艺开发'
  | '设备'
  | 'EHS'
  | '标准规范';

export type SecurityLevel = 'Public' | 'Internal' | 'Confidential';

export type ParseStatus = 'pending' | 'processing' | 'completed' | 'failed' | 'archived';

export type ProjectStatus = 'pending' | 'active' | 'completed' | 'archived';

export type MemberStatus = 'active' | 'disabled' | 'expired';

export type UserType = 'internal' | 'customer' | 'supplier' | 'epc';

export type AuthorizationStatus = 'enabled' | 'pending_approval' | 'revoked';

export type AiMode = 'enterprise' | 'project';

export type ExpertType = '工艺专家' | '研发专家' | '设备专家' | 'EHS专家' | '项目专家';

export interface UserInfo {
  /**
   * 当前用户姓名
   */
  name: string;

  /**
   * 当前用户角色
   */
  role: string;

  /**
   * 当前用户所属部门
   */
  department: string;

  /**
   * 当前用户头像地址，可为空
   */
  avatar: string;
}

export interface KnowledgeDocument {
  /**
   * 文档唯一 ID
   */
  id: EntityId;

  /**
   * 文档标题
   */
  title: string;

  /**
   * 文档分类
   */
  category: KnowledgeCategory;

  /**
   * 文档标签
   */
  tags: string[];

  /**
   * 上传人
   */
  author: string;

  /**
   * 上传时间
   */
  uploadTime: string;

  /**
   * 文件大小
   */
  fileSize: string;

  /**
   * 解析状态
   */
  parseStatus: ParseStatus;

  /**
   * 文档密级
   */
  securityLevel: SecurityLevel;

  /**
   * 是否参与 AI 问答
   */
  aiEnabled: boolean;

  /**
   * 文档摘要
   */
  summary: string;

  /**
   * 文档版本
   */
  version: string;

  /**
   * 可选所属项目 ID
   */
  projectId?: EntityId;

  /**
   * 向量化状态说明
   */
  vectorStatus: string;

  /**
   * 关联文档标题列表
   */
  relatedDocuments: string[];

  /**
   * 引用记录列表
   */
  citations: string[];
}

export interface Project {
  /**
   * 项目唯一 ID
   */
  id: EntityId;

  /**
   * 项目名称
   */
  name: string;

  /**
   * 客户名称
   */
  client: string;

  /**
   * 项目负责人
   */
  manager: string;

  /**
   * 项目状态
   */
  status: ProjectStatus;

  /**
   * 项目文档数量
   */
  documentCount: number;

  /**
   * 项目知识数量
   */
  knowledgeCount: number;

  /**
   * 项目进度百分比
   */
  progress: number;

  /**
   * 最近更新时间
   */
  updateTime: string;
}

export interface ProjectFile {
  /**
   * 资料唯一 ID
   */
  id: EntityId;

  /**
   * 所属项目 ID
   */
  projectId: EntityId;

  /**
   * 所属资料目录
   */
  folder: string;

  /**
   * 文件名称
   */
  fileName: string;

  /**
   * 文件类型
   */
  type: string;

  /**
   * 文件版本
   */
  version: string;

  /**
   * 上传人
   */
  uploader: string;

  /**
   * 上传时间
   */
  uploadTime: string;

  /**
   * 外部用户是否可见
   */
  externalVisible: boolean;
}

export interface ProjectMember {
  /**
   * 成员唯一 ID
   */
  id: EntityId;

  /**
   * 所属项目 ID
   */
  projectId: EntityId;

  /**
   * 成员姓名
   */
  name: string;

  /**
   * 成员所属单位
   */
  company: string;

  /**
   * 项目角色
   */
  role: string;

  /**
   * 权限说明
   */
  permission: string;

  /**
   * 权限有效期
   */
  expireAt: string;

  /**
   * 成员状态
   */
  status: MemberStatus;

  /**
   * 用户类型
   */
  userType: UserType;
}

export interface AuthorizationConfig {
  /**
   * 授权所属项目 ID
   */
  projectId: EntityId;

  /**
   * 授权知识分类
   */
  knowledgeCategory: KnowledgeCategory;

  /**
   * 授权密级
   */
  level: SecurityLevel;

  /**
   * 外部用户是否可见
   */
  externalVisible: boolean;

  /**
   * 授权有效期
   */
  expireAt: string;

  /**
   * 授权状态
   */
  status: AuthorizationStatus;
}

export interface AiSource {
  /**
   * 引用来源 ID
   */
  id: EntityId;

  /**
   * 关联项目 ID，用于 GraphRAG 来源追踪
   */
  projectId: EntityId;

  /**
   * 关联文档 ID，用于 GraphRAG 来源追踪
   */
  documentId: EntityId;

  /**
   * 图纸编号，用于 GraphRAG 来源追踪
   */
  drawingNo: string;

  /**
   * 页码，用于 GraphRAG 来源追踪
   */
  pageNo: number;

  /**
   * Chunk ID，用于 GraphRAG 来源追踪
   */
  chunkId: EntityId;

  /**
   * 来源标题
   */
  title: string;

  /**
   * 来源摘要
   */
  snippet: string;
}

export interface AiMessage {
  /**
   * 消息唯一 ID
   */
  id: EntityId;

  /**
   * 消息发送方
   */
  role: 'user' | 'assistant';

  /**
   * 消息正文
   */
  content: string;

  /**
   * 消息创建时间
   */
  createdAt: string;

  /**
   * AI 回复引用来源
   */
  sources?: AiSource[];
}

export interface AiSession {
  /**
   * 会话唯一 ID
   */
  id: EntityId;

  /**
   * 会话模式
   */
  mode: AiMode;

  /**
   * 专家类型
   */
  expertType: ExpertType;

  /**
   * 项目模式下关联的项目 ID
   */
  projectId?: EntityId;

  /**
   * 会话标题
   */
  title: string;

  /**
   * 会话消息列表
   */
  messages: AiMessage[];

  /**
   * 会话级引用来源列表
   */
  sources: AiSource[];
}
