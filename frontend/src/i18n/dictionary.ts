/**
 * Botree Knowledge OS I18n Dictionary
 *
 * 负责：
 * 1. 定义轻量级中英文界面文本字典
 * 2. 避免在页面内散落语言判断逻辑
 * 3. 为后续替换成熟国际化方案保留统一入口
 */

export type AppLanguage = 'zh-CN' | 'en-US';

const EN_US_DICTIONARY: Record<string, string> = {
  首页: 'Dashboard',
  知识中心: 'Knowledge Center',
  项目中心: 'Project Center',
  知识授权中心: 'Knowledge Authorization',
  AI中心: 'AI Center',
  系统管理: 'System Management',
  '搜索项目、文档、知识条目': 'Search projects, documents, knowledge',
  中文: '中文',
  English: 'English',
  个人中心: 'Profile',
  退出登录: 'Sign Out',
  上传文档: 'Upload Document',
  新建项目: 'New Project',
  上传资料: 'Upload File',
  新建文件夹: 'New Folder',
  打包导出: 'Export Package',
  添加成员: 'Add Member',
  配置授权: 'Configure Authorization',
  权限预览: 'Permission Preview',
  新增用户: 'Add User',
  新增角色: 'Add Role',
  新增部门: 'Add Department',
  发送: 'Send',
  新建会话: 'New Session',
  工作台: 'Workspace',
  知识文档数: 'Documents',
  知识条目数: 'Knowledge Items',
  项目数量: 'Projects',
  AI问答次数: 'AI Q&A',
  企业知识问答: 'Enterprise Q&A',
  项目知识问答: 'Project Q&A',
  最近上传文档: 'Recent Documents',
  最近AI问答: 'Recent AI Q&A',
  知识建设进度: 'Knowledge Progress',
  上传: 'Upload',
  创建: 'Create',
  保存: 'Save',
  取消: 'Cancel',
  重置: 'Reset',
  详情: 'Detail',
  预览: 'Preview',
  下载: 'Download',
  归档: 'Archive',
  反馈: 'Feedback',
  复制: 'Copy',
  点赞: 'Like',
  点踩: 'Dislike',
  进入项目问答: 'Enter Project Q&A',
  授权当前分类: 'Authorize Category',
  保存授权: 'Save Authorization',
  概览: 'Overview',
  项目资料: 'Project Files',
  项目成员: 'Project Members',
  项目知识库: 'Project Knowledge',
  项目问答: 'Project Q&A',
  授权管理: 'Authorization',
  用户管理: 'Users',
  角色管理: 'Roles',
  权限矩阵: 'Permission Matrix',
  部门管理: 'Departments',
  操作日志: 'Operation Logs',
  问答审计: 'Q&A Audit',
  文档名称: 'Document Name',
  文档详情: 'Document Detail',
  分类: 'Category',
  标签: 'Tags',
  上传人: 'Uploader',
  上传时间: 'Upload Time',
  文件大小: 'File Size',
  解析状态: 'Parse Status',
  密级: 'Security',
  操作: 'Actions',
  文件名: 'File Name',
  类型: 'Type',
  版本: 'Version',
  外部可见: 'External Visible',
  姓名: 'Name',
  单位: 'Company',
  角色: 'Role',
  权限: 'Permission',
  有效期: 'Expire At',
  状态: 'Status',
  用户类型: 'User Type',
  项目文档: 'Project Document',
  项目问答可用: 'Project Q&A',
  AI问答: 'AI Q&A',
  授权分类: 'Authorized Category',
  授权级别: 'Authorization Level',
  用户: 'User',
  对象: 'Target',
  操作人: 'Operator',
  操作类型: 'Action Type',
  时间: 'Time',
  结果: 'Result',
  问题: 'Question',
  回答摘要: 'Answer Summary',
  引用来源: 'Sources',
  模式: 'Mode',
  角色名称: 'Role Name',
  说明: 'Description',
  权限项: 'Permissions',
  部门名称: 'Department Name',
  负责人: 'Owner',
  成员数: 'Members',
  邮箱: 'Email',
  部门: 'Department',
  创建时间: 'Created At',
  账号: 'Account',
  模块: 'Module',
  查看: 'View',
  新增: 'Create',
  编辑: 'Edit',
  删除: 'Delete',
  启用: 'Enable',
  禁用: 'Disable',
  重置密码: 'Reset Password',
  分配角色: 'Assign Role',
  分配项目: 'Assign Project',
  配置权限: 'Configure Permissions',
  审核: 'Audit',
  授权: 'Authorize',
  首页工作台: 'Dashboard',
  知识文档管理: 'Knowledge Documents',
  项目知识建设: 'Project Knowledge Building',
  项目继承专业知识授权: 'Project Knowledge Authorization',
  历史会话: 'Conversation History',
  '组织、权限与审计': 'Organization, Permissions and Audit',
};

const ZH_CN_DICTIONARY: Record<string, string> = {};

const DICTIONARIES: Record<AppLanguage, Record<string, string>> = {
  'zh-CN': ZH_CN_DICTIONARY,
  'en-US': EN_US_DICTIONARY,
};

/**
 * 翻译界面文本
 *
 * 参数:
 * - language: 当前语言
 * - key: 字典 key
 *
 * 返回:
 * - 当前语言下的展示文本；缺失时返回原 key
 */
export function translate(language: AppLanguage, key: string): string {
  return DICTIONARIES[language][key] || key;
}
