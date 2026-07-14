/* eslint-disable react-refresh/only-export-components */
import * as TooltipPrimitive from '@radix-ui/react-tooltip';
import { cn } from '@/shared/utils/cn';

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

export function TooltipContent({ className, sideOffset = 5, ...props }: TooltipPrimitive.TooltipContentProps) {
  return <TooltipPrimitive.Portal><TooltipPrimitive.Content sideOffset={sideOffset} className={cn('z-50 rounded-[var(--osci-radius-sm)] bg-[var(--osci-color-text)] px-2.5 py-1.5 text-xs text-[var(--osci-color-canvas)] shadow-[var(--osci-shadow-md)]', className)} {...props} /></TooltipPrimitive.Portal>;
}
