import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  side?: 'left' | 'right';
  className?: string;
}

export function Sheet({ open, onOpenChange, title, children, side = 'right', className }: SheetProps) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-[var(--osci-color-overlay)]" />
        <DialogPrimitive.Content
          className={cn(
            'fixed inset-y-0 z-50 flex w-[min(24rem,calc(100%-1.5rem))] flex-col border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] shadow-[var(--osci-shadow-overlay)] outline-none',
            side === 'left' ? 'left-0 border-r' : 'right-0 border-l',
            className,
          )}
        >
          <div className="flex h-12 items-center justify-between border-b border-[var(--osci-color-border)] px-4">
            <DialogPrimitive.Title className="truncate text-sm font-semibold text-[var(--osci-color-text)]">
              {title}
            </DialogPrimitive.Title>
            <DialogPrimitive.Close aria-label="Close" className="inline-flex h-8 w-8 items-center justify-center rounded-[var(--osci-radius-sm)] text-[var(--osci-color-text-muted)] hover:bg-[var(--osci-color-surface-subtle)]">
              <X size={17} />
            </DialogPrimitive.Close>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
