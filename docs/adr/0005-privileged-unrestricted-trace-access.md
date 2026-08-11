# 问答 Debugger 使用独立的特权访问边界

问答 Debugger 只向拥有 `system:qa-audit:debug` 操作权限的人员开放；该权限挂靠在现有问答审计菜单下，并与 `system:qa-audit:view` 分离。授权后可查看 Trace 中全部问答业务载荷，不再应用项目范围、知识库授权、密级或敏感内容掩码，以保证端到端问题可以被完整还原。认证凭据和密钥在 Trace 事件产生前排除，永不进入 Trace；前端入口与完整 Trace API 都必须校验调试权限。
