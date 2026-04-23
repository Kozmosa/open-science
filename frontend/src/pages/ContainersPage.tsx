import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type FormEvent } from 'react';
import {
  createProjectEnvironmentReference,
  createEnvironment,
  deleteProjectEnvironmentReference,
  deleteEnvironment,
  detectEnvironment,
  updateProjectEnvironmentReference,
  updateEnvironment,
} from '../api';
import type {
  EnvironmentAuthKind,
  EnvironmentCreateRequest,
  EnvironmentListResponse,
  EnvironmentRecord,
  EnvironmentUpdateRequest,
  ProjectEnvironmentReference,
  ProjectEnvironmentReferenceListResponse,
  ProjectEnvironmentReferenceUpdateRequest,
} from '../types';
import { useLocale, useT } from '../i18n';
import { useEnvironmentSelection } from '../components';

const environmentsQueryKey = ['environments'] as const;
const projectEnvironmentRefsQueryKey = ['project-environment-refs', 'default'] as const;
const EMPTY_ENVIRONMENTS: EnvironmentRecord[] = [];
const EMPTY_PROJECT_REFS: ProjectEnvironmentReference[] = [];
const defaultProjectId = 'default';

type EnvironmentEditorMode = 'create' | 'edit';

interface EnvironmentFormValues {
  alias: string;
  display_name: string;
  description: string;
  tags: string;
  host: string;
  port: string;
  user: string;
  auth_kind: EnvironmentAuthKind;
  identity_file: string;
  proxy_jump: string;
  proxy_command: string;
  ssh_options: string;
  default_workdir: string;
  preferred_python: string;
  preferred_env_manager: string;
  preferred_runtime_notes: string;
  task_harness_profile: string;
}

const emptyFormValues = (): EnvironmentFormValues => ({
  alias: '',
  display_name: '',
  description: '',
  tags: '',
  host: '',
  port: '22',
  user: 'root',
  auth_kind: 'ssh_key',
  identity_file: '',
  proxy_jump: '',
  proxy_command: '',
  ssh_options: '{}',
  default_workdir: '',
  preferred_python: '',
  preferred_env_manager: '',
  preferred_runtime_notes: '',
  task_harness_profile: '',
});

function valuesFromEnvironment(environment: EnvironmentRecord): EnvironmentFormValues {
  return {
    alias: environment.alias,
    display_name: environment.display_name,
    description: environment.description ?? '',
    tags: environment.tags.join(', '),
    host: environment.host,
    port: String(environment.port),
    user: environment.user,
    auth_kind: environment.auth_kind,
    identity_file: environment.identity_file ?? '',
    proxy_jump: environment.proxy_jump ?? '',
    proxy_command: environment.proxy_command ?? '',
    ssh_options: JSON.stringify(environment.ssh_options, null, 2),
    default_workdir: environment.default_workdir ?? '',
    preferred_python: environment.preferred_python ?? '',
    preferred_env_manager: environment.preferred_env_manager ?? '',
    preferred_runtime_notes: environment.preferred_runtime_notes ?? '',
    task_harness_profile: environment.task_harness_profile ?? '',
  };
}

