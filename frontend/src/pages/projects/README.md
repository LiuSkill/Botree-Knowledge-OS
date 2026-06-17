# Projects Module

## 功能

项目中心用于管理项目资料的项目边界。

- `/projects` 展示项目列表，支持搜索、新建、编辑和进入项目详情。
- `/projects/:id` 展示项目详情、项目资料分类树、项目资料列表和项目成员。
- 项目资料分类为项目内独立分类，使用 `scope_type = project + project_id` 隔离，不继承企业分类。
- 上传项目资料必须选择当前项目内分类，新资料首次版本为 `v1`。
- 项目详情页仅提供提交审核；解析与索引构建由审核中心统一执行。

## 调用关系

- `listProjects`、`getProject` 查询项目列表和详情。
- `listKnowledgeCategories({ scope_type: 'project', project_id })` 查询项目内分类树。
- `createKnowledgeCategory`、`updateKnowledgeCategory`、`deleteKnowledgeCategory` 维护项目分类。
- `uploadKnowledgeDocument(projectKnowledgeBaseId, file, categoryId)` 上传项目资料。
- `listDocuments({ project_id, knowledge_type: 'project' })` 查询项目资料。
- `submitDocumentReview` 提交资料审核。

## 输入

- 项目列表和路由中的项目 ID。
- 项目内分类树。
- 用户选择的资料分类、上传文件和项目资料筛选条件。

## 输出

- 项目卡片列表。
- 项目资料分类树。
- 按项目隔离的资料列表和审核提交结果。

## 示例

```vue
<ProjectDetailPage />
```
