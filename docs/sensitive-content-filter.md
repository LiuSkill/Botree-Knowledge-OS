# 敏感内容过滤实现说明

系统新增 `sensitive_type`、`sensitive_filter_rule`、`role_sensitive_permission` 和轻量审计表
`sensitive_redaction_audit`。没有新增 Chunk 标注表，也不会扫描历史 Chunk、重新解析文档或重建索引。

规则由数据库动态配置，支持 `regex`、`keyword`、`keyword_window`、`table_column`、`table_row`、`table_cell`。启用规则会预编译并缓存 60 秒；管理接口写入后会立即刷新，也可使用
`POST /api/sensitive-content/cache/refresh` 手动刷新。规则管理入口均位于 `/api/sensitive-content`，包括类型、规则、规则测试和角色权限接口。

角色权限按用户启用角色的并集计算；任一角色允许即可查看。管理员根据现有 RBAC 管理员判定获得全部启用类型，不硬编码业务角色 ID。

过滤接入两处：检索证据在证据判断/回答上下文构建前复制为安全 `Evidence`，因此证据判断模型、回答模型和 citation 只接触安全内容；最终答案持久化和返回前再次使用同一规则兜底过滤。流式回答会先在服务端完整生成并过滤，再发送安全文本，避免 token 已发送后无法撤回。

## 表格感知过滤

表格单元格通常只有数字，敏感语义位于表头或第一列行名，固定文本窗口无法可靠关联二者。运行时过滤因此先识别当前 evidence/content 内的局部表格并执行结构过滤，再对安全结果执行原有文本规则兜底；不改变文档解析、分块或索引流程。

当前支持 Markdown、HTML、CSV、TSV 和多空格分隔表格。`table_column` 在表头命中后隐藏该列的数据单元格；`table_row` 在第一列行名命中后隐藏该行其余单元格；`table_cell` 用于需要直接按单元格内容判断的规则。横向指标表会复用列规则匹配第一列行名。规则按优先级匹配，供应商报价规则优先于普通报价规则。

当附近标题包含报价表、成本表、合同清单、供应商报价单、财务测算表、投资收益表或付款计划表，且用户缺少对应权限时，整表替换为 `[该表格包含受限商务敏感信息，当前权限下不展示明细]`。同一表格命中至少 3 个敏感列时也整表隐藏；疑似高风险表格解析失败时同样阻断，禁止回退原文。

过滤仅处理本次回答链路中的内容。单表保护边界为 50,000 字符或 500 行；超过边界且存在未授权敏感规则或高风险标题时整表隐藏。超限不会跳过过滤，也不会触发历史资料扫描或索引重建。

响应新增 `redacted`、`redaction_types`、`security_notice`。审计只记录用户、角色 ID、消息/项目、类型和次数，不记录敏感原文。

测试：在 `backend` 目录执行 `pytest tests/test_sensitive_content_filter.py tests/test_table_sensitive_filter.py tests/test_sensitive_content_acceptance.py`；数据库部署执行 `alembic upgrade head`。

系统管理新增“敏感内容管理”入口，包含敏感类型、敏感规则（含模拟角色和规则启停测试）及角色敏感权限矩阵。审计查询接口为 `GET /api/sensitive-content/audits`，额外记录最终答案是否触发兜底过滤，但不记录敏感原文。详细上线检查见 `docs/sensitive-content-acceptance.md`。
