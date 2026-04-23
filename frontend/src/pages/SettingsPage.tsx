import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getEnvironments } from '../api';
import { useT } from '../i18n';
import {
  clampTerminalFontSize,
  maxTerminalFontSize,
  minTerminalFontSize,
  useSettings,
} from '../settings';
import type { DefaultRoute, EnvironmentTaskDefaults, WebUiSettingsDocument } from '../settings';
import type { EnvironmentRecord } from '../types';

interface GeneralDraftState {
  defaultRoute: DefaultRoute;
  terminalFontSize: string;
}

interface GeneralPreferencesSectionProps {
  savedGeneral: WebUiSettingsDocument['general'];
  onSave: (general: WebUiSettingsDocument['general']) => void;
  onReset: () => void;
}

interface EnvironmentDefaultsCardProps {
  environment: EnvironmentRecord;
  savedDefaults: EnvironmentTaskDefaults;
  onSave: (defaults: EnvironmentTaskDefaults) => void;
  onReset: () => void;
}

interface ProjectDefaultsSectionProps {
  environments: EnvironmentRecord[];
  savedDefaultEnvironmentId: string | null;
  isLoading: boolean;
  loadError: string | null;
  getProjectEnvironmentDefaults: (environmentId: string | null) => EnvironmentTaskDefaults;
  saveProjectDefaultEnvironment: (environmentId: string | null) => void;
  saveProjectEnvironmentDefaults: (
    environmentId: string,
    defaults: EnvironmentTaskDefaults
  ) => void;
  resetProjectEnvironmentDefaults: (environmentId: string) => void;
}

function hasEnvironmentDefaultChanges(
  left: EnvironmentTaskDefaults,
  right: EnvironmentTaskDefaults
): boolean {
  return (
    left.titleTemplate !== right.titleTemplate ||
    left.taskInputTemplate !== right.taskInputTemplate
  );
}

function GeneralPreferencesSection({
  savedGeneral,
  onSave,
  onReset,
}: GeneralPreferencesSectionProps) {
  const t = useT();
  const [draft, setDraft] = useState<GeneralDraftState>({
    defaultRoute: savedGeneral.defaultRoute,
    terminalFontSize: String(savedGeneral.terminal.fontSize),
  });
  const clampedFontSize = clampTerminalFontSize(Number.parseInt(draft.terminalFontSize, 10));
  const hasChanges =
    draft.defaultRoute !== savedGeneral.defaultRoute ||
    clampedFontSize !== savedGeneral.terminal.fontSize;

  return (
    <section className="space-y-5 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="space-y-1">
        <h2 className="text-lg font-medium text-gray-900">{t('pages.settings.general.title')}</h2>
        <p className="text-sm text-gray-600">{t('pages.settings.general.description')}</p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <label className="space-y-2">
          <span className="text-sm font-medium text-gray-900">
            {t('pages.settings.general.defaultRouteLabel')}
          </span>
          <select
            aria-label={t('pages.settings.general.defaultRouteLabel')}
            value={draft.defaultRoute}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                defaultRoute: event.target.value as DefaultRoute,
              }))
            }
            className="w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)]"
          >
            <option value="terminal">{t('pages.settings.routes.terminal')}</option>
            <option value="tasks">{t('pages.settings.routes.tasks')}</option>
            <option value="workspaces">{t('pages.settings.routes.workspaces')}</option>
            <option value="containers">{t('pages.settings.routes.containers')}</option>
          </select>
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium text-gray-900">
            {t('pages.settings.general.terminalFontSizeLabel')}
          </span>
          <input
            aria-label={t('pages.settings.general.terminalFontSizeLabel')}
            type="number"
            min={minTerminalFontSize}
            max={maxTerminalFontSize}
            step={1}
            value={draft.terminalFontSize}
            onChange={(event) =>
              setDraft((current) => ({
                ...current,
                terminalFontSize: event.target.value,
              }))
            }
            className="w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)]"
          />
        </label>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-gray-200 bg-gray-50 px-4 py-3 text-sm text-gray-600">
        <p>
          {t('pages.settings.general.terminalFontSizeHelp', {
            min: minTerminalFontSize,
            max: maxTerminalFontSize,
            current: clampedFontSize,
          })}
        </p>
        <div className="flex flex-wrap gap-3">
          <button
            type="button"
            onClick={onReset}
            className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50"
          >
            {t('common.reset')}
          </button>
          <button
            type="button"
            onClick={() =>
              onSave({
                defaultRoute: draft.defaultRoute,
                terminal: {
                  fontSize: clampedFontSize,
                },
              })
            }
            disabled={!hasChanges}
            className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t('common.saveChanges')}
          </button>
        </div>
      </div>
    </section>
  );
}

