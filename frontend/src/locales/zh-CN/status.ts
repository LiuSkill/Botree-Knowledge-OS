export default {
  draft: '待审核', submitted: '审核中', reviewing: '审核中', pending: '待处理', approved: '已发布', rejected: '已驳回',
  parsing: '解析中', parsed: '已解析', parsedPendingReview: '解析完成待审核', notIndexed: '未索引', indexing: '索引构建中', indexed: '已索引', indexFailed: '索引失败', invalid: '已失效',
  unparsed: '未解析', parseSuccess: '已解析', parseFailed: '解析失败', queued: '排队中', completed: '已完成',
  active: '启用', archived: '已归档', enabled: '启用', disabled: '禁用', running: '运行中', success: '成功', failed: '失败', canceled: '已取消',
  public: '公开', internal: '内部', confidential: '机密',
  review: {
    draft: '待审核', submitted: '审核中', reviewing: '审核中', approved: '已发布', rejected: '已驳回', archived: '已归档',
  },
  indexTaskType: {
    mineruParse: '文档解析',
    pageIndexBuild: '页面索引构建',
    milvusBuild: '向量索引构建',
    ripgrepBuild: '全文检索索引构建',
    graphRagBuild: '知识图谱索引构建',
    indexPublish: '索引发布',
    fullBuild: '解析并构建索引',
  },
  project: {
    notStarted: '待启动',
    inProgress: '进行中',
    completed: '已完成',
    archived: '已归档',
    ready: '就绪',
    building: '构建中',
  },
} as const;
