import type { ReactNode } from 'react';
import { Sheet } from './Sheet';

export function DetailDrawer({ open, onOpenChange, title, children, className }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return <Sheet open={open} onOpenChange={onOpenChange} title={title} className={className}>{children}</Sheet>;
}
