import { DialogPlugin, type DialogOptions } from 'tdesign-vue-next';

export interface ConfirmDialogOptions {
  header: string;
  body: string;
  theme?: DialogOptions['theme'];
  confirmBtn?: string;
  cancelBtn?: string;
}

/**
 * 使用 TDesign 提供统一的二次确认交互，并将回调式 API 转换为 Promise。
 */
export function showConfirmDialog(options: ConfirmDialogOptions): Promise<boolean> {
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
      ...options,
      theme: options.theme ?? 'warning',
      confirmBtn: options.confirmBtn ?? '确认',
      cancelBtn: options.cancelBtn ?? '取消',
      closeOnOverlayClick: false,
      onConfirm: () => settle(true),
      onCancel: () => settle(false),
      onCloseBtnClick: () => settle(false),
      onClose: () => settle(false),
    });
  });
}
