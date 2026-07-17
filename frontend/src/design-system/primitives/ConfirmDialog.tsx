import { Button } from './Button';
import { Dialog } from './Dialog';
import { useT } from '@/shared/i18n';

export function ConfirmDialog({ open, onOpenChange, title, description, confirmLabel, onConfirm, danger = false }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const t = useT();
  return (
    <Dialog isOpen={open} onClose={() => onOpenChange(false)} title={title} size="sm">
      <p className="text-sm leading-relaxed text-[var(--osci-color-text-secondary)]">{description}</p>
      <div className="mt-5 flex justify-end gap-2">
        <Button variant="secondary" onClick={() => onOpenChange(false)}>{t('common.cancel')}</Button>
        <Button variant={danger ? 'danger' : 'primary'} onClick={() => { onConfirm(); onOpenChange(false); }}>{confirmLabel}</Button>
      </div>
    </Dialog>
  );
}
