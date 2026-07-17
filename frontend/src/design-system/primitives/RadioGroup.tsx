import * as RadioGroupPrimitive from '@radix-ui/react-radio-group';
import { Circle } from 'lucide-react';
import { forwardRef } from 'react';
import { cn } from '@/shared/utils/cn';

export const RadioGroup = forwardRef<
  React.ElementRef<typeof RadioGroupPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Root>
>(function RadioGroup({ className, ...props }, ref) {
  return <RadioGroupPrimitive.Root ref={ref} className={cn('grid gap-2', className)} {...props} />;
});

export const RadioGroupItem = forwardRef<
  React.ElementRef<typeof RadioGroupPrimitive.Item>,
  React.ComponentPropsWithoutRef<typeof RadioGroupPrimitive.Item>
>(function RadioGroupItem({ className, ...props }, ref) {
  return (
    <RadioGroupPrimitive.Item
      ref={ref}
      className={cn('inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-full border border-[var(--osci-color-border-strong)] bg-[var(--osci-color-surface)] text-[var(--osci-color-primary)] outline-none transition focus-visible:ring-2 focus-visible:ring-[var(--osci-color-primary-soft)] disabled:cursor-not-allowed disabled:opacity-50', className)}
      {...props}
    >
      <RadioGroupPrimitive.Indicator>
        <Circle aria-hidden="true" className="fill-current" size={9} />
      </RadioGroupPrimitive.Indicator>
    </RadioGroupPrimitive.Item>
  );
});