function EnvironmentDefaultsCard({
  environment,
  savedDefaults,
  onSave,
  onReset,
}: EnvironmentDefaultsCardProps) {
  const t = useT();
  const [draft, setDraft] = useState<EnvironmentTaskDefaults>(savedDefaults);
  const hasChanges = hasEnvironmentDefaultChanges(draft, savedDefaults);

  return (
    <section className="space-y-4 rounded-2xl border border-gray-200 bg-white p-5">
      <div className="space-y-1">
        <h3 className="text-base font-semibold text-gray-900">
          {environment.alias} · {environment.display_name}
        </h3>
        <p className="text-sm text-gray-600">
          {t('pages.settings.project.environmentCardDescription')}
        </p>
      </div>

      <label className="block space-y-2">
        <span className="text-sm font-medium text-gray-700">
          {t('pages.settings.project.titleTemplateLabel')}
        </span>
        <input
          aria-label={`${environment.alias} ${t('pages.settings.project.titleTemplateLabel')}`}
          value={draft.titleTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              titleTemplate: event.target.value,
            }))
          }
          className="w-full rounded-xl border border-gray-300 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/15"
          placeholder={t('pages.settings.project.titleTemplatePlaceholder')}
        />
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium text-gray-700">
          {t('pages.settings.project.taskInputTemplateLabel')}
        </span>
        <textarea
          aria-label={`${environment.alias} ${t('pages.settings.project.taskInputTemplateLabel')}`}
          value={draft.taskInputTemplate}
          onChange={(event) =>
            setDraft((current) => ({
              ...current,
              taskInputTemplate: event.target.value,
            }))
          }
          className="min-h-32 w-full rounded-xl border border-gray-300 px-4 py-3 text-sm shadow-sm outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent)]/15"
          placeholder={t('pages.settings.project.taskInputTemplatePlaceholder')}
        />
      </label>

      <div className="flex flex-wrap justify-end gap-3">
        <button
          type="button"
          onClick={onReset}
          className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50"
        >
          {t('common.reset')}
        </button>
        <button
          type="button"
          onClick={() => onSave(draft)}
          disabled={!hasChanges}
          className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {t('common.saveChanges')}
        </button>
      </div>
    </section>
  );
}

