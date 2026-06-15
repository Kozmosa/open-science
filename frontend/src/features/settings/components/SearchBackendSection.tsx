import { FormField, SectionCard, SectionHeader, Select } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { SearchBackendItem } from '@/shared/types';
import { getSearchSettings, updateSearchSettings } from '@/shared/api';

export function SearchBackendSection() {
  const t = useT();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ['searchSettings'],
    queryFn: getSearchSettings,
  });
  const mutation = useMutation({
    mutationFn: updateSearchSettings,
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['searchSettings'] }); },
  });

  const activeBackend = data?.active_backend ?? 'cc-web-mcp';
  const autoStart = data?.auto_start_mcp_servers ?? ['kindly-web-search', 'cc-web-mcp'];
  const backends = data?.available_backends ?? [];

  const toggleAutoStart = (id: string) => {
    const next = autoStart.includes(id)
      ? autoStart.filter((s: string) => s !== id)
      : [...autoStart, id];
    mutation.mutate({ auto_start_mcp_servers: next });
  };

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.searchBackend.title')}
          description={t('pages.settings.searchBackend.description')}
        />
      }
    >
      <div className="space-y-4">
        <FormField label={t('pages.settings.searchBackend.activeBackend')}>
          <Select
            aria-label={t('pages.settings.searchBackend.activeBackend')}
            value={activeBackend}
            disabled={isLoading || mutation.isPending}
            onChange={(e) => mutation.mutate({ active_backend: e.target.value })}
          >
            {backends.map((b: SearchBackendItem) => (
              <option key={b.id} value={b.id}>
                {b.display_name}
              </option>
            ))}
          </Select>
        </FormField>

        <div>
          <p className="mb-2 text-sm font-medium text-[var(--text)]">
            {t('pages.settings.searchBackend.autoStart')}
          </p>
          <p className="mb-3 text-xs text-[var(--text-secondary)]">
            {t('pages.settings.searchBackend.autoStartHint')}
          </p>
          <div className="space-y-2">
            {backends
              .filter((b: SearchBackendItem) => b.requires_mcp)
              .map((b: SearchBackendItem) => (
                <label key={b.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={autoStart.includes(b.id)}
                    disabled={mutation.isPending}
                    onChange={() => toggleAutoStart(b.id)}
                    className="rounded border-[var(--border)]"
                  />
                  <span>{b.display_name}</span>
                  <span className="text-[var(--text-secondary)]">— {b.description}</span>
                </label>
              ))}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

