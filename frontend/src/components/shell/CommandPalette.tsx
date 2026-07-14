import { useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  Dialog,
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
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault();
        onOpenChange(!open);
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [onOpenChange, open]);

  return (
    <Dialog
      isOpen={open}
      onClose={() => onOpenChange(false)}
      title={t('layout.openCommandPalette')}
      size="lg"
    >
      <Command>
        <CommandInput autoFocus placeholder={t('layout.commandPlaceholder')} />
        <CommandList>
          <CommandEmpty>{t('layout.commandNoResults')}</CommandEmpty>
          <CommandGroup>
            {routes.map((route) => {
              const Icon = route.icon;
              return (
                <CommandItem
                  key={route.id}
                  value={`${route.label} ${route.description} ${route.keywords.join(' ')}`}
                  onSelect={() => {
                    navigate(route.path);
                    onOpenChange(false);
                  }}
                >
                  <Icon aria-hidden="true" className="mr-2" size={16} />
                  <span>{route.label}</span>
                  <span className="ml-auto text-xs text-[var(--osci-color-text-muted)]">{route.path}</span>
                </CommandItem>
              );
            })}
          </CommandGroup>
        </CommandList>
      </Command>
    </Dialog>
  );
}
