# Knowledge Center Module

## 功能

知识中心用于企业知识综合管理，仅聚合 `type=base` 的企业基础知识库文档。

- 左侧展示企业知识分类树，不包含项目知识库或项目文档分类。
- 右侧展示企业知识文档，支持分类、文件类型、关键词筛选和分页。
- 上传新资料必须选择企业全局分类，系统创建同一资料的首个版本 `v1`。
- 同一资料的新版本在文档详情中上传，版本号由系统按当前资料版本链递增。
- 同一资料上传新版本后，旧版本 Chunk/索引状态置为失效；历史引用继续可显示，检索只命中最新版本有效 Chunk。
- 知识中心仅提供提交审核入口；审核通过后的解析与索引构建在审核中心合并执行。

## 调用关系

路由 `/knowledge` 挂载 `src/views/knowledge/KnowledgeBaseListPage.vue`。

页面调用：

- `listKnowledgeBases({ type: 'base' })` 查询企业基础知识库。
- `listKnowledgeCategories({ scope_type: 'base' })` 查询企业全局分类树。
- `listKnowledgeBaseDocuments(id, { category_id })` 聚合企业基础知识库文档。
- `uploadKnowledgeDocument(id, file, categoryId)` 上传新资料到企业基础知识库。
- `createDocumentVersion(documentId, file, { category_id })` 上传同一资料的新版本。
- `submitDocumentReview` 提交资料审核，构建动作由审核中心调用 `buildDocumentIndex`。

项目资料仍在 `/projects` 和 `/projects/:id` 中按项目边界管理，不进入知识中心分类。

## 输入

- 企业基础知识库列表。
- 企业基础知识库下的文档列表。
- 企业全局分类树。
- 用户输入的分类、文件类型、搜索条件和上传文件。

## 输出

- 过滤后的企业知识文档列表。
- 文档上传、版本上传和审核提交结果提示。

## 示例

```vue
<KnowledgeBaseListPage />
```
