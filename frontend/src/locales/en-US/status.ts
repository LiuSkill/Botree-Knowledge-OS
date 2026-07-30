export default {
  draft: 'Draft', submitted: 'Submitted', reviewing: 'In Review', pending: 'Pending', approved: 'Approved', rejected: 'Rejected',
  parsing: 'Parsing', parsed: 'Parsed', parsedPendingReview: 'Parsed, Pending Review', notIndexed: 'Not Indexed', indexing: 'Building Index', indexed: 'Indexed',
  unparsed: 'Unparsed', parseSuccess: 'Parsed', parseFailed: 'Parse Failed', queued: 'Queued', completed: 'Completed',
  active: 'Active', archived: 'Archived', enabled: 'Enabled', disabled: 'Disabled', running: 'Running', success: 'Success', failed: 'Failed', canceled: 'Canceled',
  public: 'Public', internal: 'Internal', confidential: 'Confidential',
  review: {
    draft: 'Draft', submitted: 'Submitted', reviewing: 'In Review', approved: 'Approved', rejected: 'Rejected', archived: 'Archived',
  },
  indexTaskType: {
    mineruParse: 'Document Parsing',
    pageIndexBuild: 'Page Index Build',
    milvusBuild: 'Vector Index Build',
    ripgrepBuild: 'Full-text Index Build',
    graphRagBuild: 'Knowledge Graph Index Build',
    indexPublish: 'Index Publishing',
    fullBuild: 'Parse and Build Index',
  },
  project: {
    notStarted: 'Not Started',
    inProgress: 'In Progress',
    completed: 'Completed',
    archived: 'Archived',
    ready: 'Ready',
    building: 'Building',
  },
} as const;
