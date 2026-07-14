import { forwardRef, type HTMLAttributes } from 'react';
import { cn } from '@/shared/utils/cn';

export const Card = forwardRef<HTMLElement, HTMLAttributes<HTMLElement>>(function Card(
  { className, ...props },
  ref,
) {
  return <section ref={ref} className={cn('rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface)] shadow-[var(--osci-shadow-sm)]', className)} {...props} />;
});

export const CardHeader = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function CardHeader(
  { className, ...props },
  ref,
) {
  return <div ref={ref} className={cn('px-6 pt-6', className)} {...props} />;
});

export const CardBody = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(function CardBody(
  { className, ...props },
  ref,
) {
  return <div ref={ref} className={cn('px-6 pb-6', className)} {...props} />;
});
