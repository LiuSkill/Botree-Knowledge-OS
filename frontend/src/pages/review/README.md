# Review Module

## 功能

审核中心用于处理资料审核和审核通过后的构建进度。

- `审核任务` 页签展示待审核、已通过和已驳回任务。
- 具备 `review:review` 权限的用户可以执行审核通过和驳回。
- `审核通过资料 / 构建进度` 页签展示已审核通过资料，支持按企业/项目、项目、分类、构建状态和关键字筛选。
- 具备 `review:review` 权限的用户可以触发“解析并构建索引”。
- 构建流程会先将同一资料旧版本 Chunk/索引置为失效，再写入当前版本有效 Chunk/索引。

## 调用关系

- `listReviewTasks` 查询审核任务。
- `approveReviewTask`、`rejectReviewTask` 处理审核动作。
- `listApprovedDocuments` 查询审核通过资料。
- `buildDocumentIndex` 触发合并构建流程。
- `listKnowledgeCategories` 和 `listProjects` 提供构建进度筛选条件。

## 输入

- 审核任务状态。
- 资料范围、项目、分类、构建状态和关键字。
- 当前用户权限编码 `permission_codes`。

## 输出

- 审核任务列表。
- 审核通过资料和构建进度列表。
- 审核处理与构建操作结果提示。

## 示例

```vue
<ReviewTaskPage />
```
