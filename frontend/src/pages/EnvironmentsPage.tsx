import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState, type FormEvent } from 'react';
import {
  Alert,
  Badge,
  Button,
  FormField,
  Input,
  Modal,
  SectionCard,
  Select,
  Textarea,
} from '../components/ui';
import { PageShell, SectionStack } from '../components/layout';
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
  EnvironmentListResponse,
  EnvironmentRecord,
  ProjectEnvironmentReferenceListResponse,
  ProjectEnvironmentReferenceUpdateRequest,
} from '../types';
import { useLocale, useT } from '../i18n';
import { useEnvironmentSelection } from '../components';
import { useToast } from '../components/common';
import { EnvironmentDetectionModal } from '../components/environment';
import {
  buildEnvironmentRequest,
  buildProjectReferenceCreateRequest,
  defaultProjectId,
  EMPTY_ENVIRONMENTS,
  EMPTY_PROJECT_REFS,
  emptyFormValues,
  environmentsQueryKey,
  formatTimestamp,
  mergeEnvironmentList,
  mergeProjectReferenceList,
  projectEnvironmentRefsQueryKey,
  removeEnvironmentFromList,
  removeProjectReferenceFromList,
  toEnvironmentUpdateRequest,
  valuesFromEnvironment,
} from './environments/helpers';
import type {
  EnvironmentEditorMode,
  EnvironmentFormValues,
} from './environments/helpers';

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
    <>
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
          <FormField label={t('components.environmentEditor.alias')}>
            <Input
              required
              value={values.alias}
              onChange={(event) => updateField('alias', event.target.value)}
              placeholder={placeholders.alias}
            />
          </FormField>

          <FormField label={t('components.environmentEditor.displayName')}>
            <Input
              required
              value={values.display_name}
              onChange={(event) => updateField('display_name', event.target.value)}
              placeholder={placeholders.displayName}
            />
          </FormField>
        </div>

        <FormField label={t('components.environmentEditor.descriptionField')}>
          <Textarea
            value={values.description}
            onChange={(event) => updateField('description', event.target.value)}
            rows={3}
            placeholder={placeholders.description}
          />
        </FormField>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t('components.environmentEditor.host')}>
            <Input
              required
              value={values.host}
              onChange={(event) => updateField('host', event.target.value)}
              placeholder={placeholders.host}
            />
          </FormField>

          <FormField label={t('components.environmentEditor.port')}>
            <Input
              required
              type="number"
              min={1}
              max={65535}
              value={values.port}
              onChange={(event) => updateField('port', event.target.value)}
              placeholder={placeholders.port}
            />
          </FormField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t('components.environmentEditor.user')}>
            <Input
              value={values.user}
              onChange={(event) => updateField('user', event.target.value)}
              placeholder={placeholders.user}
            />
          </FormField>

          <FormField label={t('components.environmentEditor.authKindLabel')}>
            <Select
              value={values.auth_kind}
              onChange={(event) => updateField('auth_kind', event.target.value as EnvironmentAuthKind)}
            >
              <option value="ssh_key">{authKindLabels.ssh_key}</option>
              <option value="password">{authKindLabels.password}</option>
              <option value="agent">{authKindLabels.agent}</option>
            </Select>
          </FormField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t('components.environmentEditor.identityFile')}>
            <Input
              value={values.identity_file}
              onChange={(event) => updateField('identity_file', event.target.value)}
              placeholder={placeholders.identityFile}
            />
          </FormField>

          <FormField label={t('components.environmentEditor.proxyJump')}>
            <Input
              value={values.proxy_jump}
              onChange={(event) => updateField('proxy_jump', event.target.value)}
              placeholder={placeholders.proxyJump}
            />
          </FormField>
        </div>

        <FormField label={t('components.environmentEditor.proxyCommand')}>
          <Input
            value={values.proxy_command}
            onChange={(event) => updateField('proxy_command', event.target.value)}
            placeholder={placeholders.proxyCommand}
          />
        </FormField>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t('components.environmentEditor.tags')}>
            <Input
              value={values.tags}
              onChange={(event) => updateField('tags', event.target.value)}
              placeholder={placeholders.tags}
            />
          </FormField>

          <FormField label={t('components.environmentEditor.defaultWorkdir')}>
            <Input
              value={values.default_workdir}
              onChange={(event) => updateField('default_workdir', event.target.value)}
              placeholder={placeholders.defaultWorkdir}
            />
          </FormField>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t('components.environmentEditor.preferredPython')}>
            <Input
              value={values.preferred_python}
              onChange={(event) => updateField('preferred_python', event.target.value)}
              placeholder={placeholders.preferredPython}
            />
          </FormField>

          <FormField label={t('components.environmentEditor.preferredEnvManager')}>
            <Input
              value={values.preferred_env_manager}
              onChange={(event) => updateField('preferred_env_manager', event.target.value)}
              placeholder={placeholders.preferredEnvManager}
            />
          </FormField>
        </div>

        <FormField label={t('components.environmentEditor.preferredRuntimeNotes')}>
          <Textarea
            value={values.preferred_runtime_notes}
            onChange={(event) => updateField('preferred_runtime_notes', event.target.value)}
            rows={3}
            placeholder={placeholders.preferredRuntimeNotes}
          />
        </FormField>

        <FormField label="Task harness profile">
          <Textarea
            value={values.task_harness_profile}
            onChange={(event) => updateField('task_harness_profile', event.target.value)}
            rows={5}
            placeholder={placeholders.taskHarnessProfile}
          />
        </FormField>

        <FormField label={t('components.environmentEditor.sshOptionsJson')}>
          <Textarea
            value={values.ssh_options}
            onChange={(event) => updateField('ssh_options', event.target.value)}
            rows={4}
            className="font-mono text-sm tracking-[-0.12px]"
            placeholder={placeholders.sshOptionsJson}
          />
        </FormField>

        {formError ? (
          <Alert variant="error">{formError}</Alert>
        ) : null}

        <div className="flex flex-wrap items-center gap-3">
          <Button type="submit" disabled={isSaving}>
            {isSaving ? t('components.environmentEditor.saving') : submitLabel}
          </Button>
          <Button type="button" variant="secondary" onClick={onCancel}>
            {mode === 'create'
              ? t('components.environmentEditor.reset')
              : t('components.environmentEditor.cancelEdit')}
          </Button>
        </div>
      </form>
    </>
  );
}

