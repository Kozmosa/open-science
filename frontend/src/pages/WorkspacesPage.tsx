import { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Checkbox,
  ConfirmDialog,
  Dialog,
  EmptyState,
  FormField,
  Input,
  NativeSelect,
  PageHeader,
  PageShell,
  StatusBadge,
  Textarea,
} from '@design-system';
import { getEnvironments, unregisterWorkspace, updateWorkspace } from '@/shared/api';
import { IdempotencyKeyManager, semanticMutationValue, useIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import { useT } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import { useAuth } from '@features/auth';
import {
  attachDomainWorkspace,
  createDomainWorkspace,
  getDomainProjects,
  getDomainWorkspaces,
  setDomainPrimaryWorkspace,
  type DomainWorkspaceProjection,
} from '@features/domain';
import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';

interface RegisterDraft {
  environmentId: string;
  canonicalPath: string;
  label: string;
  context: string;
  projectId: string;
  makePrimary: boolean;
}

interface EditDraft {
  label: string;
  description: string;
  canonicalPath: string;
  context: string;
}

const emptyRegisterDraft: RegisterDraft = {
  environmentId: '',
  canonicalPath: '',
  label: '',
  context: '',
  projectId: '',
  makePrimary: false,
};

function editDraft(workspace: DomainWorkspaceProjection | null): EditDraft {
  return {
    label: workspace?.label ?? '',
    description: workspace?.description ?? '',
    canonicalPath: workspace?.canonical_path ?? '',
    context: workspace?.workspace_context ?? '',
  };
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  );
}

