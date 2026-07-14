/* eslint-disable react-refresh/only-export-components */
import * as TabsPrimitive from '@radix-ui/react-tabs';
import { cn } from '@/shared/utils/cn';

export const Tabs = TabsPrimitive.Root;

export function TabsList({ className, ...props }: TabsPrimitive.TabsListProps) {
  return <TabsPrimitive.List className={cn('inline-flex min-h-10 items-center gap-1 rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-1 text-[var(--osci-color-text-muted)]', className)} {...props} />;
}

export function TabsTrigger({ className, ...props }: TabsPrimitive.TabsTriggerProps) {
  return <TabsPrimitive.Trigger className={cn('inline-flex min-h-8 items-center justify-center rounded-[var(--osci-radius-sm)] px-3 py-1.5 text-sm font-medium outline-none transition focus-visible:ring-2 focus-visible:ring-[var(--osci-color-primary-soft)] data-[state=active]:bg-[var(--osci-color-surface-elevated)] data-[state=active]:text-[var(--osci-color-text)] data-[state=active]:shadow-[var(--osci-shadow-sm)] disabled:opacity-50', className)} {...props} />;
}

export function TabsContent({ className, ...props }: TabsPrimitive.TabsContentProps) {
  return <TabsPrimitive.Content className={cn('mt-4 outline-none focus-visible:ring-2 focus-visible:ring-[var(--osci-color-primary-soft)]', className)} {...props} />;
}