function EnvironmentsPage() {
  const t = useT();
  const locale = useLocale();
  const queryClient = useQueryClient();
  const { showToast } = useToast();
  const environmentSelection = useEnvironmentSelection();
  const [editorMode, setEditorMode] = useState<EnvironmentEditorMode>('create');
  const [editorEnvironmentId, setEditorEnvironmentId] = useState<string | null>(null);
  const [editorFormKey, setEditorFormKey] = useState(0);
  const [isEditorModalOpen, setIsEditorModalOpen] = useState(false);
  const [selectedDetectionEnvironmentId, setSelectedDetectionEnvironmentId] = useState<string | null>(null);

  const environments = environmentSelection.environments ?? EMPTY_ENVIRONMENTS;
  const projectReferences = environmentSelection.projectReferences ?? EMPTY_PROJECT_REFS;
  const selectedEnvironment = environmentSelection.selectedEnvironment;
  const editorEnvironment = useMemo(
    () => environments.find((environment) => environment.id === editorEnvironmentId) ?? null,
    [environments, editorEnvironmentId]
  );
  const detectionEnv = useMemo(
    () =>
      selectedDetectionEnvironmentId !== null
        ? (environments.find((e) => e.id === selectedDetectionEnvironmentId) ?? null)
        : null,
    [environments, selectedDetectionEnvironmentId]
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
      const request = buildEnvironmentRequest(values, {
        portRangeError: t('components.environmentEditor.portRangeError'),
        sshOptionsObjectError: t('components.environmentEditor.sshOptionsObjectError'),
        sshOptionsValuesError: t('components.environmentEditor.sshOptionsValuesError'),
      });

      if (editorMode === 'create') {
        return createEnvironment(request);
      }

      if (editorEnvironmentId === null) {
        throw new Error(t('components.environmentEditor.noEnvironmentSelectedForEditing'));
      }

      return updateEnvironment(editorEnvironmentId, toEnvironmentUpdateRequest(request));
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
    onMutate: (environmentId) => {
      const environment = environments.find((item) => item.id === environmentId) ?? null;
      console.info('environment detect requested', {
        environmentId,
        alias: environment?.alias ?? null,
      });
    },
    onSuccess: (environment) => {
      const current = queryClient.getQueryData<EnvironmentListResponse>(environmentsQueryKey);
      syncEnvironmentList(mergeEnvironmentList(current, environment));
      const detection = environment.latest_detection;
      console.info('environment detect succeeded', {
        environmentId: environment.id,
        alias: environment.alias,
        status: detection?.status ?? null,
        warnings: detection?.warnings ?? [],
        errors: detection?.errors ?? [],
        codeServerPath: detection?.codex?.path ?? null,
      });
      if (detection?.warnings.includes('used_personal_tmux_fallback')) {
        showToast(t('pages.environments.detectFallbackToast', { alias: environment.alias }), 'warning');
      } else if (detection?.status === 'failed') {
        showToast(detection.summary, 'error');
      }
    },
    onError: (error, environmentId) => {
      const environment = environments.find((item) => item.id === environmentId) ?? null;
      console.error('environment detect failed', {
        environmentId,
        alias: environment?.alias ?? null,
        error: error instanceof Error ? error.message : error,
      });
      showToast(error instanceof Error ? error.message : t('pages.environments.detectFailedToast'), 'error');
    },
  });

  const saveProjectReferenceMutation = useMutation({
    mutationFn: async (payload: ProjectEnvironmentReferenceUpdateRequest) => {
      if (selectedEnvironment === null) {
        throw new Error(t('pages.environments.projectReferenceNoSelection'));
      }

      if (selectedProjectReference) {
        return updateProjectEnvironmentReference(selectedEnvironment.id, payload, defaultProjectId);
      }

      return createProjectEnvironmentReference(
        buildProjectReferenceCreateRequest(selectedEnvironment.id, payload),
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
        throw new Error(t('pages.environments.projectReferenceNoSelection'));
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
    : t('pages.environments.activeSelectionFallback');
  const authKindLabels = {
    ssh_key: t('pages.environments.authKind.ssh_key'),
    password: t('pages.environments.authKind.password'),
    agent: t('pages.environments.authKind.agent'),
  };
  const detectionStatusLabels = {
    success: t('pages.environments.detectionStatus.success'),
    partial: t('pages.environments.detectionStatus.partial'),
    failed: t('pages.environments.detectionStatus.failed'),
  };

  const handleCreate = () => {
    setEditorFormKey((value) => value + 1);
    setEditorMode('create');
    setEditorEnvironmentId(null);
    setIsEditorModalOpen(true);
  };

  return (
    <PageShell>
      <SectionStack>
        <SectionCard
          header={
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.12em] text-[var(--apple-blue)]">
                  {t('pages.environments.currentSelection')}
                </p>
                <p className="mt-1 text-sm text-[var(--text-secondary)]">
                  {activeEnvironmentSummary}
                </p>
              </div>
              <Button onClick={handleCreate}>
                {t('pages.environments.addEnvironment')}
              </Button>
            </div>
          }
        >
          {environmentSelection.isLoading ? (
            <p className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.environments.loading')}
            </p>
          ) : null}

          {requestError ? <Alert variant="error">{requestError}</Alert> : null}
          {mutationError ? <Alert variant="error">{mutationError}</Alert> : null}

          {!environmentSelection.isLoading && environments.length === 0 ? (
            <div className="rounded-lg border border-dashed border-[var(--border)] bg-[var(--bg-secondary)] p-6 text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
              {t('pages.environments.empty')}
            </div>
          ) : null}

          {environments.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="min-w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.environments.alias')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.environments.host')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.environments.auth')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.environments.detection')}
                    </th>
                    <th className="px-4 py-3 text-xs font-semibold uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
                      {t('pages.environments.actions')}
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
                                <Badge className="ml-2">{t('common.default')}</Badge>
                              ) : null}
                              {projectReference ? (
                                <Badge variant="secondary" className="ml-2">
                                  {t('pages.environments.projectReferencedBadge')}
                                </Badge>
                              ) : null}
                              {projectReference?.is_default ? (
                                <Badge className="ml-2">{t('pages.environments.projectDefaultBadge')}</Badge>
                              ) : null}
                              {isActive ? (
                                <Badge className="ml-2">{t('pages.environments.activeBadge')}</Badge>
                              ) : null}
                            </p>
                            <p className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                              <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5">
                                {environment.alias}
                              </code>
                              {isEditing ? (
                                <span className="ml-2 text-[var(--apple-blue)]">
                                  {t('pages.environments.editingBadge')}
                                </span>
                              ) : null}
                            </p>
                            <p className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                              {environment.default_workdir ?? t('pages.environments.defaultWorkdir')}
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
                              <button
                                type="button"
                                className="text-sm font-medium text-[var(--apple-blue)] hover:underline"
                                onClick={() => setSelectedDetectionEnvironmentId(environment.id)}
                              >
                                {detectionStatusLabels[detection.status] ?? detection.status}
                              </button>
                              <div className="text-xs tracking-[-0.12px] text-[var(--text-tertiary)]">
                                {t('pages.environments.detectedAt')}{' '}
                                {formatTimestamp(detection.detected_at, locale, t('common.never'))}
                              </div>
                            </div>
                          ) : (
                            <span className="text-sm tracking-[-0.224px] text-[var(--text-tertiary)]">
                              {t('pages.environments.notDetected')}
                            </span>
                          )}
                        </td>
                        <td className="px-4 py-4">
                          <div className="flex flex-wrap gap-2">
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => environmentSelection.onSelectEnvironment(environment.id)}
                            >
                              {t('common.use')}
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                setEditorMode('edit');
                                setEditorEnvironmentId(environment.id);
                                setIsEditorModalOpen(true);
                              }}
                            >
                              {t('common.edit')}
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                detectMutation.mutate(environment.id);
                              }}
                              disabled={detectMutation.isPending}
                              className="border-[var(--apple-blue)]/20 bg-[var(--apple-blue)]/10 text-[var(--apple-blue)] hover:bg-[var(--apple-blue)]/15 hover:text-[var(--apple-blue)]"
                            >
                              {t('common.detect')}
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={async () => {
                                try {
                                  await saveProjectReferenceMutation.mutateAsync({ is_default: true });
                                } catch { /* error handled by mutation state */ }
                              }}
                              disabled={
                                saveProjectReferenceMutation.isPending ||
                                removeProjectReferenceMutation.isPending ||
                                projectReferenceByEnvironmentId[environment.id]?.is_default === true
                              }
                            >
                              {projectReferenceByEnvironmentId[environment.id]?.is_default
                                ? t('pages.environments.setProjectDefaultDisabled')
                                : t('pages.environments.setProjectDefault')}
                            </Button>
                            <Button
                              variant="secondary"
                              size="sm"
                              onClick={() => {
                                if (
                                  window.confirm(
                                    t('pages.environments.confirmDelete', { alias: environment.alias })
                                  )
                                ) {
                                  deleteMutation.mutate(environment.id);
                                }
                              }}
                              disabled={deleteMutation.isPending || environment.is_seed}
                              title={
                                environment.is_seed
                                  ? t('pages.environments.defaultEnvironmentLocked')
                                  : undefined
                              }
                              className="border-[#ff3b30]/20 bg-[#ffebee] text-[#c62828] hover:bg-[#ffcdd2] hover:text-[#c62828]"
                            >
                              {t('common.delete')}
                            </Button>
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : null}
        </SectionCard>
      </SectionStack>

      <Modal
        isOpen={isEditorModalOpen}
        onClose={() => setIsEditorModalOpen(false)}
        title={editorMode === 'create' ? 'Add Environment' : 'Edit Environment'}
        size="lg"
      >
        <EnvironmentEditor
          key={`${editorMode}-${editorEnvironmentId ?? 'new'}-${editorFormKey}`}
          mode={editorMode}
          environment={editorEnvironment}
          activeEnvironment={selectedEnvironment}
          isSaving={saveMutation.isPending}
          onSubmit={async (values) => {
            await saveMutation.mutateAsync(values);
            setIsEditorModalOpen(false);
          }}
          onCancel={() => {
            setIsEditorModalOpen(false);
            setEditorFormKey((v) => v + 1);
            setEditorMode('create');
            setEditorEnvironmentId(null);
          }}
        />
      </Modal>

      {detectionEnv?.latest_detection ? (
        <EnvironmentDetectionModal
          detection={detectionEnv.latest_detection}
          environmentName={detectionEnv.display_name}
          isOpen={true}
          onClose={() => setSelectedDetectionEnvironmentId(null)}
        />
      ) : null}
    </PageShell>
  );
}

export default EnvironmentsPage;
