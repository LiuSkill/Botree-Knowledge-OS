-- Botree Agent / Botree Knowledge OS MySQL 初始化脚本
-- 说明：所有表、字段、枚举字段和关键索引均带有注释，满足企业级知识库初始化要求。
CREATE DATABASE IF NOT EXISTS botree_agent DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE botree_agent;
SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

DROP TABLE IF EXISTS graph_relations;
DROP TABLE IF EXISTS graph_entities;
DROP TABLE IF EXISTS retrieval_traces;
DROP TABLE IF EXISTS chat_citations;
DROP TABLE IF EXISTS review_tasks;
DROP TABLE IF EXISTS review_logs;
DROP TABLE IF EXISTS index_tasks;
DROP TABLE IF EXISTS page_indexes;
DROP TABLE IF EXISTS document_assets;
DROP TABLE IF EXISTS document_page_blocks;
DROP TABLE IF EXISTS document_pages;
DROP TABLE IF EXISTS document_versions;
DROP TABLE IF EXISTS document_chunks;
DROP TABLE IF EXISTS knowledge_base_permissions;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS knowledge_categories;
DROP TABLE IF EXISTS chat_messages;
DROP TABLE IF EXISTS project_members;
DROP TABLE IF EXISTS knowledge_bases;
DROP TABLE IF EXISTS chat_sessions;
DROP TABLE IF EXISTS user_roles;
DROP TABLE IF EXISTS role_permissions;
DROP TABLE IF EXISTS projects;
DROP TABLE IF EXISTS operation_logs;
DROP TABLE IF EXISTS users;
DROP TABLE IF EXISTS system_configs;
DROP TABLE IF EXISTS roles;
DROP TABLE IF EXISTS permissions;
DROP TABLE IF EXISTS model_configs;

SET FOREIGN_KEY_CHECKS = 1;

