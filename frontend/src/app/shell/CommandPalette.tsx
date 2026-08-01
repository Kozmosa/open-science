import * as DialogPrimitive from '@radix-ui/react-dialog';
import { useEffect, useLayoutEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@design-system';
import type { ResolvedAppRoute } from '@/app/routeRegistry';
import { useT } from '@/shared/i18n';

interface CommandPaletteProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  routes: ResolvedAppRoute[];
}

export function CommandPalette({ open, onOpenChange, routes }: CommandPaletteProps) {
  const t = useT();
  const navigate = useNavigate();
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);

  useLayoutEffect(() => {
    if (open && !wasOpenRef.current) {
      restoreFocusRef.current = document.activeElement instanceof HTMLElement
        ? document.activeElement
        : null;
    }
    wasOpenRef.current = open;
  }, [open]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && event.key.toLowerCase() === 'p') {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onOpenChange, open]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=closed]:animate-out" />
        <DialogPrimitive.Content
          aria-label={t('layout.openCommandPalette')}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            restoreFocusRef.current?.focus();
            restoreFocusRef.current = null;
          }}
          className="fixed left-1/2 top-[16vh] z-50 w-[min(42rem,calc(100%-2rem))] -translate-x-1/2 overflow-hidden rounded-2xl border border-white/20 bg-[var(--prism-glass)] shadow-[0_28px_90px_rgb(0_0_0/0.32)] outline-none backdrop-blur-2xl backdrop-saturate-150 data-[state=open]:animate-in data-[state=closed]:animate-out"
        >
          <DialogPrimitive.Title className="sr-only">
            {t('layout.openCommandPalette')}
          </DialogPrimitive.Title>
          <Command label={t('layout.openCommandPalette')} className="rounded-2xl bg-transparent">
            <CommandInput autoFocus placeholder={t('layout.commandPlaceholder')} className="h-14 text-base" />
            <CommandList className="max-h-[min(26rem,60vh)] p-2">
              <CommandEmpty>{t('layout.commandNoResults')}</CommandEmpty>
              <CommandGroup className="p-0">
                {routes.map((route) => {
                  const Icon = route.icon;
                  return (
                    <CommandItem
                      key={route.id}
                      value={`${route.label} ${route.description} ${route.keywords.join(' ')}`}
                      className="min-h-11 rounded-xl px-3"
                      onSelect={() => {
                        navigate(route.path);
                        onOpenChange(false);
                      }}
                    >
                      <Icon aria-hidden="true" className="mr-3" size={17} />
                      <span>{route.label}</span>
                      <span className="ml-auto text-xs text-[var(--osci-color-text-muted)]">{route.path}</span>
                    </CommandItem>
                  );
                })}
              </CommandGroup>
            </CommandList>
          </Command>
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
