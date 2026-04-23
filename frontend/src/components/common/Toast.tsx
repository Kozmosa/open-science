import { useState, useEffect, createContext, type ReactNode } from 'react';
import { X, CheckCircle, AlertCircle, AlertTriangle, Info } from 'lucide-react';

type ToastType = 'success' | 'error' | 'warning' | 'info';

interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextValue {
  showToast: (message: string, type?: ToastType) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

interface ProviderProps {
  children: ReactNode;
}

export function ToastProvider({ children }: ProviderProps) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const showToast = (message: string, type: ToastType = 'info') => {
    const id = Date.now().toString();
    setToasts((prev) => [...prev, { id, message, type }]);
  };

  const removeToast = (id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  };

  return (
    <ToastContext.Provider value={{ showToast }}>
      {children}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2">
        {toasts.map((toast) => (
          <ToastItem key={toast.id} toast={toast} onClose={() => removeToast(toast.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

interface ItemProps {
  toast: Toast;
  onClose: () => void;
}

const toastStyles: Record<ToastType, { bg: string; border: string; icon: typeof Info }> = {
  success: { bg: 'bg-[#e8f5e9]', border: 'border-[#81c784]', icon: CheckCircle },
  error: { bg: 'bg-[#ffebee]', border: 'border-[#e57373]', icon: AlertCircle },
  warning: { bg: 'bg-[#fff8e1]', border: 'border-[#ffb74d]', icon: AlertTriangle },
  info: { bg: 'bg-[#e3f2fd]', border: 'border-[#64b5f6]', icon: Info },
};

function ToastItem({ toast, onClose }: ItemProps) {
  useEffect(() => {
    const timer = setTimeout(onClose, 5000);
    return () => clearTimeout(timer);
  }, [onClose]);

  const style = toastStyles[toast.type];
  const Icon = style.icon;

  return (
    <div
      className={`flex items-center gap-3 rounded-lg border ${style.border} ${style.bg} px-4 py-3 shadow-lg`}
    >
      <Icon size={16} className="shrink-0 text-[var(--apple-near-black)]" />
      <span className="text-sm tracking-[-0.224px] text-[var(--apple-near-black)]">
        {toast.message}
      </span>
      <button
        onClick={onClose}
        className="ml-2 shrink-0 rounded-md p-0.5 text-[var(--apple-near-black)]/50 transition hover:bg-black/5 hover:text-[var(--apple-near-black)]"
      >
        <X size={14} />
      </button>
    </div>
  );
}
