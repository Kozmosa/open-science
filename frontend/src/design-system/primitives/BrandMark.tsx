import { cn } from '@/shared/utils/cn';

interface BrandMarkProps {
  className?: string;
  showName?: boolean;
}

export function BrandMark({ className, showName = true }: BrandMarkProps) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <img src="/openscience-mark.svg" alt="" aria-hidden="true" className="h-8 w-8 shrink-0" />
      {showName ? (
        <span className="text-lg font-semibold tracking-tight text-[var(--osci-color-text)]">
          OpenScience
        </span>
      ) : null}
    </span>
  );
}
