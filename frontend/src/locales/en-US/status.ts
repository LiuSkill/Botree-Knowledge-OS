export default {
  draft: 'Pending Review', submitted: 'In Review', reviewing: 'In Review', pending: 'Pending', approved: 'Published', rejected: 'Rejected',
  parsing: 'Parsing', parsed: 'Parsed', parsedPendingReview: 'Parsed, Pending Review', notIndexed: 'Not Indexed', indexing: 'Building Index', indexed: 'Indexed', indexFailed: 'Index Failed', invalid: 'Invalid',
  unparsed: 'Unparsed', parseSuccess: 'Parsed', parseFailed: 'Parse Failed', queued: 'Queued', completed: 'Completed',
  active: 'Active', archived: 'Archived', enabled: 'Enabled', disabled: 'Disabled', running: 'Running', success: 'Success', failed: 'Failed', canceled: 'Canceled',
  public: 'Public', internal: 'Internal', confidential: 'Confidential',
  review: {
    draft: 'Pending Review', submitted: 'In Review', reviewing: 'In Review', approved: 'Published', rejected: 'Rejected', archived: 'Archived',
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
