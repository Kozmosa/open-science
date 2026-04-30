import { Badge, SectionCard, SectionHeader, Select, StatusDot } from '../ui';
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
    <SectionCard>
      <div className="space-y-2">
        <SectionHeader
          title={t('components.environmentSelector.title')}
          description={t('components.environmentSelector.description')}
          size="md"
        />
        <div className="inline-flex items-center gap-2 rounded-full bg-[var(--bg-tertiary)] px-3 py-1.5 text-sm font-medium text-[var(--text)]">
          {selectedEnvironment ? (
            <span className="inline-flex items-center gap-2">
              <StatusDot status="success" />
              <span>{selectedEnvironment.alias}</span>
              {selectedEnvironment.is_seed ? (
                <Badge>{t('common.default')}</Badge>
              ) : null}
            </span>
          ) : (
            <span className="text-[var(--text-tertiary)]">
              {t('components.environmentSelector.selectedNone')}
            </span>
          )}
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)]">
        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('components.environmentSelector.activeLabel')}
          </span>
          <Select
            value={selectedEnvironmentId ?? ''}
            onChange={(event) => onSelectEnvironment(event.target.value)}
            disabled={!hasEnvironments || isLoading}
            className="disabled:cursor-not-allowed disabled:bg-[var(--bg-tertiary)] disabled:text-[var(--text-tertiary)]"
          >
            {!hasEnvironments ? (
              <option value="">{t('components.environmentSelector.noAvailable')}</option>
            ) : null}
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </Select>
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
    </SectionCard>
  );
}

export default EnvironmentSelectorPanel;
