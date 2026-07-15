import { useState } from 'react';
import { Button, Dialog, FormField, Input, SectionCard, SectionHeader, NativeSelect } from '@design-system';
import { useT } from '@/shared/i18n';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import type { SkillDetail, SkillImportRequest, SkillItem, SkillPreview, SkillRegistryItem } from '@/shared/types';
import { getSkillDetail, getSkillRegistries, importSkill, installSkillRegistry, previewSkillSettings, updateSkillRegistry } from '@/shared/api';
import { queryKeys } from '@/shared/api/queryKeys';

export interface SkillRepositorySectionProps {
  availableSkills: SkillItem[];
}


export function SkillRepositorySection({ availableSkills }: SkillRepositorySectionProps) {
  const t = useT();
  const queryClient = useQueryClient();
  const [selectedSkillId, setSelectedSkillId] = useState<string | null>(null);
  const [showImport, setShowImport] = useState(false);
  const [importSource, setImportSource] = useState<'git' | 'local'>('git');
  const [importUrl, setImportUrl] = useState('');
  const [importPath, setImportPath] = useState('');
  const [importSkillId, setImportSkillId] = useState('');
  const [importError, setImportError] = useState<string | null>(null);
  const [showPreview, setShowPreview] = useState(false);
  const [showDirtyConfirm, setShowDirtyConfirm] = useState(false);
  const [pendingRegistryId, setPendingRegistryId] = useState<string | null>(null);

  const detailQuery = useQuery<SkillDetail>({
    queryKey: queryKeys.skills.detail(selectedSkillId),
    queryFn: () => getSkillDetail(selectedSkillId!),
    enabled: !!selectedSkillId,
  });

  const previewQuery = useQuery<SkillPreview>({
    queryKey: queryKeys.skills.preview(selectedSkillId),
    queryFn: () => previewSkillSettings(selectedSkillId!),
    enabled: !!selectedSkillId,
  });

  const importMutation = useMutation({
    mutationFn: importSkill,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.skills.all });
      setShowImport(false);
      setImportUrl('');
      setImportPath('');
      setImportSkillId('');
      setImportError(null);
    },
    onError: (err: Error) => setImportError(err.message),
  });

  const registriesQuery = useQuery({
    queryKey: queryKeys.skills.registries,
    queryFn: getSkillRegistries,
  });

  const installRegistryMutation = useMutation({
    mutationFn: installSkillRegistry,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.skills.registries });
      queryClient.invalidateQueries({ queryKey: queryKeys.skills.all });
    },
    onError: (err: Error) => {
      alert(err.message);
    },
  });

  const updateRegistryMutation = useMutation({
    mutationFn: ({ id, force }: { id: string; force: boolean }) =>
      updateSkillRegistry(id, { force }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: queryKeys.skills.registries });
      queryClient.invalidateQueries({ queryKey: queryKeys.skills.all });
      setShowDirtyConfirm(false);
      setPendingRegistryId(null);
    },
    onError: (err: unknown) => {
      const status = typeof err === 'object' && err !== null && 'status' in err ? (err as { status?: number }).status : undefined;
      if (status === 409) {
        setShowDirtyConfirm(true);
      } else {
        alert(err instanceof Error ? err.message : t('pages.settings.llmProviders.updateFailed'));
        setShowDirtyConfirm(false);
        setPendingRegistryId(null);
      }
    },
  });

  const handleImportSubmit = () => {
    setImportError(null);
    const payload: SkillImportRequest = {
      source: importSource,
      url: importSource === 'git' ? importUrl || null : null,
      local_path: importSource === 'local' ? importPath || null : null,
      skill_id: importSkillId || null,
    };
    importMutation.mutate(payload);
  };

  const getInjectModeBadgeClasses = (mode: string) => {
    switch (mode) {
      case 'auto':
        return 'rounded bg-emerald-100 px-1.5 py-0.5 text-xs font-medium text-emerald-800';
      case 'prompt_only':
        return 'rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800';
      case 'disabled':
        return 'rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600';
      default:
        return 'rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600';
    }
  };

  return (
    <SectionCard
      collapsible
      header={
        <SectionHeader
          title={t('pages.settings.skillRepository.title')}
          description={t('pages.settings.skillRepository.description')}
        />
      }
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Button onClick={() => setShowImport((current) => !current)}>
          {t('pages.settings.skillRepository.importSkill')}
        </Button>
        {(registriesQuery.data?.items ?? []).map((registry: SkillRegistryItem) => (
          <div key={registry.registry_id} className="flex items-center gap-2">
            {!registry.installed ? (
              <Button
                onClick={() => installRegistryMutation.mutate(registry.registry_id)}
                disabled={installRegistryMutation.isPending}
              >
                {installRegistryMutation.isPending
                  ? t('pages.settings.codex.installing', { name: registry.display_name })
                  : t('pages.settings.codex.install', { name: registry.display_name })}
              </Button>
            ) : registry.has_update ? (
              <Button
                onClick={() => {
                  setPendingRegistryId(registry.registry_id);
                  updateRegistryMutation.mutate({ id: registry.registry_id, force: false });
                }}
                disabled={updateRegistryMutation.isPending}
              >
                {updateRegistryMutation.isPending
                  ? t('pages.settings.codex.updating')
                  : t('pages.settings.codex.update', { name: registry.display_name })}
              </Button>
            ) : (
              <Button disabled>
                {t('pages.settings.codex.installed', { name: registry.display_name })}
              </Button>
            )}
          </div>
        ))}
      </div>

      {showImport && (
        <div className="space-y-3 rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-4">
          <h4 className="text-sm font-medium text-[var(--text-primary)]">
            {t('pages.settings.skillRepository.importTitle')}
          </h4>

          <FormField label={t('pages.settings.skillRepository.sourceLabel')}>
            <NativeSelect
              aria-label={t('pages.settings.skillRepository.sourceLabel')}
              value={importSource}
              onChange={(event) => setImportSource(event.target.value as 'git' | 'local')}
            >
              <option value="git">{t('pages.settings.skillRepository.gitSource')}</option>
              <option value="local">{t('pages.settings.skillRepository.localSource')}</option>
            </NativeSelect>
          </FormField>

          {importSource === 'git' ? (
            <FormField label={t('pages.settings.skillRepository.urlLabel')}>
              <Input
                aria-label={t('pages.settings.skillRepository.urlLabel')}
                type="text"
                value={importUrl}
                onChange={(event) => setImportUrl(event.target.value)}
                placeholder={t('pages.settings.skillRepository.placeholders.url')}
              />
            </FormField>
          ) : (
            <FormField label={t('pages.settings.skillRepository.pathLabel')}>
              <Input
                aria-label={t('pages.settings.skillRepository.pathLabel')}
                type="text"
                value={importPath}
                onChange={(event) => setImportPath(event.target.value)}
                placeholder={t('pages.settings.skillRepository.placeholders.path')}
              />
            </FormField>
          )}

          <FormField label={t('pages.settings.skillRepository.skillIdOverrideLabel')}>
            <Input
              aria-label={t('pages.settings.skillRepository.skillIdOverrideLabel')}
              type="text"
              value={importSkillId}
              onChange={(event) => setImportSkillId(event.target.value)}
            />
          </FormField>

          {importError ? <p className="text-sm text-[#ff3b30]">{importError}</p> : null}

          <div className="flex flex-wrap gap-3">
            <Button variant="secondary" onClick={() => setShowImport(false)}>
              {t('pages.settings.skillRepository.cancel')}
            </Button>
            <Button onClick={handleImportSubmit} disabled={importMutation.isPending}>
              {importMutation.isPending
                ? t('pages.settings.skillRepository.importing')
                : t('pages.settings.skillRepository.importAction')}
            </Button>
          </div>
        </div>
      )}

      <Dialog
        isOpen={showDirtyConfirm && pendingRegistryId !== null}
        onClose={() => {
          setShowDirtyConfirm(false);
          setPendingRegistryId(null);
        }}
        title={t('pages.settings.codex.updateTitle', { name: pendingRegistryId?.toUpperCase() ?? '' })}
        size="sm"
      >
        <p className="text-sm text-[var(--osci-color-text-secondary)]">
          {t('pages.settings.codex.updateWarning')}
        </p>
        <div className="mt-5 flex justify-end gap-3">
          <Button
            variant="secondary"
            onClick={() => {
              setShowDirtyConfirm(false);
              setPendingRegistryId(null);
            }}
          >
            {t('common.cancel')}
          </Button>
          <Button
            onClick={() => {
              if (pendingRegistryId) {
                updateRegistryMutation.mutate({ id: pendingRegistryId, force: true });
              }
            }}
            disabled={updateRegistryMutation.isPending}
          >
            {t('pages.settings.codex.forceUpdate')}
          </Button>
        </div>
      </Dialog>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="space-y-2">
          {availableSkills.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.settings.skillRepository.noSkills')}
            </div>
          ) : (
            availableSkills.map((skill) => (
              <button
                key={skill.skill_id}
                onClick={() => {
                  setSelectedSkillId(skill.skill_id);
                  setShowPreview(false);
                }}
                className={`flex w-full items-center justify-between rounded-lg border p-3 text-left transition-colors ${
                  selectedSkillId === skill.skill_id
                    ? 'border-[var(--accent)] bg-[var(--bg-secondary)]'
                    : 'border-[var(--border)] bg-[var(--bg-secondary)] hover:bg-[var(--bg-tertiary)]'
                }`}
              >
                <div className="min-w-0">
                  <p className="text-sm font-medium text-[var(--text-primary)]">{skill.label}</p>
                  <p className="text-xs text-[var(--text-tertiary)]">{skill.skill_id}</p>
                </div>
              </button>
            ))
          )}
        </div>

        <div className="space-y-4">
          {!selectedSkillId ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-5 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.settings.skillRepository.selectSkill')}
            </div>
          ) : detailQuery.isLoading ? (
            <p className="text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>
          ) : detailQuery.error ? (
            <p className="text-sm text-[#ff3b30]">
              {detailQuery.error instanceof Error ? detailQuery.error.message : String(detailQuery.error)}
            </p>
          ) : detailQuery.data ? (
            <div className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                  {detailQuery.data.label}
                </h3>
                <span className={getInjectModeBadgeClasses(detailQuery.data.inject_mode)}>
                  {detailQuery.data.inject_mode}
                </span>
              </div>

              <div className="grid gap-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.version')}</span>
                  <span className="text-[var(--text-primary)]">{detailQuery.data.version}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.author')}</span>
                  <span className="text-[var(--text-primary)]">{detailQuery.data.author}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.dependencies')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.dependencies.length > 0
                      ? detailQuery.data.dependencies.join(', ')
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.mcpServers')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.mcp_servers.length > 0
                      ? detailQuery.data.mcp_servers.join(', ')
                      : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.hooks')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.hooks.length > 0 ? detailQuery.data.hooks.join(', ') : '—'}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-[var(--text-secondary)]">{t('pages.settings.skillRepository.allowedAgents')}</span>
                  <span className="text-[var(--text-primary)]">
                    {detailQuery.data.allowed_agents.length > 0
                      ? detailQuery.data.allowed_agents.join(', ')
                      : '—'}
                  </span>
                </div>
              </div>

              {detailQuery.data.skill_md ? (
                <div className="space-y-2">
                  <h4 className="text-xs font-medium text-[var(--text-secondary)]">
                    {t('pages.settings.skillRepository.skillMdTitle')}
                  </h4>
                  <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-xs text-[var(--text-primary)]">
                    {detailQuery.data.skill_md}
                  </pre>
                </div>
              ) : null}

              <Button
                variant="secondary"
                onClick={() => setShowPreview((current) => !current)}
                disabled={previewQuery.isLoading}
              >
                {showPreview
                  ? t('common.cancel')
                  : t('pages.settings.skillRepository.previewSettings')}
              </Button>

              {showPreview && previewQuery.data ? (
                <div className="space-y-2">
                  <h4 className="text-xs font-medium text-[var(--text-secondary)]">
                    {t('pages.settings.skillRepository.settingsPreviewTitle')}
                  </h4>
                  <pre className="whitespace-pre-wrap rounded-lg border border-[var(--border)] bg-[var(--bg-primary)] p-3 text-xs text-[var(--text-primary)]">
                    {JSON.stringify(previewQuery.data.merged_preview, null, 2)}
                  </pre>
                </div>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>
    </SectionCard>
  );
}
