/* eslint-disable react-refresh/only-export-components */
import * as SelectPrimitive from '@radix-ui/react-select';
import { Check, ChevronDown, ChevronUp } from 'lucide-react';
import { cn } from '@/shared/utils/cn';

export const Select = SelectPrimitive.Root;
export const SelectGroup = SelectPrimitive.Group;
export const SelectValue = SelectPrimitive.Value;

export function SelectTrigger({ className, children, ...props }: SelectPrimitive.SelectTriggerProps) {
  return (
    <SelectPrimitive.Trigger
      className={cn(
        'flex min-h-10 w-full items-center justify-between rounded-[var(--osci-radius-sm)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-3 py-2 text-sm text-[var(--osci-color-text)] outline-none transition focus:border-[var(--osci-color-primary)] focus:ring-2 focus:ring-[var(--osci-color-primary-soft)] disabled:cursor-not-allowed disabled:opacity-50',
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <ChevronDown aria-hidden="true" className="ml-2 shrink-0 text-[var(--osci-color-text-muted)]" size={16} />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({ className, children, position = 'popper', ...props }: SelectPrimitive.SelectContentProps) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position={position}
        className={cn(
          'z-50 max-h-80 min-w-[8rem] overflow-hidden rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface-elevated)] text-[var(--osci-color-text)] shadow-[var(--osci-shadow-overlay)]',
          position === 'popper' && 'w-[var(--radix-select-trigger-width)]',
          className,
        )}
        {...props}
      >
        <SelectPrimitive.ScrollUpButton className="flex h-7 items-center justify-center">
          <ChevronUp aria-hidden="true" size={15} />
        </SelectPrimitive.ScrollUpButton>
        <SelectPrimitive.Viewport className="p-1.5">{children}</SelectPrimitive.Viewport>
        <SelectPrimitive.ScrollDownButton className="flex h-7 items-center justify-center">
          <ChevronDown aria-hidden="true" size={15} />
        </SelectPrimitive.ScrollDownButton>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

export function SelectLabel({ className, ...props }: SelectPrimitive.SelectLabelProps) {
  return <SelectPrimitive.Label className={cn('px-2 py-1.5 text-xs font-semibold text-[var(--osci-color-text-muted)]', className)} {...props} />;
}

export function SelectItem({ className, children, ...props }: SelectPrimitive.SelectItemProps) {
  return (
    <SelectPrimitive.Item
      className={cn(
        'relative flex min-h-8 cursor-default select-none items-center rounded-[var(--osci-radius-sm)] py-1.5 pl-8 pr-2 outline-none data-[disabled]:pointer-events-none data-[highlighted]:bg-[var(--osci-color-primary-soft)] data-[disabled]:opacity-50',
        className,
      )}
      {...props}
    >
      <span className="absolute left-2 flex h-4 w-4 items-center justify-center">
        <SelectPrimitive.ItemIndicator><Check aria-hidden="true" size={14} /></SelectPrimitive.ItemIndicator>
      </span>
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
    </SelectPrimitive.Item>
  );
}

export function SelectSeparator({ className, ...props }: SelectPrimitive.SelectSeparatorProps) {
  return <SelectPrimitive.Separator className={cn('-mx-1 my-1 h-px bg-[var(--osci-color-border-subtle)]', className)} {...props} />;
}
