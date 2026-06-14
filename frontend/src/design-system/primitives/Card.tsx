import { type HTMLAttributes, type ReactNode } from 'react';
import { cn } from '@/shared/utils/cn';

interface CardProps extends HTMLAttributes<HTMLElement> {
  children: ReactNode;
}

interface CardSectionProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode;
}

export function Card({ children, className = '', ...rest }: CardProps) {
  return (
    <section
      className={cn('rounded-xl bg-[var(--surface)] shadow-[var(--shadow-card)]', className)}
      {...rest}
    >
      {children}
    </section>
  );
}

export function CardHeader({ children, className = '', ...rest }: CardSectionProps) {
  return (
    <div className={cn('px-6 pt-6', className)} {...rest}>
      {children}
    </div>
  );
}

export function CardBody({ children, className = '', ...rest }: CardSectionProps) {
  return (
    <div className={cn('px-6 pb-6', className)} {...rest}>
      {children}
    </div>
  );
}