function ProjectDefaultsSection({
  environments,
  savedDefaultEnvironmentId,
  isLoading,
  loadError,
  getProjectEnvironmentDefaults,
  saveProjectDefaultEnvironment,
  saveProjectEnvironmentDefaults,
  resetProjectEnvironmentDefaults,
}: ProjectDefaultsSectionProps) {
  const t = useT();
  const [defaultEnvironmentDraft, setDefaultEnvironmentDraft] = useState<string>(
    savedDefaultEnvironmentId ?? ''
  );
  const persistedProjectDefaultEnvironmentId = savedDefaultEnvironmentId ?? '';
  const hasProjectDefaultChanges = defaultEnvironmentDraft !== persistedProjectDefaultEnvironmentId;

  return (
    <section className="space-y-5 rounded-2xl border border-gray-200 bg-white p-6 shadow-sm">
      <div className="space-y-1">
        <h2 className="text-lg font-medium text-gray-900">{t('pages.settings.project.title')}</h2>
        <p className="text-sm text-gray-600">{t('pages.settings.project.description')}</p>
      </div>

      <div className="space-y-4 rounded-2xl border border-gray-200 bg-gray-50 p-4">
        <label className="space-y-2">
          <span className="text-sm font-medium text-gray-900">
            {t('pages.settings.project.defaultEnvironmentLabel')}
          </span>
          <select
            aria-label={t('pages.settings.project.defaultEnvironmentLabel')}
            value={defaultEnvironmentDraft}
            onChange={(event) => setDefaultEnvironmentDraft(event.target.value)}
            disabled={environments.length === 0}
            className="w-full rounded-xl border border-gray-300 bg-white px-3 py-2 text-sm outline-none transition focus:border-[var(--accent)] disabled:cursor-not-allowed disabled:bg-gray-100"
          >
            <option value="">{t('pages.settings.project.defaultEnvironmentEmpty')}</option>
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </select>
        </label>

        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm text-gray-600">{t('pages.settings.project.defaultEnvironmentHelp')}</p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => saveProjectDefaultEnvironment(null)}
              className="rounded-full border border-gray-300 bg-white px-4 py-2 text-sm font-semibold text-gray-700 transition hover:border-gray-400 hover:bg-gray-50"
            >
              {t('common.reset')}
            </button>
            <button
              type="button"
              onClick={() => saveProjectDefaultEnvironment(defaultEnvironmentDraft || null)}
              disabled={!hasProjectDefaultChanges}
              className="rounded-full bg-[var(--accent)] px-4 py-2 text-sm font-semibold text-white transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {t('common.saveChanges')}
            </button>
          </div>
        </div>
      </div>

      {isLoading ? <p className="text-sm text-gray-500">{t('common.loading')}</p> : null}
      {loadError ? <p className="text-sm text-red-700">{loadError}</p> : null}
      {environments.length === 0 && !isLoading ? (
        <div className="rounded-2xl border border-dashed border-gray-300 bg-gray-50 p-5 text-sm text-gray-500">
          {t('pages.settings.project.noEnvironments')}
        </div>
      ) : null}

      <div className="grid gap-4 xl:grid-cols-2">
        {environments.map((environment) => {
          const savedDefaults = getProjectEnvironmentDefaults(environment.id);
          return (
            <EnvironmentDefaultsCard
              key={`${environment.id}:${savedDefaults.titleTemplate}:${savedDefaults.taskInputTemplate}`}
              environment={environment}
              savedDefaults={savedDefaults}
              onSave={(defaults) => saveProjectEnvironmentDefaults(environment.id, defaults)}
              onReset={() => resetProjectEnvironmentDefaults(environment.id)}
            />
          );
        })}
      </div>
    </section>
  );
}

function SettingsPage() {
  const t = useT();
  const environmentsQuery = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });
  const {
    settings,
    recoveryReason,
    saveGeneralPreferences,
    resetGeneralPreferences,
    saveProjectDefaultEnvironment,
    saveProjectEnvironmentDefaults,
    resetProjectEnvironmentDefaults,
    getProjectEnvironmentDefaults,
  } = useSettings();

  const environments = useMemo(
    () => environmentsQuery.data?.items ?? [],
    [environmentsQuery.data]
  );
  const environmentsError =
    environmentsQuery.error instanceof Error ? environmentsQuery.error.message : null;

  return (
    <div className="px-4 py-8 sm:px-6 lg:px-8">
      <section className="mb-8 space-y-3">
        <p className="text-sm font-medium uppercase tracking-wide text-[var(--accent)]">
          {t('pages.settings.eyebrow')}
        </p>
        <h1 className="text-3xl font-semibold text-gray-900">{t('pages.settings.title')}</h1>
        <p className="max-w-3xl text-sm text-gray-600 sm:text-base">
          {t('pages.settings.description')}
        </p>
      </section>

      <div className="space-y-6">
        {recoveryReason !== null ? (
          <section className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            {t('pages.settings.recoveryNotice')}
          </section>
        ) : null}

        <GeneralPreferencesSection
          key={`general:${settings.general.defaultRoute}:${settings.general.terminal.fontSize}`}
          savedGeneral={settings.general}
          onSave={saveGeneralPreferences}
          onReset={resetGeneralPreferences}
        />

        <ProjectDefaultsSection
          key={`project-default:${settings.projectDefaults.default.defaultEnvironmentId ?? 'none'}`}
          environments={environments}
          savedDefaultEnvironmentId={settings.projectDefaults.default.defaultEnvironmentId}
          isLoading={environmentsQuery.isLoading}
          loadError={environmentsError}
          getProjectEnvironmentDefaults={getProjectEnvironmentDefaults}
          saveProjectDefaultEnvironment={saveProjectDefaultEnvironment}
          saveProjectEnvironmentDefaults={saveProjectEnvironmentDefaults}
          resetProjectEnvironmentDefaults={resetProjectEnvironmentDefaults}
        />
      </div>
    </div>
  );
}

export default SettingsPage;
