import * as CheckboxPrimitive from '@radix-ui/react-checkbox';
import { Check, Minus } from 'lucide-react';
import { forwardRef } from 'react';
import { cn } from '@/shared/utils/cn';

export const Checkbox = forwardRef<
  React.ElementRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(function Checkbox({ className, ...props }, ref) {
  return (
    <CheckboxPrimitive.Root
      ref={ref}
      className={cn('peer inline-flex h-4 w-4 shrink-0 items-center justify-center rounded border border-[var(--osci-color-border-strong)] bg-[var(--osci-color-surface)] text-white outline-none transition focus-visible:ring-2 focus-visible:ring-[var(--osci-color-primary-soft)] data-[state=checked]:border-[var(--osci-color-primary)] data-[state=checked]:bg-[var(--osci-color-primary)] data-[state=indeterminate]:border-[var(--osci-color-primary)] data-[state=indeterminate]:bg-[var(--osci-color-primary)] disabled:cursor-not-allowed disabled:opacity-50', className)}
      {...props}
    >
      <CheckboxPrimitive.Indicator>
        {props.checked === 'indeterminate' ? <Minus aria-hidden="true" size={12} /> : <Check aria-hidden="true" size={12} />}
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
});
