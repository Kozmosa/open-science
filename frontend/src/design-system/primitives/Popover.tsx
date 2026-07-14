/* eslint-disable react-refresh/only-export-components */
import * as PopoverPrimitive from '@radix-ui/react-popover';
import { cn } from '@/shared/utils/cn';

export const Popover = PopoverPrimitive.Root;
export const PopoverTrigger = PopoverPrimitive.Trigger;
export const PopoverAnchor = PopoverPrimitive.Anchor;

export function PopoverContent({ className, align = 'center', sideOffset = 6, ...props }: PopoverPrimitive.PopoverContentProps) {
  return <PopoverPrimitive.Portal><PopoverPrimitive.Content align={align} sideOffset={sideOffset} className={cn('z-50 w-72 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-elevated)] p-4 text-[var(--osci-color-text)] shadow-[var(--osci-shadow-overlay)] outline-none', className)} {...props} /></PopoverPrimitive.Portal>;
}
