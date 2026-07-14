/* eslint-disable react-refresh/only-export-components */
import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useLayoutEffect, useRef, type ReactNode } from 'react';
import { useT } from '@/shared/i18n';
import { cn } from '@/shared/utils/cn';

interface DialogProps {
  isOpen: boolean;
  onClose: () => void;
  title?: string | null;
  ariaLabel?: string | null;
  children: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  showCloseButton?: boolean;
  closeOnBackdropClick?: boolean;
}

const sizeClasses: Record<NonNullable<DialogProps['size']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-4xl',
};

export function Dialog({
  isOpen,
  onClose,
  title = null,
  ariaLabel = null,
  children,
  size = 'md',
  showCloseButton = true,
  closeOnBackdropClick = true,
}: DialogProps) {
  const t = useT();
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);

  useLayoutEffect(() => {
    if (isOpen && !wasOpenRef.current) {
      restoreFocusRef.current = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    }
    wasOpenRef.current = isOpen;
  }, [isOpen]);

  return (
    <DialogPrimitive.Root open={isOpen} onOpenChange={(open) => { if (!open) onClose(); }}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay
          className="fixed inset-0 z-50 bg-[var(--osci-color-overlay)] data-[state=open]:animate-in data-[state=closed]:animate-out"
          onPointerDown={(event) => {
            if (!closeOnBackdropClick) event.preventDefault();
          }}
        />
        <DialogPrimitive.Content
          aria-label={title ? undefined : ariaLabel ?? undefined}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            restoreFocusRef.current?.focus();
            restoreFocusRef.current = null;
          }}
          onPointerDownOutside={(event) => { if (!closeOnBackdropClick) event.preventDefault(); }}
          className={cn(
            'fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100%-2rem)] -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-elevated)] shadow-[var(--osci-shadow-overlay)] outline-none',
            sizeClasses[size],
          )}
        >
          {title ? (
            <div className="flex items-center justify-between border-b border-[var(--osci-color-border)] px-6 py-4">
              <DialogPrimitive.Title className="text-lg font-semibold text-[var(--osci-color-text)]">
                {title}
              </DialogPrimitive.Title>
              {showCloseButton ? <DialogCloseButton label={t('components.modal.close')} /> : null}
            </div>
          ) : (
            <>
              <DialogPrimitive.Title className="sr-only">
                {ariaLabel ?? t('components.modal.dialog')}
              </DialogPrimitive.Title>
              {showCloseButton ? (
                <div className="flex justify-end px-6 pt-4">
                  <DialogCloseButton label={t('components.modal.close')} />
                </div>
              ) : null}
            </>
          )}
          <div className="px-6 py-4">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}

function DialogCloseButton({ label }: { label: string }) {
  return (
    <DialogPrimitive.Close
      className="inline-flex h-8 w-8 items-center justify-center rounded-[var(--osci-radius-sm)] text-[var(--osci-color-text-muted)] hover:bg-[var(--osci-color-surface-subtle)] hover:text-[var(--osci-color-text)]"
      aria-label={label}
    >
      <X size={18} />
    </DialogPrimitive.Close>
  );
}

export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;
