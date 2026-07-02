import { DialogPlugin } from 'tdesign-vue-next';

const INDEXED_INDEX_STATUSES = new Set(['indexed', 'success', 'completed']);

export function isIndexedIndexStatus(status: string | null | undefined): boolean {
  return INDEXED_INDEX_STATUSES.has((status || '').toLowerCase());
}

export function confirmRebuildIndexedDocument(fileName: string): Promise<boolean> {
  return new Promise((resolve) => {
    let settled = false;
    let dialog: ReturnType<typeof DialogPlugin.confirm> | null = null;

    const settle = (confirmed: boolean): void => {
      if (settled) return;
      settled = true;
      dialog?.destroy();
      resolve(confirmed);
    };

    dialog = DialogPlugin.confirm({
      header: '确认重新构建索引',
      body: `文档“${fileName || '当前文档'}”已完成索引。重新构建会覆盖当前索引结果，是否继续？`,
      theme: 'warning',
      confirmBtn: '继续构建',
      cancelBtn: '取消',
      closeOnOverlayClick: false,
      onConfirm: () => settle(true),
      onCancel: () => settle(false),
      onCloseBtnClick: () => settle(false),
      onClose: () => settle(false),
    });
  });
}
