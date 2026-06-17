# AI Center Module

## 功能

提供 Botree Knowledge OS 的 AI 中心页面说明。当前 AI 中心已拆分为项目问答和基础问答，分别承载项目级隔离问答和当前用户权限范围内的基础问答。

## 调用关系

`src/router/index.ts` 将 `/ai/project-chat` 挂载到 `ProjectChatPage.vue`，将 `/ai/base-chat` 挂载到 `BaseChatPage.vue`。两个页面复用 `ChatWorkspace.vue`，并通过 `chat_type` 调用后端真实问答接口。

## 输入

- URL：`/ai/project-chat`、`/ai/base-chat`
- API：`/api/chat/sessions`、`/api/chat/completions`、`/api/projects`
- 用户操作：项目选择、会话选择、新建会话、发送问题

## 输出

- 项目问答或基础问答会话上下文
- 基于真实知识检索结果生成的回答
- 引用来源、Agent 执行过程和知识范围展示

## 示例

```vue
<ProjectChatPage />
<BaseChatPage />
```
