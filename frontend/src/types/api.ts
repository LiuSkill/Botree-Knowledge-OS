/**
 * Botree Knowledge OS API Types
 *
 * 负责：
 * 1. 定义前端使用的后端响应类型
 * 2. 统一核心业务实体字段
 * 3. 避免页面中散落魔法字段
 */

export interface ApiResponse<T> {
  code: number;
  message: string;
  data: T;
}

export interface RoleBrief {
  id: number;
  name: string;
  code: string;
  enabled: boolean;
}

export interface UserInfo {
  id: number;
  username: string;
  real_name: string;
  email?: string | null;
  phone?: string | null;
  department?: string | null;
  status: 'enabled' | 'disabled' | string;
  avatar_url?: string | null;
  avatar_updated_at?: string | null;
  roles: RoleBrief[];
  permission_codes?: string[];
  permissions?: CurrentPermissions;
}

export interface RoleInfo extends RoleBrief {
  description?: string | null;
  enabled: boolean;
  permissions?: PermissionInfo[];
}

export interface PermissionInfo {
  id: number;
  module: string;
  action: string;
  code: string;
  description?: string | null;
}

export interface ProjectInfo {
  id: number;
  name: string;
  code: string;
  description?: string | null;
  client?: string | null;
  manager?: string | null;
  status: string;
  progress: number;
  knowledge_base_id?: number | null;
  document_count: number;
  knowledge_count: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeBaseInfo {
  id: number;
  name: string;
  code: string;
  type: 'base' | 'project';
  project_id?: number | null;
  description?: string | null;
  visibility: string;
  enabled: boolean;
  document_count?: number;
  chunk_count?: number;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCategory {
  id: number;
  scope_type: 'base' | 'project';
  project_id?: number | null;
  parent_id?: number | null;
  name: string;
  code: string;
  description?: string | null;
  sort_order: number;
  enabled: boolean;
  document_count: number;
  total_document_count: number;
  children: KnowledgeCategory[];
  created_by?: number | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentInfo {
  id: number;
  knowledge_base_id: number;
  knowledge_type: 'base' | 'project';
  project_id?: number | null;
  file_name: string;
  file_type: string;
  file_size: number;
  storage_path: string;
  category_id?: number | null;
  category_name?: string | null;
  category_path?: string | null;
  document_status?: string;
  parse_status?: string;
  parse_started_at?: string | null;
  parse_finished_at?: string | null;
  parse_error?: string | null;
  parse_log?: string | null;
  review_status: string;
  index_status: string;
  version_no: number;
  current_version: boolean;
  build_started_at?: string | null;
  build_finished_at?: string | null;
  build_error?: string | null;
  built_by?: number | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentVersionInfo {
  id: number;
  document_id: number;
  version_no: number;
  category_id?: number | null;
  file_name: string;
  file_type?: string;
  file_size?: number;
  storage_path: string;
  change_summary?: string | null;
  version_status?: string;
  parse_status?: string;
  parse_started_at?: string | null;
  parse_finished_at?: string | null;
  parse_error?: string | null;
  parse_log?: string | null;
  review_status: string;
  index_status: string;
  is_current: boolean;
  reviewed_by?: number | null;
  reviewed_at?: string | null;
  review_comment?: string | null;
  build_started_at?: string | null;
  build_finished_at?: string | null;
  build_error?: string | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
}

export interface IndexTaskInfo {
  id: number;
  document_id: number;
  version_id?: number | null;
  version_no: number;
  task_type: string;
  status: 'pending' | 'running' | 'success' | 'failed' | 'canceled';
  progress: number;
  error_message?: string | null;
  result_json?: string | null;
  rq_job_id?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_by?: number | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentIndexSummary {
  document_id: number;
  index_status: string;
  chunk_count: number;
  build_started_at?: string | null;
  build_finished_at?: string | null;
  build_error?: string | null;
  built_by?: number | null;
}

export interface DocumentChunk {
  id: number;
  document_id: number;
  version_no: number;
  chunk_status: string;
  chunk_index: number;
  content: string;
  page_number?: number | null;
  section_title?: string | null;
}

export interface DocumentAssetInfo {
  id: number;
  asset_type: string;
  file_name: string;
  mime_type?: string | null;
  storage_backend: string;
  file_size: number;
  status: 'ready' | 'failed' | 'obsolete' | string;
  metadata_json?: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentPreviewBlock {
  id: number;
  block_index: number;
  block_type: string;
  text?: string | null;
  clean_text?: string | null;
  filter_status?: string;
  filter_reason?: string | null;
  bbox_json?: string | null;
  metadata_json?: string | null;
  image_asset?: DocumentAssetInfo | null;
}

export interface DocumentPreviewPage {
  id: number;
  page_no: number;
  page_title?: string | null;
  drawing_no?: string | null;
  page_text: string;
  clean_content?: string | null;
  filtered_content?: string | null;
  cleaning_metadata_json?: string | null;
  corrected_text?: string | null;
  correction_status: string;
  page_summary?: string | null;
  page_preview_asset?: DocumentAssetInfo | null;
  blocks: DocumentPreviewBlock[];
}

export interface DocumentPreview {
  document: {
    id: number;
    file_name: string;
    file_type: string;
    version_no: number;
    knowledge_type: 'base' | 'project';
    project_id?: number | null;
    index_status: string;
  };
  converted_pdf_asset?: DocumentAssetInfo | null;
  markdown_content?: string | null;
  markdown_source?: string | null;
  markdown_image_assets: DocumentAssetInfo[];
  page_count: number;
  pages: DocumentPreviewPage[];
}

export interface DocumentDeleteResult {
  deleted: boolean;
  vector_count: number;
  retrieval_traces: number;
  chat_citations: number;
  graph_entities: number;
  document_pages: number;
  document_chunks: number;
  document_versions: number;
  index_tasks: number;
  review_tasks: number;
  review_logs: number;
  document_assets: number;
  deleted_asset_files: number;
  deleted_asset_objects: number;
  external_cleanup_queued?: boolean;
  pending_vector_count?: number;
  pending_file_count?: number;
  pending_asset_object_count?: number;
}

export interface ReviewTask {
  id: number;
  document_id: number;
  document_file_name?: string | null;
  document_category_name?: string | null;
  document_category_path?: string | null;
  display_version_no?: number | null;
  uploader_id?: number | null;
  uploader_name?: string | null;
  uploader_username?: string | null;
  version_id?: number | null;
  version_no?: number | null;
  reviewer_id?: number | null;
  review_status: string;
  review_comment?: string | null;
  created_at: string;
}

export interface ChatSession {
  id: number;
  user_id: number;
  title: string;
  chat_type: 'project_chat' | 'base_chat';
  mode: string;
  project_id?: number | null;
  created_at: string;
}

export interface ChatMessage {
  id: number;
  session_id: number;
  role: 'user' | 'assistant';
  content: string;
  query_scope?: string | null;
  agent_trace_json?: string | null;
  feedback_status?: 'like' | 'dislike' | null;
  citations?: Citation[];
  created_at: string;
}

export interface CurrentPermissions {
  menus: string[];
  actions: string[];
}

export interface SystemMenuNode {
  id: string;
  name: string;
  path?: string | null;
  permission_id?: number | null;
  children: SystemMenuNode[];
}

export interface ActionPermissionInfo {
  action: string;
  name: string;
  code: string;
  permission_id?: number | null;
}

export interface ActionPermissionGroup {
  module: string;
  module_name: string;
  menu_ids: string[];
  actions: ActionPermissionInfo[];
}

export interface CitationAsset {
  asset_id: number;
  asset_type: string;
  url: string;
  mime_type?: string | null;
  file_name: string;
  file_size: number;
  page_number?: number | null;
  block_id?: number | null;
  metadata?: Record<string, unknown>;
}

export interface Citation {
  source_type: 'base' | 'project' | 'authorized_internal';
  knowledge_base_id: number;
  project_id?: number | null;
  document_id: number;
  chunk_id: number;
  drawing_no?: string | null;
  file_name: string;
  page_number?: number | null;
  content: string;
  assets?: CitationAsset[];
}

export interface AgentTraceStep {
  sequence?: number | null;
  step: string;
  implementation?: string;
  status?: string;
  display_text?: string;
  elapsed_ms?: number | null;
  result?: string;
  intent?: string;
  sub_query_index?: number | null;
  sub_query_total?: number | null;
  input_summary?: Record<string, unknown>;
  output_summary?: Record<string, unknown>;
  details?: Record<string, unknown>;
}

export interface ChatCompletionResult {
  answer: string;
  session_id: number;
  chat_type: 'project_chat' | 'base_chat';
  mode: string;
  query_scope: string;
  used_retrievers: string[];
  agent_trace: AgentTraceStep[];
  trace_steps?: AgentTraceStep[];
  citations: Citation[];
  feedback_status?: 'like' | 'dislike' | null;
  raw?: Record<string, unknown>;
}

export interface ChatStreamMeta {
  session_id: number;
  chat_type: 'project_chat' | 'base_chat';
  mode: string;
  query_scope: string;
  used_retrievers: string[];
  agent_trace: AgentTraceStep[];
  trace_steps?: AgentTraceStep[];
  citations: Citation[];
  raw?: Record<string, unknown>;
}

export interface ChatTraceDeltaEvent extends AgentTraceStep {
  sequence: number;
  status: 'running' | 'success' | 'failed';
  display_text: string;
}

export interface ChatStreamDoneEvent extends ChatCompletionResult {}

export interface DashboardStats {
  project_count: number;
  knowledge_base_count: number;
  document_count: number;
  knowledge_entry_count?: number;
  ai_answer_count?: number;
  pending_review_count: number;
  last_login_at?: string | null;
  recent_documents: DashboardDocumentSummary[];
  recent_projects: Array<Record<string, unknown>>;
  todo_reviews: Array<Record<string, unknown>>;
  recent_ai_questions?: DashboardAiQuestion[];
  knowledge_category_stats?: DashboardCategoryStat[];
}

export interface DashboardDocumentSummary {
  id: number;
  file_name: string;
  file_type?: string | null;
  review_status?: string | null;
  index_status?: string | null;
  created_at?: string | null;
}

export interface DashboardAiQuestion {
  id: number;
  session_id: number;
  question: string;
  chat_type: 'project_chat' | 'base_chat';
  created_at?: string | null;
}

export interface DashboardCategoryStat {
  name: string;
  value: number;
  percent: number;
  color: string;
}

export interface ModelConfig {
  id: number;
  provider: string;
  model_name: string;
  api_base?: string | null;
  api_key?: string | null;
  model_type: string;
  is_default: boolean;
  enabled: boolean;
}

export interface ListQueryParams {
  page?: number;
  page_size?: number;
}

export interface OperationLog {
  id: number;
  username?: string | null;
  action: string;
  target_type: string;
  target_id?: string | null;
  detail?: string | null;
  result: string;
  created_at: string;
}

export interface PageResult<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type QAAuditFeedbackFilter = 'like' | 'dislike' | 'none';

export interface QAAuditFilters {
  user_id?: number;
  project_id?: number;
  started_at?: string;
  ended_at?: string;
  feedback_status?: QAAuditFeedbackFilter;
  page?: number;
  page_size?: number;
}

export interface QAAuditSession {
  id: number;
  session_id: number;
  title: string;
  user_id: number;
  username: string;
  real_name: string;
  avatar_url?: string | null;
  avatar_updated_at?: string | null;
  chat_type: 'project_chat' | 'base_chat';
  mode: string;
  project_id?: number | null;
  project_name?: string | null;
  project_code?: string | null;
  question_count: number;
  answer_count: number;
  citation_count: number;
  latest_question?: string | null;
  latest_answer?: string | null;
  latest_qa_at: string;
  created_at: string;
}

export interface QAAuditDetail {
  id: number;
  message_id: number;
  session_id: number;
  session_title: string;
  user_id: number;
  username: string;
  real_name: string;
  avatar_url?: string | null;
  avatar_updated_at?: string | null;
  chat_type: 'project_chat' | 'base_chat';
  mode: string;
  project_id?: number | null;
  project_name?: string | null;
  project_code?: string | null;
  question?: string | null;
  answer: string;
  query_scope?: string | null;
  agent_trace_json?: string | null;
  citation_count: number;
  citations: Citation[];
  retrievers: string[];
  intent?: string | null;
  elapsed_ms?: number | null;
  feedback_status?: 'like' | 'dislike' | null;
  answered_at: string;
  created_at: string;
}
