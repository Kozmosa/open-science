import {
  useRef,
  type HTMLAttributes,
} from 'react';
import { cn } from '@/shared/utils/cn';
import { useReducedMotion } from './MotionPreferences';

export type LiquidGlassVariant = 'subtle' | 'regular' | 'prominent';

export interface LiquidGlassProps extends HTMLAttributes<HTMLDivElement> {
  variant?: LiquidGlassVariant;
  interactive?: boolean;
}

export function LiquidGlass({
    children,
    className,
    variant = 'regular',
    interactive = false,
    onPointerMove,
    onPointerLeave,
    ...props
  }: LiquidGlassProps) {
  const elementRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef<number | null>(null);
  const reducedMotion = useReducedMotion();
  const enhanced = !reducedMotion
    && typeof CSS !== 'undefined'
    && typeof CSS.supports === 'function'
    && CSS.supports('backdrop-filter', 'blur(1px)')
    && CSS.supports('filter', 'url("#filter")');

  return (
    <div
      ref={elementRef}
      className={cn('osci-liquid-glass', className)}
      data-variant={variant}
      data-enhanced={enhanced ? 'true' : 'false'}
      data-interactive={enhanced && interactive ? 'true' : 'false'}
      onPointerMove={(event) => {
        onPointerMove?.(event);
        if (!enhanced || !interactive || !elementRef.current) return;
        const { clientX, clientY } = event;
        if (frameRef.current !== null) cancelAnimationFrame(frameRef.current);
        frameRef.current = requestAnimationFrame(() => {
          const element = elementRef.current;
          if (!element) return;
          const rect = element.getBoundingClientRect();
          element.style.setProperty('--osci-glass-pointer-x', `${((clientX - rect.left) / rect.width) * 100}%`);
          element.style.setProperty('--osci-glass-pointer-y', `${((clientY - rect.top) / rect.height) * 100}%`);
          element.style.setProperty('--osci-glass-shift-x', `${((clientX - rect.left) / rect.width - 0.5) * 5}px`);
          element.style.setProperty('--osci-glass-shift-y', `${((clientY - rect.top) / rect.height - 0.5) * 5}px`);
        });
      }}
      onPointerLeave={(event) => {
        onPointerLeave?.(event);
        elementRef.current?.style.removeProperty('--osci-glass-shift-x');
        elementRef.current?.style.removeProperty('--osci-glass-shift-y');
      }}
      {...props}
    >
      <span className="osci-liquid-glass__material" aria-hidden="true" />
      <div className="osci-liquid-glass__content">{children}</div>
    </div>
  );
}