function WorkspacesPage() {
  const t = useT();
  const navigate = useNavigate();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [unregisterOpen, setUnregisterOpen] = useState(false);
  const [taskCreateOpen, setTaskCreateOpen] = useState(false);
  const [registerDraft, setRegisterDraft] = useState<RegisterDraft>(emptyRegisterDraft);
  const [editState, setEditState] = useState<EditDraft>(editDraft(null));

  const workspacesQuery = useQuery({
    queryKey: queryKeys.domain.workspaces(false),
    queryFn: () => getDomainWorkspaces(false),
  });
  const projectsQuery = useQuery({
    queryKey: queryKeys.domain.projects(false),
    queryFn: () => getDomainProjects(false),
  });
  const environmentsQuery = useQuery({
    queryKey: queryKeys.environments.all,
    queryFn: getEnvironments,
  });

  const workspaces = useMemo(() => workspacesQuery.data?.items ?? [], [workspacesQuery.data]);
  const projects = projectsQuery.data?.items ?? [];
  const environments = environmentsQuery.data?.items ?? [];
  const selectedWorkspace = workspaces.find((item) => item.workspace_id === selectedWorkspaceId)
    ?? workspaces[0]
    ?? null;
  const isOwner = selectedWorkspace?.owner_user_id === user?.id;

  const registerKey = useIdempotencyKey('workspace.register', registerDraft);
  const editKey = useIdempotencyKey('workspace.update', {
    workspaceId: selectedWorkspace?.workspace_id,
    ...editState,
  });
  const unregisterKeyManager = useRef(new IdempotencyKeyManager('workspace.unregister')).current;

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.workspaces(false) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(false) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.workspaces.all });
  };

  const registerMutation = useMutation({
    mutationFn: async () => {
      const workspace = await createDomainWorkspace(
        {
          environment_id: registerDraft.environmentId,
          canonical_path: registerDraft.canonicalPath.trim(),
          label: registerDraft.label.trim(),
        },
        `${registerKey.idempotencyKey}.create`,
      );
      if (registerDraft.context.trim()) {
        await updateWorkspace(
          workspace.workspace_id,
          { workspace_prompt: registerDraft.context.trim() },
          `${registerKey.idempotencyKey}.context`,
        );
      }
      if (registerDraft.projectId) {
        await attachDomainWorkspace(
          registerDraft.projectId,
          workspace.workspace_id,
          `${registerKey.idempotencyKey}.attach`,
        );
        if (registerDraft.makePrimary) {
          await setDomainPrimaryWorkspace(
            registerDraft.projectId,
            workspace.workspace_id,
            `${registerKey.idempotencyKey}.primary`,
          );
        }
      }
      return workspace;
    },
    onSuccess: (workspace) => {
      registerKey.markSucceeded();
      setRegisterOpen(false);
      setRegisterDraft(emptyRegisterDraft);
      setSelectedWorkspaceId(workspace.workspace_id);
      invalidate();
    },
  });

  const editMutation = useMutation({
    mutationFn: () => {
      if (!selectedWorkspace) throw new Error('Workspace is required');
      const payload = {
        label: editState.label.trim(),
        description: editState.description.trim() || null,
        default_workdir: editState.canonicalPath.trim(),
        ...(editState.context.trim() ? { workspace_prompt: editState.context.trim() } : {}),
      };
      return updateWorkspace(
        selectedWorkspace.workspace_id,
        payload,
        editKey.idempotencyKey,
      );
    },
    onSuccess: () => {
      editKey.markSucceeded();
      setEditOpen(false);
      invalidate();
    },
  });

  const unregisterMutation = useMutation({
    mutationFn: () => {
      if (!selectedWorkspace) throw new Error('Workspace is required');
      const key = unregisterKeyManager.keyFor(semanticMutationValue({ workspaceId: selectedWorkspace.workspace_id }));
      return unregisterWorkspace(selectedWorkspace.workspace_id, key).then(() => key);
    },
    onSuccess: (key) => {
      unregisterKeyManager.markSucceeded(key);
      setSelectedWorkspaceId(null);
      invalidate();
    },
  });

  const operationError = registerMutation.error ?? editMutation.error ?? unregisterMutation.error;

  return (
    <PageShell variant="canvas">
      <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-5 p-4 md:p-6">
        <PageHeader
          eyebrow={t('pages.workspaces.eyebrow')}
          title={t('pages.workspaces.title')}
          description={t('pages.workspaces.description')}
          actions={<Button onClick={() => setRegisterOpen(true)}>{t('pages.workspaces.register')}</Button>}
        />

        {operationError ? <Alert variant="error">{extractErrorMessage(operationError)}</Alert> : null}
        {workspacesQuery.error instanceof Error ? (
          <Alert variant="error">{workspacesQuery.error.message}</Alert>
        ) : null}

        <div className="grid min-h-0 gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
          <Card className="min-h-0">
            <CardBody className="space-y-2 p-3">
              {workspaces.map((workspace) => (
                <button
                  key={workspace.workspace_id}
                  type="button"
                  onClick={() => setSelectedWorkspaceId(workspace.workspace_id)}
                  className={`w-full rounded-[var(--osci-radius-md)] border p-3 text-left transition ${
                    selectedWorkspace?.workspace_id === workspace.workspace_id
                      ? 'border-[var(--osci-color-primary-border)] bg-[var(--osci-color-primary-soft)]'
                      : 'border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface)] hover:bg-[var(--osci-color-surface-subtle)]'
                  }`}
                >
                  <span className="flex items-center justify-between gap-2">
                    <span className="truncate text-sm font-semibold text-[var(--osci-color-text)]">{workspace.label}</span>
                    <StatusBadge tone={workspace.can_execute ? 'success' : 'warning'}>
                      {workspace.can_execute ? t('pages.workspaces.executable') : t('pages.workspaces.linkedOnly')}
                    </StatusBadge>
                  </span>
                  <span className="mt-1 block truncate text-xs text-[var(--osci-color-text-muted)]">{workspace.canonical_path}</span>
                  <span className="mt-2 block text-xs text-[var(--osci-color-text-secondary)]">
                    {workspace.environment.display_name} · {workspace.project_links.filter((link) => link.link_status === 'active').length} {t('pages.workspaces.projects')}
                  </span>
                </button>
              ))}
              {!workspacesQuery.isLoading && workspaces.length === 0 ? (
                <EmptyState title={t('pages.workspaces.emptyTitle')} message={t('pages.workspaces.emptyDescription')} />
              ) : null}
            </CardBody>
          </Card>

          {selectedWorkspace ? (
            <div className="space-y-5">
              <Card>
                <CardBody className="space-y-5 p-5 md:p-6">
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <div className="flex flex-wrap items-center gap-2">
                        <h2 className="text-xl font-semibold text-[var(--osci-color-text)]">{selectedWorkspace.label}</h2>
                        <Badge variant="outline">{selectedWorkspace.status}</Badge>
                        <StatusBadge tone={selectedWorkspace.can_execute ? 'success' : 'warning'}>
                          {selectedWorkspace.can_execute ? t('pages.workspaces.availableForTasks') : t('pages.workspaces.notAvailableForTasks')}
                        </StatusBadge>
                      </div>
                      <p className="mt-2 text-sm text-[var(--osci-color-text-secondary)]">{selectedWorkspace.description || t('pages.workspaces.noDescription')}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        variant="secondary"
                        onClick={() => navigate(`/workspace-browser?environment_id=${encodeURIComponent(selectedWorkspace.environment.environment_id)}&workspace_id=${encodeURIComponent(selectedWorkspace.workspace_id)}`)}
                      >
                        {t('pages.workspaces.files')}
                      </Button>
                      <Button
                        variant="secondary"
                        onClick={() => navigate(`/terminal?environment_id=${encodeURIComponent(selectedWorkspace.environment.environment_id)}`)}
                      >
                        {t('pages.workspaces.terminal')}
                      </Button>
                      <Button
                        disabled={!selectedWorkspace.can_execute}
                        title={selectedWorkspace.cannot_execute_reason ?? undefined}
                        onClick={() => setTaskCreateOpen(true)}
                      >
                        {t('pages.tasks.newTask')}
                      </Button>
                    </div>
                  </div>

                  {!selectedWorkspace.can_execute ? (
                    <Alert variant="warning">
                      {t('pages.workspaces.cannotExecute')}: {selectedWorkspace.cannot_execute_reason ?? t('pages.workspaces.unknownReason')}
                    </Alert>
                  ) : null}

                  <dl className="grid gap-4 text-sm sm:grid-cols-2 xl:grid-cols-3">
                    <div><dt className="text-[var(--osci-color-text-muted)]">{t('pages.workspaces.environment')}</dt><dd className="mt-1 font-medium text-[var(--osci-color-text)]">{selectedWorkspace.environment.display_name} ({selectedWorkspace.environment.alias})</dd></div>
                    <div><dt className="text-[var(--osci-color-text-muted)]">{t('pages.workspaces.canonicalPath')}</dt><dd className="mt-1 break-all font-mono text-[var(--osci-color-text)]">{selectedWorkspace.canonical_path}</dd></div>
                    <div><dt className="text-[var(--osci-color-text-muted)]">{t('pages.workspaces.owner')}</dt><dd className="mt-1 font-mono text-[var(--osci-color-text)]">{selectedWorkspace.owner_user_id}</dd></div>
                    <div><dt className="text-[var(--osci-color-text-muted)]">{t('pages.workspaces.tasks')}</dt><dd className="mt-1 text-[var(--osci-color-text)]">{selectedWorkspace.active_task_count} active / {selectedWorkspace.task_count} total</dd></div>
                    <div><dt className="text-[var(--osci-color-text-muted)]">{t('pages.workspaces.recentActivity')}</dt><dd className="mt-1 text-[var(--osci-color-text)]">{formatDate(selectedWorkspace.recent_activity_at)}</dd></div>
                    <div><dt className="text-[var(--osci-color-text-muted)]">Git</dt><dd className="mt-1 text-[var(--osci-color-text)]">{selectedWorkspace.git_status.state === 'available' ? `${selectedWorkspace.git_status.branch ?? 'detached'}${selectedWorkspace.git_status.is_dirty ? ' · dirty' : ' · clean'}` : selectedWorkspace.git_status.state}</dd></div>
                  </dl>
                </CardBody>
              </Card>

              <Card>
                <CardBody className="space-y-4 p-5 md:p-6">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="font-semibold text-[var(--osci-color-text)]">{t('pages.workspaces.projectLinks')}</h3>
                      <p className="text-sm text-[var(--osci-color-text-secondary)]">{t('pages.workspaces.projectLinksDescription')}</p>
                    </div>
                    {isOwner ? (
                      <div className="flex gap-2">
                        <Button variant="secondary" onClick={() => { setEditState(editDraft(selectedWorkspace)); setEditOpen(true); }}>{t('pages.workspaces.edit')}</Button>
                        <Button variant="danger" onClick={() => setUnregisterOpen(true)}>{t('pages.workspaces.unregister')}</Button>
                      </div>
                    ) : null}
                  </div>
                  <div className="space-y-2">
                    {selectedWorkspace.project_links.filter((link) => link.link_status === 'active').map((link) => (
                      <div key={link.project_id} className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] p-3">
                        <div><p className="font-medium text-[var(--osci-color-text)]">{link.project_name}</p><p className="text-xs text-[var(--osci-color-text-muted)]">{link.current_user_role} · {link.project_status}</p></div>
                        <div className="flex items-center gap-2">{link.is_primary ? <Badge>{t('pages.workspaces.primary')}</Badge> : null}<StatusBadge tone={link.can_execute ? 'success' : 'warning'}>{link.can_execute ? t('pages.workspaces.executable') : link.cannot_execute_reason ?? t('pages.workspaces.linkedOnly')}</StatusBadge></div>
                      </div>
                    ))}
                    {selectedWorkspace.project_links.filter((link) => link.link_status === 'active').length === 0 ? <p className="text-sm text-[var(--osci-color-text-muted)]">{t('pages.workspaces.noProjectLinks')}</p> : null}
                  </div>
                </CardBody>
              </Card>
            </div>
          ) : null}
        </div>
      </div>

      <Dialog isOpen={registerOpen} onClose={() => setRegisterOpen(false)} title={t('pages.workspaces.registerTitle')} size="lg">
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); registerMutation.mutate(); }}>
          <FormField label={t('pages.workspaces.environment')}>
            <NativeSelect aria-label={t('pages.workspaces.environment')} required value={registerDraft.environmentId} onChange={(event) => setRegisterDraft((current) => ({ ...current, environmentId: event.target.value }))}>
              <option value="">{t('pages.workspaces.selectEnvironment')}</option>
              {environments.map((environment) => <option key={environment.id} value={environment.id}>{environment.display_name} ({environment.alias})</option>)}
            </NativeSelect>
          </FormField>
          <FormField label={t('pages.workspaces.canonicalPath')}><Input aria-label={t('pages.workspaces.canonicalPath')} required value={registerDraft.canonicalPath} onChange={(event) => setRegisterDraft((current) => ({ ...current, canonicalPath: event.target.value }))} /></FormField>
          <FormField label={t('pages.workspaces.labelField')}><Input aria-label={t('pages.workspaces.labelField')} required value={registerDraft.label} onChange={(event) => setRegisterDraft((current) => ({ ...current, label: event.target.value }))} /></FormField>
          <FormField label={t('pages.workspaces.context')}><Textarea aria-label={t('pages.workspaces.context')} value={registerDraft.context} onChange={(event) => setRegisterDraft((current) => ({ ...current, context: event.target.value }))} /></FormField>
          <FormField label={t('pages.workspaces.optionalProject')}>
            <NativeSelect aria-label={t('pages.workspaces.optionalProject')} value={registerDraft.projectId} onChange={(event) => setRegisterDraft((current) => ({ ...current, projectId: event.target.value, makePrimary: event.target.value ? current.makePrimary : false }))}>
              <option value="">{t('pages.workspaces.noInitialProject')}</option>
              {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
            </NativeSelect>
          </FormField>
          <label className="flex items-center gap-2 text-sm text-[var(--osci-color-text)]">
            <Checkbox
              checked={registerDraft.makePrimary}
              disabled={!registerDraft.projectId}
              onCheckedChange={(checked) => setRegisterDraft((current) => ({ ...current, makePrimary: checked === true }))}
              aria-label={t('pages.workspaces.makePrimary')}
            />
            {t('pages.workspaces.makePrimary')}
          </label>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setRegisterOpen(false)}>{t('common.cancel')}</Button><Button type="submit" isLoading={registerMutation.isPending}>{t('pages.workspaces.register')}</Button></div>
        </form>
      </Dialog>

      <Dialog isOpen={editOpen} onClose={() => setEditOpen(false)} title={t('pages.workspaces.editTitle')} size="lg">
        <form className="space-y-4" onSubmit={(event) => { event.preventDefault(); editMutation.mutate(); }}>
          <FormField label={t('pages.workspaces.labelField')}><Input aria-label={t('pages.workspaces.labelField')} required value={editState.label} onChange={(event) => setEditState((current) => ({ ...current, label: event.target.value }))} /></FormField>
          <FormField label={t('pages.workspaces.descriptionField')}><Input aria-label={t('pages.workspaces.descriptionField')} value={editState.description} onChange={(event) => setEditState((current) => ({ ...current, description: event.target.value }))} /></FormField>
          <FormField label={t('pages.workspaces.canonicalPath')}><Input aria-label={t('pages.workspaces.canonicalPath')} required value={editState.canonicalPath} onChange={(event) => setEditState((current) => ({ ...current, canonicalPath: event.target.value }))} /></FormField>
          <FormField label={t('pages.workspaces.context')}><Textarea aria-label={t('pages.workspaces.context')} value={editState.context} onChange={(event) => setEditState((current) => ({ ...current, context: event.target.value }))} /></FormField>
          <div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setEditOpen(false)}>{t('common.cancel')}</Button><Button type="submit" isLoading={editMutation.isPending}>{t('pages.workspaces.saveWorkspace')}</Button></div>
        </form>
      </Dialog>

      <ConfirmDialog
        open={unregisterOpen}
        onOpenChange={setUnregisterOpen}
        title={t('pages.workspaces.unregisterTitle')}
        description={t('pages.workspaces.unregisterDescription')}
        confirmLabel={t('pages.workspaces.unregister')}
        danger
        onConfirm={() => unregisterMutation.mutate()}
      />

      <TaskCreateFlow isOpen={taskCreateOpen} onClose={() => setTaskCreateOpen(false)} source="workspace" lockedWorkspaceId={selectedWorkspace?.workspace_id} />
    </PageShell>
  );
}

export default WorkspacesPage;