CREATE TABLE IF NOT EXISTS model_configs (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	provider VARCHAR(100) NOT NULL COMMENT '模型供应商', 
	model_name VARCHAR(150) NOT NULL COMMENT '模型名称', 
	api_base VARCHAR(500) COMMENT 'API Base地址', 
	api_key VARCHAR(500) COMMENT 'API Key，从.env或安全配置读取后写入', 
	model_type VARCHAR(30) NOT NULL COMMENT '模型类型：llm/embedding/reranker/intent/planner/evidence_judge_fast/evidence_judge/answer_llm/vision_llm/analysis_llm/graph_extractor',
	is_default BOOL NOT NULL COMMENT '是否默认模型', 
	enabled BOOL NOT NULL COMMENT '是否启用', 
	security_level VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT '角色最高密级：public/internal/confidential',
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='模型配置表';

CREATE TABLE IF NOT EXISTS permissions (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	module VARCHAR(100) NOT NULL COMMENT '权限所属模块', 
	action VARCHAR(100) NOT NULL COMMENT '权限动作：view/create/update/delete/review/auth', 
	code VARCHAR(150) NOT NULL COMMENT '权限编码', 
	description VARCHAR(500) COMMENT '权限说明', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	UNIQUE KEY uk_permissions_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='权限表';

CREATE TABLE IF NOT EXISTS roles (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	name VARCHAR(100) NOT NULL COMMENT '角色名称', 
	code VARCHAR(100) NOT NULL COMMENT '角色编码', 
	description VARCHAR(500) COMMENT '角色描述', 
	enabled BOOL NOT NULL COMMENT '是否启用', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	UNIQUE KEY uk_roles_name (name), 
	UNIQUE KEY uk_roles_code (code)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色表';

CREATE TABLE IF NOT EXISTS system_configs (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	config_key VARCHAR(150) NOT NULL COMMENT '配置键', 
	config_value TEXT COMMENT '配置值', 
	description VARCHAR(500) COMMENT '配置说明', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	UNIQUE KEY uk_system_configs_config_key (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统配置表';

CREATE TABLE IF NOT EXISTS users (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	username VARCHAR(100) NOT NULL COMMENT '登录用户名', 
	password_hash VARCHAR(255) NOT NULL COMMENT '密码哈希', 
	real_name VARCHAR(100) NOT NULL COMMENT '真实姓名', 
	email VARCHAR(255) COMMENT '邮箱', 
	phone VARCHAR(50) COMMENT '手机号', 
	department VARCHAR(100) COMMENT '所属部门', 
	status VARCHAR(30) NOT NULL COMMENT '状态：enabled/disabled', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户主表';
CREATE UNIQUE INDEX uk_users_username ON users (username);

CREATE TABLE IF NOT EXISTS operation_logs (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	user_id INTEGER COMMENT '操作用户ID，关联users.id', 
	username VARCHAR(100) COMMENT '操作用户名', 
	action VARCHAR(100) NOT NULL COMMENT '操作动作', 
	target_type VARCHAR(100) NOT NULL COMMENT '操作对象类型', 
	target_id VARCHAR(100) COMMENT '操作对象ID', 
	detail TEXT COMMENT '操作详情', 
	ip_address VARCHAR(100) COMMENT 'IP地址', 
	result VARCHAR(30) NOT NULL COMMENT '执行结果：success/failed', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='操作日志表';

CREATE TABLE IF NOT EXISTS projects (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL COMMENT '项目名称', 
	code VARCHAR(100) NOT NULL COMMENT '项目编码', 
	description TEXT COMMENT '项目描述', 
	client VARCHAR(255) COMMENT '客户名称', 
	manager VARCHAR(100) COMMENT '项目经理', 
	status VARCHAR(30) NOT NULL COMMENT '项目状态：active/completed/pending/archived', 
	progress INTEGER NOT NULL COMMENT '项目进度百分比', 
	security_level VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT '项目密级：public/internal/confidential',
	created_by INTEGER COMMENT '创建人ID，关联users.id', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	UNIQUE KEY uk_projects_code (code), 
	FOREIGN KEY(created_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='项目主表';
CREATE INDEX idx_projects_security_level ON projects (security_level);

CREATE TABLE IF NOT EXISTS role_permissions (
	role_id INTEGER NOT NULL COMMENT '角色ID，关联roles.id', 
	permission_id INTEGER NOT NULL COMMENT '权限ID，关联permissions.id', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (role_id, permission_id), 
	FOREIGN KEY(role_id) REFERENCES roles (id), 
	FOREIGN KEY(permission_id) REFERENCES permissions (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='角色权限关联表';

CREATE TABLE IF NOT EXISTS user_roles (
	user_id INTEGER NOT NULL COMMENT '用户ID，关联users.id', 
	role_id INTEGER NOT NULL COMMENT '角色ID，关联roles.id', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (user_id, role_id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(role_id) REFERENCES roles (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户角色关联表';

CREATE TABLE IF NOT EXISTS chat_sessions (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	user_id INTEGER NOT NULL COMMENT '用户ID，关联users.id', 
	title VARCHAR(255) NOT NULL COMMENT '会话标题', 
	chat_type VARCHAR(30) NOT NULL COMMENT '问答类型：project_chat/base_chat', 
	mode VARCHAR(30) NOT NULL COMMENT '问答模式：auto/base_only/project_only/hybrid', 
	project_id INTEGER COMMENT '项目ID，项目问答关联projects.id', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(user_id) REFERENCES users (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能体会话表';
CREATE INDEX idx_chat_sessions_chat_type ON chat_sessions (chat_type);
CREATE INDEX idx_chat_sessions_user_id ON chat_sessions (user_id);

CREATE TABLE IF NOT EXISTS knowledge_bases (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	name VARCHAR(255) NOT NULL COMMENT '知识库名称', 
	code VARCHAR(100) NOT NULL COMMENT '知识库编码', 
	type VARCHAR(30) NOT NULL COMMENT '知识库类型：base/project', 
	project_id INTEGER COMMENT '所属项目ID，base为空，project关联projects.id', 
	description TEXT COMMENT '知识库描述', 
	enabled BOOL NOT NULL COMMENT '是否启用', 
	created_by INTEGER COMMENT '创建人ID，关联users.id', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	UNIQUE KEY uk_knowledge_bases_code (code), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识库表';
CREATE INDEX idx_knowledge_bases_project_id ON knowledge_bases (project_id);
CREATE INDEX idx_knowledge_bases_type ON knowledge_bases (type);

CREATE TABLE IF NOT EXISTS project_members (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	project_id INTEGER NOT NULL COMMENT '所属项目ID，关联projects.id', 
	user_id INTEGER NOT NULL COMMENT '用户ID，关联users.id', 
	`role` VARCHAR(100) NOT NULL COMMENT '项目角色：owner/manager/member/viewer/external', 
	permission_scope VARCHAR(100) NOT NULL COMMENT '权限范围：project_manage/project_read/authorized_only', 
	external_user BOOL NOT NULL COMMENT '是否外部用户', 
	status VARCHAR(30) NOT NULL COMMENT '成员状态：active/disabled/expired', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='项目成员表';
CREATE INDEX idx_project_members_project_id ON project_members (project_id);
CREATE INDEX idx_project_members_user_id ON project_members (user_id);

CREATE TABLE IF NOT EXISTS knowledge_categories (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT,
	scope_type VARCHAR(30) NOT NULL COMMENT '分类范围：base/project',
	project_id INTEGER COMMENT '所属项目ID，项目分类关联projects.id，企业分类为空',
	parent_id INTEGER COMMENT '父分类ID，关联knowledge_categories.id',
	name VARCHAR(100) NOT NULL COMMENT '分类名称',
	code VARCHAR(100) NOT NULL COMMENT '分类编码，同一范围内唯一',
	description TEXT COMMENT '分类说明',
	sort_order INTEGER NOT NULL COMMENT '排序值，数值越小越靠前',
	enabled BOOL NOT NULL COMMENT '是否启用',
	created_by INTEGER COMMENT '创建人ID，关联users.id',
	created_at DATETIME NOT NULL COMMENT '创建时间',
	updated_at DATETIME NOT NULL COMMENT '更新时间',
	PRIMARY KEY (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(parent_id) REFERENCES knowledge_categories (id),
	FOREIGN KEY(created_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识分类表';
CREATE INDEX idx_knowledge_categories_scope ON knowledge_categories (scope_type);
CREATE INDEX idx_knowledge_categories_project_id ON knowledge_categories (project_id);
CREATE INDEX idx_knowledge_categories_parent_id ON knowledge_categories (parent_id);
CREATE UNIQUE INDEX uk_knowledge_categories_scope_code ON knowledge_categories (scope_type, project_id, code);

CREATE TABLE IF NOT EXISTS chat_messages (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	session_id INTEGER NOT NULL COMMENT '会话ID，关联chat_sessions.id', 
	user_id INTEGER COMMENT '用户ID，助手消息可为空', 
	`role` VARCHAR(30) NOT NULL COMMENT '消息角色：user/assistant', 
	content TEXT NOT NULL COMMENT '消息内容', 
	query_scope VARCHAR(100) COMMENT '查询范围说明', 
	agent_trace_json LONGTEXT COMMENT 'Agent执行过程JSON',
	feedback_status VARCHAR(20) COMMENT '回答反馈状态：like/dislike',
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(session_id) REFERENCES chat_sessions (id), 
	FOREIGN KEY(user_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能体消息表';
CREATE INDEX idx_chat_messages_session_id ON chat_messages (session_id);

CREATE TABLE IF NOT EXISTS documents (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	knowledge_base_id INTEGER NOT NULL COMMENT '所属知识库ID，关联knowledge_bases.id', 
	knowledge_type VARCHAR(30) NOT NULL COMMENT '知识类型：base/project', 
	project_id INTEGER COMMENT '所属项目ID，项目知识关联projects.id', 
	file_name VARCHAR(255) NOT NULL COMMENT '文件名', 
	file_type VARCHAR(50) NOT NULL COMMENT '文件类型', 
	file_size INTEGER NOT NULL COMMENT '文件大小，单位字节', 
	storage_path VARCHAR(500) NOT NULL COMMENT '文件存储路径', 
	category_id INTEGER COMMENT '知识分类ID，关联knowledge_categories.id', 
	review_status VARCHAR(30) NOT NULL COMMENT '审核状态：draft/submitted/reviewing/approved/rejected/archived', 
	index_status VARCHAR(30) NOT NULL COMMENT '索引状态：not_indexed/parsing/parsed_pending_review/parsed/indexing/indexed/failed',
	version_no INTEGER NOT NULL COMMENT '当前版本号', 
	current_version BOOL NOT NULL COMMENT '是否当前版本', 
	parent_document_id INTEGER COMMENT '父文档ID，关联documents.id', 
	drawing_no VARCHAR(100) COMMENT '图纸编号', 
	drawing_name VARCHAR(255) COMMENT '图纸名称', 
	security_level VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT '文档密级：public/internal/confidential',
	created_by INTEGER COMMENT '创建人ID，关联users.id', 
	submitted_by INTEGER COMMENT '提交人ID，关联users.id', 
	reviewed_by INTEGER COMMENT '审核人ID，关联users.id', 
	submitted_at DATETIME COMMENT '提交审核时间', 
	reviewed_at DATETIME COMMENT '审核完成时间', 
	review_comment TEXT COMMENT '审核意见', 
	build_started_at DATETIME COMMENT '解析并构建索引开始时间', 
	build_finished_at DATETIME COMMENT '解析并构建索引完成时间', 
	build_error TEXT COMMENT '解析并构建索引失败信息', 
	built_by INTEGER COMMENT '构建操作人ID，关联users.id', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(category_id) REFERENCES knowledge_categories (id), 
	FOREIGN KEY(parent_document_id) REFERENCES documents (id), 
	FOREIGN KEY(created_by) REFERENCES users (id), 
	FOREIGN KEY(submitted_by) REFERENCES users (id), 
	FOREIGN KEY(reviewed_by) REFERENCES users (id), 
	FOREIGN KEY(built_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档主表';
CREATE INDEX idx_documents_category_id ON documents (category_id);
CREATE INDEX idx_documents_index_status ON documents (index_status);
CREATE INDEX idx_documents_knowledge_base_id ON documents (knowledge_base_id);
CREATE INDEX idx_documents_knowledge_type ON documents (knowledge_type);
CREATE INDEX idx_documents_project_id ON documents (project_id);
CREATE INDEX idx_documents_review_status ON documents (review_status);
CREATE INDEX idx_documents_security_level ON documents (security_level);

CREATE TABLE IF NOT EXISTS document_chunks (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	knowledge_base_id INTEGER NOT NULL COMMENT '所属知识库ID，关联knowledge_bases.id', 
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id', 
	project_id INTEGER COMMENT '所属项目ID，项目知识关联projects.id', 
	knowledge_type VARCHAR(30) NOT NULL COMMENT '知识类型：base/project', 
	version_no INTEGER NOT NULL DEFAULT 1 COMMENT '所属文档版本号', 
	chunk_status VARCHAR(30) NOT NULL DEFAULT 'active' COMMENT 'Chunk状态：active/obsolete', 
	chunk_index INTEGER NOT NULL COMMENT 'Chunk序号', 
	content TEXT NOT NULL COMMENT 'Chunk内容', 
	page_number INTEGER COMMENT '页码', 
	section_title VARCHAR(255) COMMENT '章节标题', 
	metadata_json TEXT COMMENT '扩展元数据JSON', 
	vector_id VARCHAR(255) COMMENT '向量ID，后续关联Milvus', 
	security_level VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT 'Chunk密级：public/internal/confidential',
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档切块表';
CREATE INDEX idx_document_chunks_document_id ON document_chunks (document_id);
CREATE INDEX idx_document_chunks_knowledge_base_id ON document_chunks (knowledge_base_id);
CREATE INDEX idx_document_chunks_knowledge_type ON document_chunks (knowledge_type);
CREATE INDEX idx_document_chunks_project_id ON document_chunks (project_id);
CREATE INDEX idx_document_chunks_version_no ON document_chunks (version_no);
CREATE INDEX idx_document_chunks_chunk_status ON document_chunks (chunk_status);
CREATE INDEX idx_document_chunks_security_level ON document_chunks (security_level);

CREATE TABLE IF NOT EXISTS document_pages (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT,
	knowledge_base_id INTEGER NOT NULL COMMENT '所属知识库ID，关联knowledge_bases.id',
	project_id INTEGER COMMENT '所属项目ID，关联projects.id',
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id',
	version_no INTEGER NOT NULL DEFAULT 1 COMMENT '所属文档版本号',
	page_no INTEGER NOT NULL COMMENT '页码',
	drawing_no VARCHAR(100) COMMENT '图纸编号',
	page_title VARCHAR(255) COMMENT '页标题或章节标题',
	page_text TEXT NOT NULL COMMENT '页级原始正文文本',
	clean_content TEXT COMMENT '清洗后页文本，用于分块和索引',
	filtered_content TEXT COMMENT '清洗过滤掉的页文本',
	cleaning_metadata_json TEXT COMMENT '解析清洗摘要JSON',
	page_summary TEXT COMMENT '页级摘要',
	layout_json LONGTEXT COMMENT 'MinerU版面结构JSON',
	mineru_json_object_key VARCHAR(500) COMMENT 'MinerU原始JSON对象存储Key',
	page_image_object_key VARCHAR(500) COMMENT '页面图片对象存储Key',
	source_hash VARCHAR(100) COMMENT '页内容哈希',
	correction_status VARCHAR(30) NOT NULL DEFAULT 'raw' COMMENT '修正状态：raw/corrected/confirmed',
	corrected_text TEXT COMMENT '人工修正后的页文本',
	corrected_by INTEGER COMMENT '修正人ID，关联users.id',
	security_level VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT '文档页密级：public/internal/confidential',
	created_at DATETIME NOT NULL COMMENT '创建时间',
	updated_at DATETIME NOT NULL COMMENT '更新时间',
	PRIMARY KEY (id),
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(document_id) REFERENCES documents (id),
	FOREIGN KEY(corrected_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档页级解析表';
CREATE INDEX idx_document_pages_knowledge_base_id ON document_pages (knowledge_base_id);
CREATE INDEX idx_document_pages_project_id ON document_pages (project_id);
CREATE INDEX idx_document_pages_document_id ON document_pages (document_id);
CREATE INDEX idx_document_pages_version_no ON document_pages (version_no);
CREATE INDEX idx_document_pages_page_no ON document_pages (page_no);
CREATE INDEX idx_document_pages_drawing_no ON document_pages (drawing_no);
CREATE INDEX idx_document_pages_correction_status ON document_pages (correction_status);
CREATE INDEX idx_document_pages_security_level ON document_pages (security_level);

CREATE TABLE IF NOT EXISTS document_page_blocks (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT,
	page_id INTEGER NOT NULL COMMENT '所属页ID，关联document_pages.id',
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id',
	block_index INTEGER NOT NULL COMMENT '页内块序号',
	block_type VARCHAR(50) NOT NULL COMMENT '块类型：title/text/table/image/formula',
	text TEXT COMMENT '块原始文本内容',
	clean_text TEXT COMMENT '清洗后块文本',
	filter_status VARCHAR(30) NOT NULL DEFAULT 'kept' COMMENT '清洗状态：kept/filtered',
	filter_reason VARCHAR(100) COMMENT '清洗过滤原因',
	bbox_json TEXT COMMENT '块坐标JSON',
	metadata_json TEXT COMMENT '块扩展元数据JSON',
	created_at DATETIME NOT NULL COMMENT '创建时间',
	updated_at DATETIME NOT NULL COMMENT '更新时间',
	PRIMARY KEY (id),
	FOREIGN KEY(page_id) REFERENCES document_pages (id),
	FOREIGN KEY(document_id) REFERENCES documents (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档页块解析表';
CREATE INDEX idx_document_page_blocks_page_id ON document_page_blocks (page_id);
CREATE INDEX idx_document_page_blocks_document_id ON document_page_blocks (document_id);

CREATE TABLE IF NOT EXISTS document_assets (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT,
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id',
	version_no INTEGER NOT NULL COMMENT '所属文档版本号',
	page_id INTEGER COMMENT '所属页ID，关联document_pages.id',
	block_id INTEGER COMMENT '所属块ID，关联document_page_blocks.id',
	asset_type VARCHAR(50) NOT NULL COMMENT '资产类型：converted_pdf/mineru_result/page_preview/block_image',
	file_name VARCHAR(255) NOT NULL COMMENT '资产文件名',
	mime_type VARCHAR(100) COMMENT '资产MIME类型',
	storage_backend VARCHAR(30) NOT NULL DEFAULT 'local' COMMENT '存储后端：local/minio',
	storage_path VARCHAR(500) COMMENT '本地存储路径',
	object_key VARCHAR(500) COMMENT '对象存储Key',
	file_size INTEGER NOT NULL DEFAULT 0 COMMENT '文件大小，单位字节',
	status VARCHAR(30) NOT NULL DEFAULT 'ready' COMMENT '资产状态：ready/failed/obsolete',
	metadata_json TEXT COMMENT '资产扩展元数据JSON',
	created_by INTEGER COMMENT '创建人ID，关联users.id',
	created_at DATETIME NOT NULL COMMENT '创建时间',
	updated_at DATETIME NOT NULL COMMENT '更新时间',
	PRIMARY KEY (id),
	FOREIGN KEY(document_id) REFERENCES documents (id),
	FOREIGN KEY(page_id) REFERENCES document_pages (id),
	FOREIGN KEY(block_id) REFERENCES document_page_blocks (id),
	FOREIGN KEY(created_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档派生资产表';
CREATE INDEX idx_document_assets_document_id ON document_assets (document_id);
CREATE INDEX idx_document_assets_version_no ON document_assets (version_no);
CREATE INDEX idx_document_assets_asset_type ON document_assets (asset_type);
CREATE INDEX idx_document_assets_status ON document_assets (status);
CREATE INDEX idx_document_assets_page_id ON document_assets (page_id);
CREATE INDEX idx_document_assets_block_id ON document_assets (block_id);

CREATE TABLE IF NOT EXISTS page_indexes (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT,
	knowledge_base_id INTEGER NOT NULL COMMENT '所属知识库ID，关联knowledge_bases.id',
	project_id INTEGER COMMENT '所属项目ID，关联projects.id',
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id',
	page_id INTEGER NOT NULL COMMENT '关联页ID，关联document_pages.id',
	chunk_id INTEGER COMMENT '关联Chunk ID，关联document_chunks.id',
	version_no INTEGER NOT NULL DEFAULT 1 COMMENT '所属文档版本号',
	page_no INTEGER NOT NULL COMMENT '页码',
	drawing_no VARCHAR(100) COMMENT '图纸编号',
	index_text TEXT NOT NULL COMMENT '用于页级检索的文本',
	text_mirror_path VARCHAR(500) COMMENT 'ripgrep本地文本镜像路径',
	status VARCHAR(30) NOT NULL DEFAULT 'staging' COMMENT '索引状态：staging/published/obsolete',
	security_level VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT 'PageIndex密级：public/internal/confidential',
	created_at DATETIME NOT NULL COMMENT '创建时间',
	updated_at DATETIME NOT NULL COMMENT '更新时间',
	PRIMARY KEY (id),
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id),
	FOREIGN KEY(project_id) REFERENCES projects (id),
	FOREIGN KEY(document_id) REFERENCES documents (id),
	FOREIGN KEY(page_id) REFERENCES document_pages (id),
	FOREIGN KEY(chunk_id) REFERENCES document_chunks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='PageIndex页级索引表';
CREATE INDEX idx_page_indexes_knowledge_base_id ON page_indexes (knowledge_base_id);
CREATE INDEX idx_page_indexes_project_id ON page_indexes (project_id);
CREATE INDEX idx_page_indexes_document_id ON page_indexes (document_id);
CREATE INDEX idx_page_indexes_page_id ON page_indexes (page_id);
CREATE INDEX idx_page_indexes_chunk_id ON page_indexes (chunk_id);
CREATE INDEX idx_page_indexes_version_no ON page_indexes (version_no);
CREATE INDEX idx_page_indexes_page_no ON page_indexes (page_no);
CREATE INDEX idx_page_indexes_drawing_no ON page_indexes (drawing_no);
CREATE INDEX idx_page_indexes_status ON page_indexes (status);
CREATE INDEX idx_page_indexes_security_level ON page_indexes (security_level);

CREATE TABLE IF NOT EXISTS index_tasks (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT,
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id',
	version_no INTEGER NOT NULL DEFAULT 1 COMMENT '任务对应文档版本号',
	task_type VARCHAR(50) NOT NULL COMMENT '任务类型：mineru_parse/pageindex_build/milvus_build/ripgrep_build/graphrag_build/index_publish/full_build',
	status VARCHAR(30) NOT NULL DEFAULT 'pending' COMMENT '任务状态：pending/running/success/failed/canceled',
	progress INTEGER NOT NULL DEFAULT 0 COMMENT '任务进度，0-100',
	error_message TEXT COMMENT '失败错误信息',
	result_json TEXT COMMENT '任务执行结果JSON',
	rq_job_id VARCHAR(100) COMMENT 'RQ任务ID',
	started_at DATETIME COMMENT '任务开始时间',
	finished_at DATETIME COMMENT '任务完成时间',
	created_by INTEGER COMMENT '创建人ID，关联users.id',
	created_at DATETIME NOT NULL COMMENT '创建时间',
	updated_at DATETIME NOT NULL COMMENT '更新时间',
	PRIMARY KEY (id),
	FOREIGN KEY(document_id) REFERENCES documents (id),
	FOREIGN KEY(created_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='离线索引任务表';
CREATE INDEX idx_index_tasks_document_id ON index_tasks (document_id);
CREATE INDEX idx_index_tasks_version_no ON index_tasks (version_no);
CREATE INDEX idx_index_tasks_task_type ON index_tasks (task_type);
CREATE INDEX idx_index_tasks_status ON index_tasks (status);

CREATE TABLE IF NOT EXISTS document_versions (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id', 
	version_no INTEGER NOT NULL COMMENT '版本号', 
	category_id INTEGER COMMENT '版本所属知识分类ID，关联knowledge_categories.id', 
	file_name VARCHAR(255) NOT NULL COMMENT '文件名', 
	storage_path VARCHAR(500) NOT NULL COMMENT '文件存储路径', 
	change_summary TEXT COMMENT '版本变更说明', 
	review_status VARCHAR(30) NOT NULL COMMENT '审核状态：draft/submitted/reviewing/approved/rejected/archived', 
	index_status VARCHAR(30) NOT NULL COMMENT '索引状态：not_indexed/parsing/parsed_pending_review/parsed/indexing/indexed/failed', 
	is_current BOOL NOT NULL COMMENT '是否当前版本', 
	security_level VARCHAR(30) NOT NULL DEFAULT 'internal' COMMENT '文档版本密级：public/internal/confidential',
	created_by INTEGER COMMENT '创建人ID，关联users.id', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(category_id) REFERENCES knowledge_categories (id), 
	FOREIGN KEY(created_by) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='文档版本表';
CREATE INDEX idx_document_versions_category_id ON document_versions (category_id);
CREATE INDEX idx_document_versions_document_id ON document_versions (document_id);
CREATE INDEX idx_document_versions_security_level ON document_versions (security_level);

CREATE TABLE IF NOT EXISTS review_logs (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id', 
	action VARCHAR(50) NOT NULL COMMENT '审核动作：submit/approve/reject/archive', 
	operator_id INTEGER COMMENT '操作人ID，关联users.id', 
	comment TEXT COMMENT '操作说明', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(operator_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审核日志表';
CREATE INDEX idx_review_logs_document_id ON review_logs (document_id);

CREATE TABLE IF NOT EXISTS review_tasks (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	document_id INTEGER NOT NULL COMMENT '关联文档ID，关联documents.id', 
	reviewer_id INTEGER COMMENT '审核人ID，关联users.id', 
	review_status VARCHAR(30) NOT NULL COMMENT '审核状态：reviewing/approved/rejected', 
	review_comment TEXT COMMENT '审核意见', 
	reviewed_at DATETIME COMMENT '审核完成时间', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(reviewer_id) REFERENCES users (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审核任务表';
CREATE INDEX idx_review_tasks_document_id ON review_tasks (document_id);
CREATE INDEX idx_review_tasks_review_status ON review_tasks (review_status);

CREATE TABLE IF NOT EXISTS chat_citations (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	message_id INTEGER NOT NULL COMMENT '助手消息ID，关联chat_messages.id', 
	source_type VARCHAR(30) NOT NULL COMMENT '来源类型：base/project', 
	knowledge_base_id INTEGER NOT NULL COMMENT '知识库ID，关联knowledge_bases.id', 
	project_id INTEGER COMMENT '项目ID，项目知识关联projects.id', 
	document_id INTEGER NOT NULL COMMENT '文档ID，关联documents.id', 
	chunk_id INTEGER NOT NULL COMMENT 'Chunk ID，关联document_chunks.id', 
	drawing_no VARCHAR(100) COMMENT '图纸编号', 
	file_name VARCHAR(255) NOT NULL COMMENT '来源文件名', 
	page_number INTEGER COMMENT '来源页码', 
	content TEXT NOT NULL COMMENT '引用片段内容', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(message_id) REFERENCES chat_messages (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(chunk_id) REFERENCES document_chunks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='智能体引用来源表';
CREATE INDEX idx_chat_citations_message_id ON chat_citations (message_id);

CREATE TABLE IF NOT EXISTS retrieval_traces (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT,
	user_id INTEGER COMMENT '提问用户ID，关联users.id',
	session_id INTEGER COMMENT '会话ID，关联chat_sessions.id',
	message_id INTEGER COMMENT '回答消息ID，关联chat_messages.id',
	chat_type VARCHAR(30) NOT NULL DEFAULT 'qa' COMMENT '问答类型：qa/document/project/debug',
	mode VARCHAR(30) NOT NULL DEFAULT 'rag' COMMENT '问答模式：rag/direct/debug',
	knowledge_base_id INTEGER COMMENT '知识库ID，关联knowledge_bases.id',
	project_id INTEGER COMMENT '项目ID，关联projects.id',
	question TEXT NOT NULL COMMENT '用户原始问题',
	intent VARCHAR(100) COMMENT 'Qwen识别的意图',
	sub_queries_json LONGTEXT COMMENT 'Qwen拆解后的子查询JSON',
	retriever_hits_json LONGTEXT COMMENT '各路召回命中统计JSON',
	rerank_result_json LONGTEXT COMMENT 'Reranker重排结果JSON',
	citations_json LONGTEXT COMMENT '最终引用JSON，包含project_id/document_id/drawing_no/page_no/chunk_id',
	trace_json LONGTEXT COMMENT '完整检索编排Trace JSON',
	elapsed_ms INTEGER COMMENT '端到端耗时毫秒',
	created_at DATETIME NOT NULL COMMENT '创建时间',
	updated_at DATETIME NOT NULL COMMENT '更新时间',
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES users (id),
	FOREIGN KEY(session_id) REFERENCES chat_sessions (id),
	FOREIGN KEY(message_id) REFERENCES chat_messages (id),
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id),
	FOREIGN KEY(project_id) REFERENCES projects (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='检索问答审计Trace表';
CREATE INDEX idx_retrieval_traces_user_id ON retrieval_traces (user_id);
CREATE INDEX idx_retrieval_traces_message_id ON retrieval_traces (message_id);
CREATE INDEX idx_retrieval_traces_knowledge_base_id ON retrieval_traces (knowledge_base_id);
CREATE INDEX idx_retrieval_traces_project_id ON retrieval_traces (project_id);
CREATE INDEX idx_retrieval_traces_created_at ON retrieval_traces (created_at);

CREATE TABLE IF NOT EXISTS graph_entities (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	knowledge_base_id INTEGER NOT NULL COMMENT '知识库ID，关联knowledge_bases.id', 
	project_id INTEGER COMMENT '所属项目ID，项目知识关联projects.id', 
	document_id INTEGER NOT NULL COMMENT '文档ID，关联documents.id', 
	chunk_id INTEGER COMMENT 'Chunk ID，关联document_chunks.id', 
	version_no INTEGER NOT NULL DEFAULT 1 COMMENT '来源文档版本号', 
	drawing_no VARCHAR(100) COMMENT '图纸编号', 
	page_number INTEGER COMMENT '来源页码', 
	status VARCHAR(30) NOT NULL DEFAULT 'staging' COMMENT '图谱索引状态：staging/published/obsolete', 
	entity_type VARCHAR(100) NOT NULL COMMENT '实体类型', 
	entity_code VARCHAR(150) COMMENT '实体编码', 
	entity_name VARCHAR(255) NOT NULL COMMENT '实体名称', 
	properties_json TEXT COMMENT '实体属性JSON', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(chunk_id) REFERENCES document_chunks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识图谱实体表';
CREATE INDEX idx_graph_entities_document_id ON graph_entities (document_id);
CREATE INDEX idx_graph_entities_knowledge_base_id ON graph_entities (knowledge_base_id);
CREATE INDEX idx_graph_entities_project_id ON graph_entities (project_id);
CREATE INDEX idx_graph_entities_version_no ON graph_entities (version_no);
CREATE INDEX idx_graph_entities_drawing_no ON graph_entities (drawing_no);
CREATE INDEX idx_graph_entities_page_number ON graph_entities (page_number);
CREATE INDEX idx_graph_entities_status ON graph_entities (status);

CREATE TABLE IF NOT EXISTS graph_relations (
	id INTEGER NOT NULL COMMENT '主键ID' AUTO_INCREMENT, 
	knowledge_base_id INTEGER NOT NULL COMMENT '知识库ID，关联knowledge_bases.id', 
	project_id INTEGER COMMENT '所属项目ID，项目知识关联projects.id', 
	source_entity_id INTEGER NOT NULL COMMENT '源实体ID，关联graph_entities.id', 
	target_entity_id INTEGER NOT NULL COMMENT '目标实体ID，关联graph_entities.id', 
	relation_type VARCHAR(100) NOT NULL COMMENT '关系类型', 
	document_id INTEGER COMMENT '来源文档ID，关联documents.id', 
	chunk_id INTEGER COMMENT '来源Chunk ID，关联document_chunks.id', 
	version_no INTEGER NOT NULL DEFAULT 1 COMMENT '来源文档版本号', 
	drawing_no VARCHAR(100) COMMENT '图纸编号', 
	page_number INTEGER COMMENT '来源页码', 
	status VARCHAR(30) NOT NULL DEFAULT 'staging' COMMENT '图谱关系状态：staging/published/obsolete', 
	properties_json TEXT COMMENT '关系属性JSON', 
	created_at DATETIME NOT NULL COMMENT '创建时间', 
	updated_at DATETIME NOT NULL COMMENT '更新时间', 
	PRIMARY KEY (id), 
	FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	FOREIGN KEY(project_id) REFERENCES projects (id), 
	FOREIGN KEY(source_entity_id) REFERENCES graph_entities (id), 
	FOREIGN KEY(target_entity_id) REFERENCES graph_entities (id), 
	FOREIGN KEY(document_id) REFERENCES documents (id), 
	FOREIGN KEY(chunk_id) REFERENCES document_chunks (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='知识图谱关系表';
CREATE INDEX idx_graph_relations_knowledge_base_id ON graph_relations (knowledge_base_id);
CREATE INDEX idx_graph_relations_project_id ON graph_relations (project_id);
CREATE INDEX idx_graph_relations_source_entity_id ON graph_relations (source_entity_id);
CREATE INDEX idx_graph_relations_target_entity_id ON graph_relations (target_entity_id);
CREATE INDEX idx_graph_relations_document_id ON graph_relations (document_id);
CREATE INDEX idx_graph_relations_version_no ON graph_relations (version_no);
CREATE INDEX idx_graph_relations_drawing_no ON graph_relations (drawing_no);
CREATE INDEX idx_graph_relations_page_number ON graph_relations (page_number);
CREATE INDEX idx_graph_relations_status ON graph_relations (status);

-- 默认权限点
INSERT INTO permissions (module, action, code, description, created_at, updated_at) VALUES
('dashboard', 'view', 'dashboard:view', 'dashboard模块view权限', NOW(), NOW()),
('dashboard', 'create', 'dashboard:create', 'dashboard模块create权限', NOW(), NOW()),
('dashboard', 'update', 'dashboard:update', 'dashboard模块update权限', NOW(), NOW()),
('dashboard', 'delete', 'dashboard:delete', 'dashboard模块delete权限', NOW(), NOW()),
('dashboard', 'review', 'dashboard:review', 'dashboard模块review权限', NOW(), NOW()),
('dashboard', 'auth', 'dashboard:auth', 'dashboard模块auth权限', NOW(), NOW()),
('knowledge', 'view', 'knowledge:view', 'knowledge模块view权限', NOW(), NOW()),
('knowledge', 'create', 'knowledge:create', 'knowledge模块create权限', NOW(), NOW()),
('knowledge', 'update', 'knowledge:update', 'knowledge模块update权限', NOW(), NOW()),
('knowledge', 'delete', 'knowledge:delete', 'knowledge模块delete权限', NOW(), NOW()),
('knowledge', 'review', 'knowledge:review', 'knowledge模块review权限', NOW(), NOW()),
('knowledge', 'auth', 'knowledge:auth', 'knowledge模块auth权限', NOW(), NOW()),
('project', 'view', 'project:view', 'project模块view权限', NOW(), NOW()),
('project', 'create', 'project:create', 'project模块create权限', NOW(), NOW()),
('project', 'update', 'project:update', 'project模块update权限', NOW(), NOW()),
('project', 'delete', 'project:delete', 'project模块delete权限', NOW(), NOW()),
('project', 'review', 'project:review', 'project模块review权限', NOW(), NOW()),
('project', 'auth', 'project:auth', 'project模块auth权限', NOW(), NOW()),
('authorization', 'view', 'authorization:view', 'authorization模块view权限', NOW(), NOW()),
('authorization', 'create', 'authorization:create', 'authorization模块create权限', NOW(), NOW()),
('authorization', 'update', 'authorization:update', 'authorization模块update权限', NOW(), NOW()),
('authorization', 'delete', 'authorization:delete', 'authorization模块delete权限', NOW(), NOW()),
('authorization', 'review', 'authorization:review', 'authorization模块review权限', NOW(), NOW()),
('authorization', 'auth', 'authorization:auth', 'authorization模块auth权限', NOW(), NOW()),
('ai', 'view', 'ai:view', 'ai模块view权限', NOW(), NOW()),
('ai', 'create', 'ai:create', 'ai模块create权限', NOW(), NOW()),
('ai', 'update', 'ai:update', 'ai模块update权限', NOW(), NOW()),
('ai', 'delete', 'ai:delete', 'ai模块delete权限', NOW(), NOW()),
('ai', 'review', 'ai:review', 'ai模块review权限', NOW(), NOW()),
('ai', 'auth', 'ai:auth', 'ai模块auth权限', NOW(), NOW()),
('review', 'view', 'review:view', 'review模块view权限', NOW(), NOW()),
('review', 'create', 'review:create', 'review模块create权限', NOW(), NOW()),
('review', 'update', 'review:update', 'review模块update权限', NOW(), NOW()),
('review', 'delete', 'review:delete', 'review模块delete权限', NOW(), NOW()),
('review', 'review', 'review:review', 'review模块review权限', NOW(), NOW()),
('review', 'auth', 'review:auth', 'review模块auth权限', NOW(), NOW()),
('system', 'view', 'system:view', 'system模块view权限', NOW(), NOW()),
('system', 'create', 'system:create', 'system模块create权限', NOW(), NOW()),
('system', 'update', 'system:update', 'system模块update权限', NOW(), NOW()),
('system', 'delete', 'system:delete', 'system模块delete权限', NOW(), NOW()),
('system', 'review', 'system:review', 'system模块review权限', NOW(), NOW()),
('system', 'auth', 'system:auth', 'system模块auth权限', NOW(), NOW())
ON DUPLICATE KEY UPDATE description = VALUES(description), updated_at = NOW();

-- 默认角色
INSERT INTO roles (name, code, description, enabled, security_level, created_at, updated_at) VALUES
('超级管理员', 'admin', '拥有平台全部权限', 1, 'confidential', NOW(), NOW()),
('知识工程师', 'engineer', '管理知识库和项目资料', 1, 'internal', NOW(), NOW()),
('只读用户', 'viewer', '查看已授权知识和项目', 1, 'public', NOW(), NOW())
ON DUPLICATE KEY UPDATE description = VALUES(description), enabled = VALUES(enabled), security_level = VALUES(security_level), updated_at = NOW();

-- 管理员绑定全部权限
INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at, updated_at)
SELECT r.id, p.id, NOW(), NOW() FROM roles r CROSS JOIN permissions p WHERE r.code = 'admin';

-- 默认管理员由应用启动时根据 DEFAULT_ADMIN_USERNAME/DEFAULT_ADMIN_PASSWORD 创建，初始化SQL不写入固定密码。

-- 默认基础知识库
INSERT INTO knowledge_bases (name, code, type, project_id, description, enabled, created_by, created_at, updated_at) VALUES
('企业基础知识库', 'base-default', 'base', NULL, '企业通用工艺、设备、规范和专家经验知识库', 1, NULL, NOW(), NOW())
ON DUPLICATE KEY UPDATE name = VALUES(name), description = VALUES(description), enabled = VALUES(enabled), updated_at = NOW();

-- 默认企业知识分类
INSERT INTO knowledge_categories (scope_type, project_id, parent_id, name, code, description, sort_order, enabled, created_by, created_at, updated_at)
SELECT 'base', NULL, NULL, '工艺技术', 'base-process', '企业工艺技术资料分类', 10, 1, NULL, NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM knowledge_categories WHERE scope_type = 'base' AND project_id IS NULL AND code = 'base-process')
UNION ALL
SELECT 'base', NULL, NULL, '实验报告', 'base-lab-report', '企业实验报告资料分类', 20, 1, NULL, NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM knowledge_categories WHERE scope_type = 'base' AND project_id IS NULL AND code = 'base-lab-report')
UNION ALL
SELECT 'base', NULL, NULL, '设计规范', 'base-design-standard', '企业设计规范资料分类', 30, 1, NULL, NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM knowledge_categories WHERE scope_type = 'base' AND project_id IS NULL AND code = 'base-design-standard')
UNION ALL
SELECT 'base', NULL, NULL, '标准法规', 'base-regulation', '企业标准法规资料分类', 40, 1, NULL, NOW(), NOW()
WHERE NOT EXISTS (SELECT 1 FROM knowledge_categories WHERE scope_type = 'base' AND project_id IS NULL AND code = 'base-regulation');

INSERT INTO knowledge_categories (scope_type, project_id, parent_id, name, code, description, sort_order, enabled, created_by, created_at, updated_at)
SELECT 'base', NULL, parent.id, '浸出工艺', 'base-process-leaching', '浸出工艺资料', 10, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-process'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-process-leaching')
UNION ALL
SELECT 'base', NULL, parent.id, '萃取分离', 'base-process-extraction', '萃取分离资料', 20, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-process'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-process-extraction')
UNION ALL
SELECT 'base', NULL, parent.id, '沉淀结晶', 'base-process-crystallization', '沉淀结晶资料', 30, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-process'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-process-crystallization')
UNION ALL
SELECT 'base', NULL, parent.id, '条件优化', 'base-lab-optimization', '实验条件优化资料', 10, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-lab-report'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-lab-optimization')
UNION ALL
SELECT 'base', NULL, parent.id, '表征分析', 'base-lab-analysis', '表征分析资料', 20, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-lab-report'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-lab-analysis')
UNION ALL
SELECT 'base', NULL, parent.id, '工艺设计', 'base-design-process', '工艺设计资料', 10, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-design-standard'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-design-process')
UNION ALL
SELECT 'base', NULL, parent.id, '设备选型', 'base-design-equipment', '设备选型资料', 20, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-design-standard'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-design-equipment')
UNION ALL
SELECT 'base', NULL, parent.id, '国家标准', 'base-regulation-national', '国家标准资料', 10, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-regulation'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-regulation-national')
UNION ALL
SELECT 'base', NULL, parent.id, '行业标准', 'base-regulation-industry', '行业标准资料', 20, 1, NULL, NOW(), NOW()
FROM knowledge_categories parent
WHERE parent.scope_type = 'base' AND parent.project_id IS NULL AND parent.code = 'base-regulation'
  AND NOT EXISTS (SELECT 1 FROM knowledge_categories child WHERE child.scope_type = 'base' AND child.project_id IS NULL AND child.code = 'base-regulation-industry');

-- 默认模型配置；真实 API Key 从 .env 读取，避免脚本泄露密钥。
INSERT INTO model_configs (provider, model_name, api_base, api_key, model_type, is_default, enabled, created_at, updated_at) VALUES
('qwen_api', 'qwen3.7-max', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'llm', 1, 1, NOW(), NOW()),
('qwen_api', 'qwen3.5-flash', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'intent', 1, 1, NOW(), NOW()),
('qwen_api', 'qwen3.5-flash', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'planner', 1, 1, NOW(), NOW()),
('qwen_api', 'qwen3.5-flash', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'evidence_judge_fast', 1, 1, NOW(), NOW()),
('qwen_api', 'qwen3.5-plus', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'evidence_judge', 1, 1, NOW(), NOW()),
('qwen_api', 'qwen3.5-plus', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'answer_llm', 1, 1, NOW(), NOW()),
('qwen_api', 'qwen3.5-plus', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'vision_llm', 1, 1, NOW(), NOW()),
('qwen_api', 'qwen3.7-max', 'https://dashscope.aliyuncs.com/compatible-mode/v1', NULL, 'analysis_llm', 1, 1, NOW(), NOW()),
('local', 'E:/workspace/botree-agent/backend/workspace/Qwen/Qwen3-Embedding-0.6B', NULL, NULL, 'embedding', 1, 1, NOW(), NOW());
