/* eslint-disable react-refresh/only-export-components */
import * as DropdownPrimitive from '@radix-ui/react-dropdown-menu';
import { Check, ChevronRight } from 'lucide-react';
import { cn } from '@/shared/utils/cn';

export const DropdownMenu = DropdownPrimitive.Root;
export const DropdownMenuTrigger = DropdownPrimitive.Trigger;
export const DropdownMenuGroup = DropdownPrimitive.Group;
export const DropdownMenuPortal = DropdownPrimitive.Portal;
export const DropdownMenuSub = DropdownPrimitive.Sub;
export const DropdownMenuRadioGroup = DropdownPrimitive.RadioGroup;

export function DropdownMenuContent({ className, sideOffset = 6, ...props }: DropdownPrimitive.DropdownMenuContentProps) {
  return (
    <DropdownPrimitive.Portal>
      <DropdownPrimitive.Content
        sideOffset={sideOffset}
        className={cn('z-50 min-w-44 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-elevated)] p-1.5 text-sm text-[var(--osci-color-text)] shadow-[var(--osci-shadow-overlay)] outline-none', className)}
        {...props}
      />
    </DropdownPrimitive.Portal>
  );
}

export function DropdownMenuItem({ className, inset, ...props }: DropdownPrimitive.DropdownMenuItemProps & { inset?: boolean }) {
  return <DropdownPrimitive.Item className={cn('relative flex min-h-8 cursor-default select-none items-center rounded-[var(--osci-radius-sm)] px-2.5 py-1.5 outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-[var(--osci-color-primary-soft)] data-[highlighted]:text-[var(--osci-color-text)] data-[disabled]:opacity-50', inset && 'pl-8', className)} {...props} />;
}

export function DropdownMenuCheckboxItem({ className, children, checked, ...props }: DropdownPrimitive.DropdownMenuCheckboxItemProps) {
  return <DropdownPrimitive.CheckboxItem checked={checked} className={cn('relative flex min-h-8 cursor-default select-none items-center rounded-[var(--osci-radius-sm)] py-1.5 pl-8 pr-2.5 outline-none data-[highlighted]:bg-[var(--osci-color-primary-soft)]', className)} {...props}><span className="absolute left-2"><DropdownPrimitive.ItemIndicator><Check size={15} /></DropdownPrimitive.ItemIndicator></span>{children}</DropdownPrimitive.CheckboxItem>;
}

export function DropdownMenuLabel({ className, ...props }: DropdownPrimitive.DropdownMenuLabelProps) {
  return <DropdownPrimitive.Label className={cn('px-2.5 py-1.5 text-xs font-semibold text-[var(--osci-color-text-muted)]', className)} {...props} />;
}

export function DropdownMenuSeparator({ className, ...props }: DropdownPrimitive.DropdownMenuSeparatorProps) {
  return <DropdownPrimitive.Separator className={cn('-mx-1 my-1 h-px bg-[var(--osci-color-border-subtle)]', className)} {...props} />;
}

export function DropdownMenuSubTrigger({ className, children, ...props }: DropdownPrimitive.DropdownMenuSubTriggerProps) {
  return <DropdownPrimitive.SubTrigger className={cn('flex min-h-8 items-center rounded-[var(--osci-radius-sm)] px-2.5 py-1.5 outline-none data-[highlighted]:bg-[var(--osci-color-primary-soft)]', className)} {...props}>{children}<ChevronRight className="ml-auto" size={15} /></DropdownPrimitive.SubTrigger>;
}

export function DropdownMenuSubContent({ className, ...props }: DropdownPrimitive.DropdownMenuSubContentProps) {
  return <DropdownPrimitive.SubContent className={cn('z-50 min-w-40 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-elevated)] p-1.5 shadow-[var(--osci-shadow-overlay)]', className)} {...props} />;
}
