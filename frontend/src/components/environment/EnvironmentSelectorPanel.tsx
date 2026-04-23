import type { EnvironmentRecord } from '../../types';
import { useT } from '../../i18n';

interface Props {
  environments: EnvironmentRecord[];
  selectedEnvironmentId: string | null;
  selectedEnvironment: EnvironmentRecord | null;
  isLoading: boolean;
  loadError: string | null;
  hasEnvironments: boolean;
  onSelectEnvironment: (environmentId: string) => void;
}

function EnvironmentSelectorPanel({
  environments,
  selectedEnvironmentId,
  selectedEnvironment,
  isLoading,
  loadError,
  hasEnvironments,
  onSelectEnvironment,
}: Props) {
  const t = useT();

  return (
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('components.environmentSelector.eyebrow')}
        </p>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="space-y-1">
            <h2
              className="text-xl font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
              style={{ fontFamily: 'var(--font-display)' }}
            >
              {t('components.environmentSelector.title')}
            </h2>
            <p className="max-w-xl text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
              {t('components.environmentSelector.description')}
            </p>
          </div>
          <div className="inline-flex items-center gap-2 rounded-full bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm font-medium text-[var(--text)]">
            {selectedEnvironment ? (
              <span className="inline-flex items-center gap-2">
                <span className="h-2 w-2 rounded-full bg-[#34c759]" />
                <span>{selectedEnvironment.alias}</span>
                {selectedEnvironment.is_seed ? (
                  <span className="rounded-full bg-[var(--apple-blue)]/10 px-2 py-0.5 text-xs font-semibold text-[var(--apple-blue)]">
                    {t('common.default')}
                  </span>
                ) : null}
              </span>
            ) : (
              <span className="text-[var(--text-tertiary)]">
                {t('components.environmentSelector.selectedNone')}
              </span>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('components.environmentSelector.activeLabel')}
          </span>
          <select
            value={selectedEnvironmentId ?? ''}
            onChange={(event) => onSelectEnvironment(event.target.value)}
            disabled={!hasEnvironments || isLoading}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15 disabled:cursor-not-allowed disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-tertiary)]"
          >
            {!hasEnvironments ? (
              <option value="">{t('components.environmentSelector.noAvailable')}</option>
            ) : null}
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </select>
        </label>

        <div className="space-y-3 rounded-lg bg-[var(--bg-secondary)] p-4">
          <div className="flex flex-wrap gap-x-6 gap-y-2 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            <span className="font-medium text-[var(--text)]">
              {t('components.environmentSelector.selectionStatus')}
            </span>
            <span>
              {t('components.environmentSelector.loaded')}{' '}
              {isLoading ? t('common.no') : t('common.yes')}
            </span>
            <span>
              {t('components.environmentSelector.available')} {environments.length}
            </span>
          </div>

          {loadError ? (
            <p className="text-sm text-[#ff3b30]">
              {t('components.environmentSelector.loadError')} {loadError}
            </p>
          ) : null}

          {selectedEnvironment ? (
            <div className="space-y-1.5 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
              <p>
                <span className="font-medium text-[var(--text)]">
                  {t('components.environmentSelector.displayName')}
                </span>{' '}
                {selectedEnvironment.display_name}
              </p>
              <p>
                <span className="font-medium text-[var(--text)]">
                  {t('components.environmentSelector.host')}
                </span>{' '}
                {selectedEnvironment.host}:{selectedEnvironment.port}
              </p>
              <p>
                <span className="font-medium text-[var(--text)]">
                  {t('components.environmentSelector.defaultWorkdir')}
                </span>{' '}
                {selectedEnvironment.default_workdir ?? t('common.notConfigured')}
              </p>
            </div>
          ) : (
            <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {hasEnvironments
                ? t('components.environmentSelector.waitingValidSelection')
                : t('components.environmentSelector.createPrompt')}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}

export default EnvironmentSelectorPanel;