function parseTags(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function parseJsonObject(
  value: string,
  objectErrorMessage: string,
  valuesErrorMessage: string
): Record<string, string> {
  const trimmed = value.trim();
  if (!trimmed) {
    return {};
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(trimmed) as unknown;
  } catch {
    throw new Error(objectErrorMessage);
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error(objectErrorMessage);
  }

  const entries = Object.entries(parsed as Record<string, unknown>);
  const normalized: Record<string, string> = {};
  for (const [key, entryValue] of entries) {
    if (typeof entryValue !== 'string') {
      throw new Error(valuesErrorMessage);
    }
    normalized[key] = entryValue;
  }
  return normalized;
}

function formatTimestamp(value: string | null, locale: string, neverLabel: string): string {
  if (!value) {
    return neverLabel;
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return parsed.toLocaleString(locale === 'zh' ? 'zh-CN' : 'en-US');
}

function mergeEnvironmentList(
  current: EnvironmentListResponse | undefined,
  environment: EnvironmentRecord
): EnvironmentListResponse {
  const items = current?.items ?? [];
  const nextItems = [...items];
  const index = nextItems.findIndex((item) => item.id === environment.id);
  if (index === -1) {
    nextItems.unshift(environment);
  } else {
    nextItems[index] = environment;
  }
  return { items: nextItems };
}

function removeEnvironmentFromList(
  current: EnvironmentListResponse | undefined,
  environmentId: string
): EnvironmentListResponse {
  return {
    items: (current?.items ?? []).filter((item) => item.id !== environmentId),
  };
}

function mergeProjectReferenceList(
  current: ProjectEnvironmentReferenceListResponse | undefined,
  reference: ProjectEnvironmentReference
): ProjectEnvironmentReferenceListResponse {
  const items = (current?.items ?? [])
    .filter((item) => item.environment_id !== reference.environment_id)
    .map((item) => (reference.is_default ? { ...item, is_default: false } : item));
  return { items: [...items, reference] };
}

function removeProjectReferenceFromList(
  current: ProjectEnvironmentReferenceListResponse | undefined,
  environmentId: string
): ProjectEnvironmentReferenceListResponse {
  return {
    items: (current?.items ?? []).filter((item) => item.environment_id !== environmentId),
  };
}

interface EnvironmentEditorProps {
  mode: EnvironmentEditorMode;
  environment: EnvironmentRecord | null;
  activeEnvironment: EnvironmentRecord | null;
  isSaving: boolean;
  onSubmit: (values: EnvironmentFormValues) => Promise<void>;
  onCancel: () => void;
}

function EnvironmentEditor({
  mode,
  environment,
  activeEnvironment,
  isSaving,
  onSubmit,
  onCancel,
}: EnvironmentEditorProps) {
  const t = useT();
  const [values, setValues] = useState<EnvironmentFormValues>(() =>
    environment ? valuesFromEnvironment(environment) : emptyFormValues()
  );
  const [formError, setFormError] = useState<string | null>(null);

  const title =
    mode === 'create'
      ? t('components.environmentEditor.createTitle')
      : t('components.environmentEditor.editTitle');
  const submitLabel =
    mode === 'create' ? t('components.environmentEditor.create') : t('components.environmentEditor.save');
  const placeholders = {
    alias: t('components.environmentEditor.placeholders.alias'),
    displayName: t('components.environmentEditor.placeholders.displayName'),
    description: t('components.environmentEditor.placeholders.description'),
    host: t('components.environmentEditor.placeholders.host'),
    port: t('components.environmentEditor.placeholders.port'),
    user: t('components.environmentEditor.placeholders.user'),
    identityFile: t('components.environmentEditor.placeholders.identityFile'),
    proxyJump: t('components.environmentEditor.placeholders.proxyJump'),
    proxyCommand: t('components.environmentEditor.placeholders.proxyCommand'),
    tags: t('components.environmentEditor.placeholders.tags'),
    defaultWorkdir: t('components.environmentEditor.placeholders.defaultWorkdir'),
    preferredPython: t('components.environmentEditor.placeholders.preferredPython'),
    preferredEnvManager: t('components.environmentEditor.placeholders.preferredEnvManager'),
    preferredRuntimeNotes: t('components.environmentEditor.placeholders.preferredRuntimeNotes'),
    sshOptionsJson: t('components.environmentEditor.placeholders.sshOptionsJson'),
    taskHarnessProfile: 'You are running inside the task harness for this environment.',
  };
  const authKindLabels = {
    ssh_key: t('components.environmentEditor.authKindOptions.ssh_key'),
    password: t('components.environmentEditor.authKindOptions.password'),
    agent: t('components.environmentEditor.authKindOptions.agent'),
  };

  const updateField = (field: keyof EnvironmentFormValues, nextValue: string) => {
    setValues((current) => ({ ...current, [field]: nextValue }));
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setFormError(null);
      await onSubmit(values);
    } catch (error) {
      setFormError(error instanceof Error ? error.message : t('components.environmentEditor.saveError'));
    }
  };

  return (
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-2">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('components.environmentEditor.eyebrow')}
        </p>
        <h2
          className="text-xl font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {title}
        </h2>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {t('components.environmentEditor.description')}
        </p>
      </div>

      {activeEnvironment ? (
        <div
          data-testid="active-environment-banner"
          className="rounded-lg bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-secondary)]"
        >
          {t('components.environmentEditor.activeLabel')}{' '}
          <span className="font-medium text-[var(--text)]">{activeEnvironment.alias}</span>
          <span className="ml-2 text-[var(--text-tertiary)]">({activeEnvironment.display_name})</span>
        </div>
      ) : (
        <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-4 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          {t('components.environmentEditor.noActive')}
        </div>
      )}

      <form className="space-y-5" onSubmit={handleSubmit}>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.alias')}
            </span>
            <input
              required
              value={values.alias}
              onChange={(event) => updateField('alias', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.alias}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.displayName')}
            </span>
            <input
              required
              value={values.display_name}
              onChange={(event) => updateField('display_name', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.displayName}
            />
          </label>
        </div>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('components.environmentEditor.descriptionField')}
          </span>
          <textarea
            value={values.description}
            onChange={(event) => updateField('description', event.target.value)}
            rows={3}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            placeholder={placeholders.description}
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.host')}
            </span>
            <input
              required
              value={values.host}
              onChange={(event) => updateField('host', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.host}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.port')}
            </span>
            <input
              required
              type="number"
              min={1}
              max={65535}
              value={values.port}
              onChange={(event) => updateField('port', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.port}
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.user')}
            </span>
            <input
              value={values.user}
              onChange={(event) => updateField('user', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.user}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.authKindLabel')}
            </span>
            <select
              value={values.auth_kind}
              onChange={(event) => updateField('auth_kind', event.target.value as EnvironmentAuthKind)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            >
              <option value="ssh_key">{authKindLabels.ssh_key}</option>
              <option value="password">{authKindLabels.password}</option>
              <option value="agent">{authKindLabels.agent}</option>
            </select>
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.identityFile')}
            </span>
            <input
              value={values.identity_file}
              onChange={(event) => updateField('identity_file', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.identityFile}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.proxyJump')}
            </span>
            <input
              value={values.proxy_jump}
              onChange={(event) => updateField('proxy_jump', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.proxyJump}
            />
          </label>
        </div>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('components.environmentEditor.proxyCommand')}
          </span>
          <input
            value={values.proxy_command}
            onChange={(event) => updateField('proxy_command', event.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            placeholder={placeholders.proxyCommand}
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.tags')}
            </span>
            <input
              value={values.tags}
              onChange={(event) => updateField('tags', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.tags}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.defaultWorkdir')}
            </span>
            <input
              value={values.default_workdir}
              onChange={(event) => updateField('default_workdir', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.defaultWorkdir}
            />
          </label>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.preferredPython')}
            </span>
            <input
              value={values.preferred_python}
              onChange={(event) => updateField('preferred_python', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.preferredPython}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('components.environmentEditor.preferredEnvManager')}
            </span>
            <input
              value={values.preferred_env_manager}
              onChange={(event) => updateField('preferred_env_manager', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={placeholders.preferredEnvManager}
            />
          </label>
        </div>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('components.environmentEditor.preferredRuntimeNotes')}
          </span>
          <textarea
            value={values.preferred_runtime_notes}
            onChange={(event) => updateField('preferred_runtime_notes', event.target.value)}
            rows={3}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            placeholder={placeholders.preferredRuntimeNotes}
          />
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            Task harness profile
          </span>
          <textarea
            value={values.task_harness_profile}
            onChange={(event) => updateField('task_harness_profile', event.target.value)}
            rows={5}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            placeholder={placeholders.taskHarnessProfile}
          />
        </label>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('components.environmentEditor.sshOptionsJson')}
          </span>
          <textarea
            value={values.ssh_options}
            onChange={(event) => updateField('ssh_options', event.target.value)}
            rows={4}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 font-mono text-sm tracking-[-0.12px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            placeholder={placeholders.sshOptionsJson}
          />
        </label>

        {formError ? (
          <p className="rounded-lg border border-[#ff3b30]/20 bg-[#ffebee] px-3 py-2 text-sm text-[#c62828]">
            {formError}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="submit"
            disabled={isSaving}
            className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {isSaving ? t('components.environmentEditor.saving') : submitLabel}
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
          >
            {mode === 'create'
              ? t('components.environmentEditor.reset')
              : t('components.environmentEditor.cancelEdit')}
          </button>
        </div>
      </form>
    </section>
  );
}

interface ProjectRefFormValues {
  override_workdir: string;
  override_env_name: string;
  override_env_manager: string;
  override_runtime_notes: string;
}

function valuesFromProjectReference(
  reference: ProjectEnvironmentReference | null
): ProjectRefFormValues {
  return {
    override_workdir: reference?.override_workdir ?? '',
    override_env_name: reference?.override_env_name ?? '',
    override_env_manager: reference?.override_env_manager ?? '',
    override_runtime_notes: reference?.override_runtime_notes ?? '',
  };
}

interface ProjectReferenceEditorProps {
  selectedEnvironment: EnvironmentRecord | null;
  projectReference: ProjectEnvironmentReference | null;
  isSaving: boolean;
  isRemoving: boolean;
  onSave: (values: ProjectRefFormValues) => Promise<void>;
  onSetDefault: () => Promise<void>;
  onClearDefault: () => Promise<void>;
  onRemove: () => Promise<void>;
}

function ProjectReferenceEditor({
  selectedEnvironment,
  projectReference,
  isSaving,
  isRemoving,
  onSave,
  onSetDefault,
  onClearDefault,
  onRemove,
}: ProjectReferenceEditorProps) {
  const t = useT();
  const [values, setValues] = useState<ProjectRefFormValues>(() =>
    valuesFromProjectReference(projectReference)
  );
  const [formError, setFormError] = useState<string | null>(null);

  const updateField = (field: keyof ProjectRefFormValues, nextValue: string) => {
    setValues((current) => ({ ...current, [field]: nextValue }));
  };

  if (selectedEnvironment === null) {
    return (
      <section className="space-y-4 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
        <div className="space-y-1">
          <h2
            className="text-xl font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
            style={{ fontFamily: 'var(--font-display)' }}
          >
            {t('pages.containers.projectReferenceTitle')}
          </h2>
          <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
            {t('pages.containers.projectReferenceDescription')}
          </p>
        </div>
        <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
          {t('pages.containers.projectReferenceNoSelection')}
        </p>
      </section>
    );
  }

  return (
    <section className="space-y-5 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
      <div className="space-y-1">
        <h2
          className="text-xl font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.containers.projectReferenceTitle')}
        </h2>
        <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
          {t('pages.containers.projectReferenceDescription')}
        </p>
        <p className="text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
          <span className="font-medium text-[var(--text)]">{selectedEnvironment.alias}</span>
          <span className="ml-2 text-[var(--text-tertiary)]">({selectedEnvironment.display_name})</span>
        </p>
      </div>

      <div className="flex flex-wrap gap-2">
        {projectReference ? (
          <span className="rounded-full bg-[var(--apple-blue)]/10 px-3 py-1 text-xs font-semibold text-[var(--apple-blue)]">
            {t('pages.containers.projectReferencedBadge')}
          </span>
        ) : (
          <span className="rounded-full bg-[var(--bg-secondary)] px-3 py-1 text-xs font-semibold text-[var(--text-tertiary)]">
            {t('pages.containers.projectUnreferencedBadge')}
          </span>
        )}
        {projectReference?.is_default ? (
          <span className="rounded-full bg-[var(--apple-blue)]/10 px-3 py-1 text-xs font-semibold text-[var(--apple-blue)]">
            {t('pages.containers.projectDefaultBadge')}
          </span>
        ) : null}
      </div>

      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={async () => {
            try {
              setFormError(null);
              await onSetDefault();
            } catch (error) {
              setFormError(
                error instanceof Error ? error.message : t('pages.containers.projectReferenceSaveError')
              );
            }
          }}
          disabled={isSaving || isRemoving || projectReference?.is_default === true}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {projectReference?.is_default
            ? t('pages.containers.setProjectDefaultDisabled')
            : t('pages.containers.setProjectDefault')}
        </button>
        {projectReference?.is_default ? (
          <button
            type="button"
            onClick={async () => {
              try {
                setFormError(null);
                await onClearDefault();
              } catch (error) {
                setFormError(
                  error instanceof Error ? error.message : t('pages.containers.projectReferenceSaveError')
                );
              }
            }}
            disabled={isSaving || isRemoving}
            className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t('pages.containers.clearProjectDefault')}
          </button>
        ) : null}
        {projectReference ? (
          <button
            type="button"
            onClick={async () => {
              try {
                setFormError(null);
                await onRemove();
              } catch (error) {
                setFormError(
                  error instanceof Error ? error.message : t('pages.containers.projectReferenceSaveError')
                );
              }
            }}
            disabled={isSaving || isRemoving}
            className="rounded-lg border border-[#ff3b30]/20 bg-[#ffebee] px-4 py-2 text-sm font-medium text-[#c62828] transition hover:bg-[#ffcdd2] disabled:cursor-not-allowed disabled:opacity-40"
          >
            {t('pages.containers.removeProjectReference')}
          </button>
        ) : null}
      </div>

      <form
        className="space-y-4"
        onSubmit={async (event) => {
          event.preventDefault();
          try {
            setFormError(null);
            await onSave(values);
          } catch (error) {
            setFormError(
              error instanceof Error ? error.message : t('pages.containers.projectReferenceSaveError')
            );
          }
        }}
      >
        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.containers.projectOverrideWorkdir')}
          </span>
          <input
            value={values.override_workdir}
            onChange={(event) => updateField('override_workdir', event.target.value)}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            placeholder={t('pages.containers.projectOverrideWorkdirPlaceholder')}
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('pages.containers.projectOverrideEnvName')}
            </span>
            <input
              value={values.override_env_name}
              onChange={(event) => updateField('override_env_name', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={t('pages.containers.projectOverrideEnvNamePlaceholder')}
            />
          </label>

          <label className="space-y-2">
            <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
              {t('pages.containers.projectOverrideEnvManager')}
            </span>
            <input
              value={values.override_env_manager}
              onChange={(event) => updateField('override_env_manager', event.target.value)}
              className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
              placeholder={t('pages.containers.projectOverrideEnvManagerPlaceholder')}
            />
          </label>
        </div>

        <label className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.containers.projectOverrideRuntimeNotes')}
          </span>
          <textarea
            value={values.override_runtime_notes}
            onChange={(event) => updateField('override_runtime_notes', event.target.value)}
            rows={4}
            className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-2.5 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
            placeholder={t('pages.containers.projectOverrideRuntimeNotesPlaceholder')}
          />
        </label>

        {formError ? (
          <p className="rounded-lg border border-[#ff3b30]/20 bg-[#ffebee] px-3 py-2 text-sm text-[#c62828]">
            {formError}
          </p>
        ) : null}

        <button
          type="submit"
          disabled={isSaving || isRemoving}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isSaving
            ? t('pages.containers.projectReferenceSaving')
            : projectReference
              ? t('pages.containers.updateProjectReference')
              : t('pages.containers.attachProjectReference')}
        </button>
      </form>
    </section>
  );
}

function ContainersPage() {
  const t = useT();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const environmentSelection = useEnvironmentSelection();
  const [editorMode, setEditorMode] = useState<EnvironmentEditorMode>('create');
  const [editorEnvironmentId, setEditorEnvironmentId] = useState<string | null>(null);
  const [editorFormKey, setEditorFormKey] = useState(0);

  const environments = environmentSelection.environments ?? EMPTY_ENVIRONMENTS;
  const projectReferences = environmentSelection.projectReferences ?? EMPTY_PROJECT_REFS;
  const selectedEnvironment = environmentSelection.selectedEnvironment;
  const editorEnvironment = useMemo(
    () => environments.find((environment) => environment.id === editorEnvironmentId) ?? null,
    [environments, editorEnvironmentId]
  );
  const projectReferenceByEnvironmentId = useMemo(
    () =>
      Object.fromEntries(
        projectReferences.map((reference) => [reference.environment_id, reference] as const)
      ),
    [projectReferences]
  );
  const selectedProjectReference =
    selectedEnvironment !== null
      ? projectReferenceByEnvironmentId[selectedEnvironment.id] ?? null
      : null;

  const syncEnvironmentList = (next: EnvironmentListResponse) => {
    queryClient.setQueryData(environmentsQueryKey, next);
  };
  const syncProjectReferenceList = (next: ProjectEnvironmentReferenceListResponse) => {
    queryClient.setQueryData(projectEnvironmentRefsQueryKey, next);
  };

  const saveMutation = useMutation({
    mutationFn: async (values: EnvironmentFormValues) => {
      const requestBase = {
        alias: values.alias.trim(),
        display_name: values.display_name.trim(),
        description: values.description.trim() || null,
        tags: parseTags(values.tags),
        host: values.host.trim(),
        port: Number.parseInt(values.port, 10),
        user: values.user.trim() || 'root',
        auth_kind: values.auth_kind,
        identity_file: values.identity_file.trim() || null,
        proxy_jump: values.proxy_jump.trim() || null,
        proxy_command: values.proxy_command.trim() || null,
        ssh_options: parseJsonObject(
          values.ssh_options,
          t('components.environmentEditor.sshOptionsObjectError'),
          t('components.environmentEditor.sshOptionsValuesError')
        ),
        default_workdir: values.default_workdir.trim() || null,
        preferred_python: values.preferred_python.trim() || null,
        preferred_env_manager: values.preferred_env_manager.trim() || null,
        preferred_runtime_notes: values.preferred_runtime_notes.trim() || null,
        task_harness_profile: values.task_harness_profile.trim() || null,
      } satisfies EnvironmentCreateRequest;

      if (!Number.isInteger(requestBase.port) || requestBase.port < 1 || requestBase.port > 65535) {
        throw new Error(t('components.environmentEditor.portRangeError'));
      }

      if (editorMode === 'create') {
        return createEnvironment(requestBase);
      }

      if (editorEnvironmentId === null) {
        throw new Error(t('components.environmentEditor.noEnvironmentSelectedForEditing'));
      }

      const request: EnvironmentUpdateRequest = requestBase;
      return updateEnvironment(editorEnvironmentId, request);
    },
    onSuccess: (environment) => {
      const current = queryClient.getQueryData<EnvironmentListResponse>(environmentsQueryKey);
      syncEnvironmentList(mergeEnvironmentList(current, environment));
      environmentSelection.onSelectEnvironment(environment.id);
      setEditorEnvironmentId(environment.id);
      setEditorMode('edit');
    },
  });

  const deleteMutation = useMutation({
    mutationFn: async (environmentId: string) => deleteEnvironment(environmentId),
    onSuccess: (_, environmentId) => {
      const current = queryClient.getQueryData<EnvironmentListResponse>(environmentsQueryKey);
      syncEnvironmentList(removeEnvironmentFromList(current, environmentId));
      if (editorEnvironmentId === environmentId) {
        setEditorEnvironmentId(null);
        setEditorMode('create');
      }
    },
  });

  const detectMutation = useMutation({
    mutationFn: async (environmentId: string) => detectEnvironment(environmentId),
    onSuccess: (environment) => {
      const current = queryClient.getQueryData<EnvironmentListResponse>(environmentsQueryKey);
      syncEnvironmentList(mergeEnvironmentList(current, environment));
    },
  });

  const saveProjectReferenceMutation = useMutation({
    mutationFn: async (payload: ProjectEnvironmentReferenceUpdateRequest) => {
      if (selectedEnvironment === null) {
        throw new Error(t('pages.containers.projectReferenceNoSelection'));
      }

      if (selectedProjectReference) {
        return updateProjectEnvironmentReference(
          selectedEnvironment.id,
          payload,
          defaultProjectId
        );
      }

      return createProjectEnvironmentReference(
        {
          environment_id: selectedEnvironment.id,
          is_default: payload.is_default ?? false,
          override_workdir: payload.override_workdir ?? null,
          override_env_name: payload.override_env_name ?? null,
          override_env_manager: payload.override_env_manager ?? null,
          override_runtime_notes: payload.override_runtime_notes ?? null,
        },
        defaultProjectId
      );
    },
    onSuccess: (reference) => {
      const current = queryClient.getQueryData<ProjectEnvironmentReferenceListResponse>(
        projectEnvironmentRefsQueryKey
      );
      syncProjectReferenceList(mergeProjectReferenceList(current, reference));
    },
  });

  const removeProjectReferenceMutation = useMutation({
    mutationFn: async () => {
      if (selectedEnvironment === null || selectedProjectReference === null) {
        throw new Error(t('pages.containers.projectReferenceNoSelection'));
      }
      return deleteProjectEnvironmentReference(selectedEnvironment.id, defaultProjectId);
    },
    onSuccess: () => {
      if (selectedEnvironment === null) {
        return;
      }
      const current = queryClient.getQueryData<ProjectEnvironmentReferenceListResponse>(
        projectEnvironmentRefsQueryKey
      );
      syncProjectReferenceList(removeProjectReferenceFromList(current, selectedEnvironment.id));
    },
  });

  const requestError = environmentSelection.loadError;
  const mutationError =
    (deleteMutation.error instanceof Error ? deleteMutation.error.message : null) ??
    (detectMutation.error instanceof Error ? detectMutation.error.message : null) ??
    (saveProjectReferenceMutation.error instanceof Error
      ? saveProjectReferenceMutation.error.message
      : null) ??
    (removeProjectReferenceMutation.error instanceof Error
      ? removeProjectReferenceMutation.error.message
      : null);
  const activeEnvironmentSummary = selectedEnvironment
    ? `${selectedEnvironment.alias} · ${selectedEnvironment.display_name}`
    : t('pages.containers.activeSelectionFallback');
  const authKindLabels = {
    ssh_key: t('pages.containers.authKind.ssh_key'),
    password: t('pages.containers.authKind.password'),
    agent: t('pages.containers.authKind.agent'),
  };
  const detectionStatusLabels = {
    success: t('pages.containers.detectionStatus.success'),
    partial: t('pages.containers.detectionStatus.partial'),
    failed: t('pages.containers.detectionStatus.failed'),
  };

  const handleCreate = () => {
    setEditorFormKey((value) => value + 1);
    setEditorMode('create');
    setEditorEnvironmentId(null);
  };

  return (
    <div className="space-y-8">
      <section className="space-y-3">
        <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
          {t('pages.containers.eyebrow')}
        </p>
        <h1
          className="text-[28px] font-normal leading-tight tracking-[0.196px] text-[var(--text)]"
          style={{ fontFamily: 'var(--font-display)' }}
        >
          {t('pages.containers.title')}
        </h1>
        <p className="max-w-3xl text-base leading-relaxed tracking-[-0.374px] text-[var(--text-secondary)]">
          {t('pages.containers.description')}
        </p>
      </section>

      <section className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-[var(--surface)] p-5 shadow-sm">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
            {t('pages.containers.currentSelection')}
          </p>
          <p className="mt-1 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
            {activeEnvironmentSummary}
          </p>
        </div>
        <button
          type="button"
          onClick={handleCreate}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)]"
        >
          {t('pages.containers.addEnvironment')}
        </button>
      </section>

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
        <section className="space-y-4 rounded-xl bg-[var(--surface)] p-6 shadow-sm">
          <div className="space-y-1">
            <h2
              className="text-xl font-semibold leading-tight tracking-[0.231px] text-[var(--text)]"
              style={{ fontFamily: 'var(--font-display)' }}
            >
              {t('pages.containers.listTitle')}
            </h2>
            <p className="text-sm leading-relaxed tracking-[-0.224px] text-[var(--text-secondary)]">
              {t('pages.containers.listDescription')}
            </p>
          </div>

          {environmentSelection.isLoading ? (
            <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.containers.loading')}
            </p>
          ) : null}

          {requestError ? <p className="text-sm text-[#ff3b30]">{requestError}</p> : null}
          {mutationError ? <p className="text-sm text-[#ff3b30]">{mutationError}</p> : null}

          {!environmentSelection.isLoading && environments.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-6 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.containers.empty')}
            </div>
          ) : null}

          {environments.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.containers.alias')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.containers.host')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.containers.auth')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.containers.detection')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.containers.actions')}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {environments.map((environment) => {
                    const detection = environment.latest_detection;
                    const projectReference =
                      projectReferenceByEnvironmentId[environment.id] ?? null;
                    const isActive = environment.id === environmentSelection.selectedEnvironmentId;
                    const isEditing = environment.id === editorEnvironmentId;
                    return (
                      <tr
                        key={environment.id}
                        className={`border-b border-[var(--border)] transition ${
                          isActive ? 'bg-[var(--apple-blue)]/[0.04]' : ''
                        }`}
                      >
                        <td className="px-4 py-4">
                          <div className="space-y-1">
                            <p className="font-medium text-[var(--text)]">
                              {environment.display_name}
                              {environment.is_seed ? (
                                <span className="ml-2 rounded-full bg-[var(--apple-blue)]/10 px-2 py-0.5 text-xs font-semibold text-[var(--apple-blue)]">
                                  {t('common.default')}
                                </span>
                              ) : null}
                              {projectReference ? (
                                <span className="ml-2 rounded-full bg-[var(--bg-secondary)] px-2 py-0.5 text-xs font-semibold text-[var(--text-tertiary)]">
                                  {t('pages.containers.projectReferencedBadge')}
                                </span>
                              ) : null}
                              {projectReference?.is_default ? (
                                <span className="ml-2 rounded-full bg-[var(--apple-blue)]/10 px-2 py-0.5 text-xs font-semibold text-[var(--apple-blue)]">
                                  {t('pages.containers.projectDefaultBadge')}
                                </span>
                              ) : null}
                              {isActive ? (
                                <span className="ml-2 rounded-full bg-[var(--apple-blue)]/10 px-2 py-0.5 text-xs font-semibold text-[var(--apple-blue)]">
                                  {t('pages.containers.activeBadge')}
                                </span>
                              ) : null}
                            </p>
                            <p className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                              <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5">
                                {environment.alias}
                              </code>
                              {isEditing ? (
                                <span className="ml-2 text-[var(--apple-blue)]">
                                  {t('pages.containers.editingBadge')}
                                </span>
                              ) : null}
                            </p>
                            <p className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                              {environment.default_workdir ?? t('pages.containers.defaultWorkdir')}
                            </p>
                          </div>
                        </td>
                        <td className="px-4 py-4 text-[var(--text-secondary)]">
                          <div>{environment.host}</div>
                          <div className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                            {environment.user}@{environment.port}
                          </div>
                        </td>
                        <td className="px-4 py-4 text-[var(--text-secondary)]">
                          <div>{authKindLabels[environment.auth_kind]}</div>
                          <div className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                            {environment.tags.length > 0
                              ? environment.tags.join(', ')
                              : t('common.noTags')}
                          </div>
                        </td>
                        <td className="px-4 py-4">
                          {detection ? (
                            <div className="space-y-1">
                              <div className="text-sm font-medium text-[var(--text)]">
                                {detectionStatusLabels[detection.status] ?? detection.status} ·{' '}
                                {detection.summary}
                              </div>
                              <div className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                                {t('pages.containers.detectedAt')}{' '}
                                {formatTimestamp(detection.detected_at, locale, t('common.never'))}
                              </div>
                            </div>
                          ) : (
                            <span className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                              {t('pages.containers.notDetected')}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-4">
                          <div className="flex flex-wrap gap-2">
                            <button
                              type="button"
                              onClick={() => environmentSelection.onSelectEnvironment(environment.id)}
                              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
                            >
                              {t('common.use')}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setEditorMode('edit');
                                setEditorEnvironmentId(environment.id);
                              }}
                              className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-3 py-1.5 text-xs font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
                            >
                              {t('common.edit')}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                detectMutation.mutate(environment.id);
                              }}
                              disabled={detectMutation.isPending}
                              className="rounded-lg border border-[var(--apple-blue)]/20 bg-[var(--apple-blue)]/10 px-3 py-1.5 text-xs font-medium text-[var(--apple-blue)] transition hover:bg-[var(--apple-blue)]/15 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {t('common.detect')}
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                if (
                                  window.confirm(
                                    t('pages.containers.confirmDelete', { alias: environment.alias })
                                  )
                                ) {
                                  deleteMutation.mutate(environment.id);
                                }
                              }}
                              disabled={deleteMutation.isPending || environment.is_seed}
                              title={
                                environment.is_seed
                                  ? t('pages.containers.defaultEnvironmentLocked')
                                  : undefined
                              }
                              className="rounded-lg border border-[#ff3b30]/20 bg-[#ffebee] px-3 py-1.5 text-xs font-medium text-[#c62828] transition hover:bg-[#ffcdd2] disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {t('common.delete')}
                            </button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </section>

        <div className="space-y-6">
          <EnvironmentEditor
            key={`${editorMode}-${editorEnvironmentId ?? 'new'}-${editorFormKey}`}
            mode={editorMode}
            environment={editorEnvironment}
            activeEnvironment={selectedEnvironment}
            isSaving={saveMutation.isPending}
            onSubmit={async (values) => {
              await saveMutation.mutateAsync(values);
            }}
            onCancel={() => {
              if (editorMode === 'edit') {
                setEditorFormKey((value) => value + 1);
                setEditorMode('create');
                setEditorEnvironmentId(null);
                return;
              }
              setEditorFormKey((value) => value + 1);
              setEditorEnvironmentId(null);
            }}
          />

          <ProjectReferenceEditor
            key={`${selectedEnvironment?.id ?? 'none'}-${selectedProjectReference?.updated_at ?? 'new'}`}
            selectedEnvironment={selectedEnvironment}
            projectReference={selectedProjectReference}
            isSaving={saveProjectReferenceMutation.isPending}
            isRemoving={removeProjectReferenceMutation.isPending}
            onSave={async (values) => {
              await saveProjectReferenceMutation.mutateAsync({
                override_workdir: values.override_workdir.trim() || null,
                override_env_name: values.override_env_name.trim() || null,
                override_env_manager: values.override_env_manager.trim() || null,
                override_runtime_notes: values.override_runtime_notes.trim() || null,
              });
            }}
            onSetDefault={async () => {
              await saveProjectReferenceMutation.mutateAsync({ is_default: true });
            }}
            onClearDefault={async () => {
              await saveProjectReferenceMutation.mutateAsync({ is_default: false });
            }}
            onRemove={async () => {
              await removeProjectReferenceMutation.mutateAsync();
            }}
          />
        </div>
      </div>
    </div>
  );
}

export default ContainersPage;
