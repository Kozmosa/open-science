import { Command as CommandPrimitive } from 'cmdk';
import { Search } from 'lucide-react';
import { forwardRef } from 'react';
import { cn } from '@/shared/utils/cn';

export const Command = forwardRef<React.ElementRef<typeof CommandPrimitive>, React.ComponentPropsWithoutRef<typeof CommandPrimitive>>(
  function Command({ className, ...props }, ref) {
    return <CommandPrimitive ref={ref} className={cn('flex h-full w-full flex-col overflow-hidden rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-elevated)] text-[var(--osci-color-text)]', className)} {...props} />;
  },
);

export function CommandInput({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive.Input>) {
  return (
    <div className="flex items-center border-b border-[var(--osci-color-border)] px-3">
      <Search aria-hidden="true" className="mr-2 shrink-0 text-[var(--osci-color-text-muted)]" size={17} />
      <CommandPrimitive.Input className={cn('h-11 w-full bg-transparent text-sm outline-none placeholder:text-[var(--osci-color-text-muted)] disabled:opacity-50', className)} {...props} />
    </div>
  );
}

export function CommandList({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive.List>) {
  return <CommandPrimitive.List className={cn('max-h-80 overflow-y-auto overflow-x-hidden p-1.5', className)} {...props} />;
}

export function CommandEmpty({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive.Empty>) {
  return <CommandPrimitive.Empty className={cn('py-8 text-center text-sm text-[var(--osci-color-text-muted)]', className)} {...props} />;
}

export function CommandGroup({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive.Group>) {
  return <CommandPrimitive.Group className={cn('overflow-hidden p-1 text-sm text-[var(--osci-color-text)] [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1.5 [&_[cmdk-group-heading]]:text-xs [&_[cmdk-group-heading]]:font-semibold [&_[cmdk-group-heading]]:text-[var(--osci-color-text-muted)]', className)} {...props} />;
}

export function CommandItem({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive.Item>) {
  return <CommandPrimitive.Item className={cn('relative flex min-h-9 cursor-default select-none items-center rounded-[var(--osci-radius-sm)] px-2.5 py-2 text-sm outline-none data-[disabled=true]:pointer-events-none data-[selected=true]:bg-[var(--osci-color-primary-soft)] data-[disabled=true]:opacity-50', className)} {...props} />;
}

export function CommandSeparator({ className, ...props }: React.ComponentPropsWithoutRef<typeof CommandPrimitive.Separator>) {
  return <CommandPrimitive.Separator className={cn('-mx-1 my-1 h-px bg-[var(--osci-color-border-subtle)]', className)} {...props} />;
}
