import * as ToastPrimitive from '@radix-ui/react-toast';
import { AlertCircle, AlertTriangle, CheckCircle, Info, X } from 'lucide-react';
import { createContext, useCallback, useContext, useMemo, useRef, useState, type ReactNode } from 'react';
import { useT } from '@/shared/i18n';
import { cn } from '@/shared/utils/cn';

export type ToastType = 'success' | 'error' | 'warning' | 'info';

interface ToastMessage {
  id: number;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const toastStyles: Record<ToastType, { className: string; icon: typeof Info }> = {
  success: { className: 'border-[var(--osci-color-success)] text-[var(--osci-color-success)]', icon: CheckCircle },
  error: { className: 'border-[var(--osci-color-danger)] text-[var(--osci-color-danger)]', icon: AlertCircle },
  warning: { className: 'border-[var(--osci-color-warning)] text-[var(--osci-color-warning)]', icon: AlertTriangle },
  info: { className: 'border-[var(--osci-color-primary)] text-[var(--osci-color-primary)]', icon: Info },
};

// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastContextValue {
  const value = useContext(ToastContext);
  if (value === null) throw new Error('useToast must be used within ToastProvider');
  return value;
}

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastMessage[]>([]);
  const nextId = useRef(0);
  const showToast = useCallback((message: string, type: ToastType = 'info') => {
    nextId.current += 1;
    setToasts((current) => [...current, { id: nextId.current, message, type }]);
  }, []);
  const value = useMemo(() => ({ showToast }), [showToast]);

  return (
    <ToastContext.Provider value={value}>
      <ToastPrimitive.Provider swipeDirection="right" duration={5000}>
        {children}
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onOpenChange={(open) => {
            if (!open) setToasts((current) => current.filter((item) => item.id !== toast.id));
          }} />
        ))}
        <ToastPrimitive.Viewport className="fixed bottom-5 right-5 z-[100] flex w-[min(24rem,calc(100%-2rem))] flex-col gap-2 outline-none" />
      </ToastPrimitive.Provider>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onOpenChange }: { toast: ToastMessage; onOpenChange: (open: boolean) => void }) {
  const t = useT();
  const style = toastStyles[toast.type];
  const Icon = style.icon;
  return (
    <ToastPrimitive.Root
      defaultOpen
      onOpenChange={onOpenChange}
      className={cn('grid grid-cols-[auto_1fr_auto] items-center gap-3 rounded-[var(--osci-radius-md)] border bg-[var(--osci-color-surface-elevated)] px-4 py-3 shadow-[var(--osci-shadow-overlay)]', style.className)}
    >
      <Icon aria-hidden="true" size={17} />
      <ToastPrimitive.Description className="text-sm text-[var(--osci-color-text)]">{toast.message}</ToastPrimitive.Description>
      <ToastPrimitive.Close aria-label={t('components.modal.close')} className="inline-flex h-7 w-7 items-center justify-center rounded-[var(--osci-radius-sm)] text-[var(--osci-color-text-muted)] hover:bg-[var(--osci-color-surface-subtle)] hover:text-[var(--osci-color-text)]">
        <X aria-hidden="true" size={14} />
      </ToastPrimitive.Close>
    </ToastPrimitive.Root>
  );
}
