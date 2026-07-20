# 敏感内容过滤实现说明

系统新增 `sensitive_type`、`sensitive_filter_rule`、`role_sensitive_permission` 和轻量审计表
`sensitive_redaction_audit`。没有新增 Chunk 标注表，也不会扫描历史 Chunk、重新解析文档或重建索引。

规则由数据库动态配置，支持 `regex`、`keyword`、`keyword_window`。启用规则会预编译并缓存 60 秒；管理接口写入后会立即刷新，也可使用
`POST /api/sensitive-content/cache/refresh` 手动刷新。规则管理入口均位于 `/api/sensitive-content`，包括类型、规则、规则测试和角色权限接口。

角色权限按用户启用角色的并集计算；任一角色允许即可查看。管理员根据现有 RBAC 管理员判定获得全部启用类型，不硬编码业务角色 ID。

过滤接入两处：检索证据在证据判断/回答上下文构建前复制为安全 `Evidence`，因此证据判断模型、回答模型和 citation 只接触安全内容；最终答案持久化和返回前再次使用同一规则兜底过滤。流式回答会先在服务端完整生成并过滤，再发送安全文本，避免 token 已发送后无法撤回。

响应新增 `redacted`、`redaction_types`、`security_notice`。审计只记录用户、角色 ID、消息/项目、类型和次数，不记录敏感原文。

测试：在 `backend` 目录执行 `pytest tests/test_sensitive_content_filter.py`；数据库部署执行 `alembic upgrade head`。

系统管理新增“敏感内容管理”入口，包含敏感类型、敏感规则（含模拟角色和规则启停测试）及角色敏感权限矩阵。审计查询接口为 `GET /api/sensitive-content/audits`，额外记录最终答案是否触发兜底过滤，但不记录敏感原文。详细上线检查见 `docs/sensitive-content-acceptance.md`。
