import { useEffect, useLayoutEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  DialogContent,
  DialogOverlay,
  DialogPortal,
  DialogRoot,
  DialogTitle,
  LiquidGlass,
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
    <DialogRoot open={open} onOpenChange={onOpenChange}>
      <DialogPortal>
        <DialogOverlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px] data-[state=open]:animate-in data-[state=closed]:animate-out" />
        <DialogContent
          aria-label={t('layout.openCommandPalette')}
          onCloseAutoFocus={(event) => {
            event.preventDefault();
            restoreFocusRef.current?.focus();
            restoreFocusRef.current = null;
          }}
          className="fixed left-1/2 top-[16vh] z-50 w-[min(42rem,calc(100%-2rem))] -translate-x-1/2 outline-none data-[state=open]:animate-in data-[state=closed]:animate-out"
        >
          <DialogTitle className="sr-only">
            {t('layout.openCommandPalette')}
          </DialogTitle>
          <LiquidGlass variant="prominent" interactive className="rounded-2xl">
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
          </LiquidGlass>
        </DialogContent>
      </DialogPortal>
    </DialogRoot>
  );
}
