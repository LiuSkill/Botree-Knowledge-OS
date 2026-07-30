import { showConfirmDialog } from '@/utils/confirmDialog';
import { i18n } from '@/locales';

const INDEXED_INDEX_STATUSES = new Set(['indexed', 'success', 'completed']);

export function isIndexedIndexStatus(status: string | null | undefined): boolean {
  return INDEXED_INDEX_STATUSES.has((status || '').toLowerCase());
}

export function confirmRebuildIndexedDocument(fileName: string): Promise<boolean> {
  return showConfirmDialog({
    header: i18n.global.t('common.index.rebuildHeader'),
    body: i18n.global.t('common.index.rebuildBody', { fileName: fileName || i18n.global.t('common.entity.currentDocument') }),
    confirmBtn: i18n.global.t('common.index.continueBuild'),
  });
}
