import * as Dialog from '@radix-ui/react-dialog';
import { AlertTriangle, Trash2, X } from 'lucide-react';

type ConfirmDialogProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: 'danger' | 'warning';
  onConfirm: () => void;
  pending?: boolean;
};

export default function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel = '确认',
  cancelLabel = '取消',
  tone = 'danger',
  onConfirm,
  pending = false,
}: ConfirmDialogProps) {
  const Icon = tone === 'danger' ? Trash2 : AlertTriangle;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="confirm-overlay" />
        <Dialog.Content className="confirm-content">
          <div className={`confirm-icon-ring is-${tone}`}>
            <Icon size={22} />
          </div>
          <Dialog.Title className="confirm-title">{title}</Dialog.Title>
          <Dialog.Description className="confirm-description">{description}</Dialog.Description>
          <div className="confirm-actions">
            <Dialog.Close asChild>
              <button className="action-button" disabled={pending} type="button">
                {cancelLabel}
              </button>
            </Dialog.Close>
            <button
              className={`action-button is-${tone}`}
              disabled={pending}
              onClick={() => onConfirm()}
              type="button"
            >
              {pending ? '处理中...' : confirmLabel}
            </button>
          </div>
          <Dialog.Close asChild>
            <button aria-label="关闭" className="confirm-close" type="button">
              <X size={16} />
            </button>
          </Dialog.Close>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
