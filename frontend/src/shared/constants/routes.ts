/**
 * Botree Knowledge OS Route Constants
 *
 * 负责：
 * 1. 集中维护前端路由路径
 * 2. 避免路由魔法字符串散落在页面与组件中
 * 3. 为后续权限路由扩展保留统一常量
 */

export const ROUTE_PATHS = {
  /**
   * 根路径，进入后重定向到工作台
   */
  root: '/',

  /**
   * 工作台首页路径
   */
  dashboard: '/dashboard',

  /**
   * 知识中心路径
   */
  knowledge: '/knowledge',

  /**
   * 文档详情路径模板
   */
  documentDetail: '/documents/:id',

  /**
   * 项目中心路径
   */
  projects: '/projects',

  /**
   * 项目详情路径模板
   */
  projectDetail: '/projects/:id',

  /**
   * 知识授权中心路径
   */
  authorization: '/authorization',

  /**
   * 审核中心路径
   */
  reviews: '/reviews',

  /**
   * AI 中心项目问答路径。
   */
  aiProjectChat: '/ai/project-chat',

  /**
   * AI 中心基础问答路径。
   */
  aiBaseChat: '/ai/base-chat',

  /**
   * 系统管理路径
   */
  system: '/system',

  /**
   * 问答审计路径
   */
  qaAudit: '/system/qa-audits',
} as const;

export type RoutePath = (typeof ROUTE_PATHS)[keyof typeof ROUTE_PATHS];
