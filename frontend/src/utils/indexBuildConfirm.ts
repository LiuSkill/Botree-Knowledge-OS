import { showConfirmDialog } from '@/utils/confirmDialog';

const INDEXED_INDEX_STATUSES = new Set(['indexed', 'success', 'completed']);

export function isIndexedIndexStatus(status: string | null | undefined): boolean {
  return INDEXED_INDEX_STATUSES.has((status || '').toLowerCase());
}

export function confirmRebuildIndexedDocument(fileName: string): Promise<boolean> {
  return showConfirmDialog({
    header: '确认重新构建索引',
    body: `文档“${fileName || '当前文档'}”已完成索引。重新构建会覆盖当前索引结果，是否继续？`,
    confirmBtn: '继续构建',
  });
}
