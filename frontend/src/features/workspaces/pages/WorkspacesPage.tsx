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
  PageShell,
  StatusBadge,
  Textarea,
} from '@design-system';
import { getEnvironments } from '@features/environments';
import { IdempotencyKeyManager, semanticMutationValue, useIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import { useLocale, useT } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import { copyText } from '@/shared/utils/clipboard';
import { useAuth } from '@features/auth';
import {
  attachDomainWorkspace,
  createDomainWorkspace,
  getDomainProjects,
  getDomainWorkspaces,
  setDomainPrimaryWorkspace,
  unregisterDomainWorkspace,
  updateDomainWorkspace,
  type DomainWorkspaceProjection,
} from '@features/domain';
import { projectionReasonLabel } from '@features/domain';
import { TaskCreateFlow } from '@features/tasks';

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

function formatDate(value: string | null | undefined, locale: 'en' | 'zh'): string {
  if (!value) return '—';
  return new Intl.DateTimeFormat(locale === 'zh' ? 'zh-CN' : 'en-US', { dateStyle: 'medium', timeStyle: 'short' }).format(
    new Date(value),
  );
}

function WorkspacesPage() {
  const t = useT();
  const locale = useLocale();
  const navigate = useNavigate();
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [registerOpen, setRegisterOpen] = useState(false);
  const [editOpen, setEditOpen] = useState(false);
  const [unregisterOpen, setUnregisterOpen] = useState(false);
  const [taskCreateOpen, setTaskCreateOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showExecutableOnly, setShowExecutableOnly] = useState(false);
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
  const filteredWorkspaces = useMemo(() => {
    const normalizedQuery = searchQuery.trim().toLowerCase();
    return workspaces.filter((workspace) => {
      const matchesAvailability = !showExecutableOnly || workspace.can_execute;
      const matchesQuery = !normalizedQuery || [
        workspace.label,
        workspace.canonical_path,
        workspace.environment.display_name,
        workspace.environment.alias,
      ].some((value) => value.toLowerCase().includes(normalizedQuery));
      return matchesAvailability && matchesQuery;
    });
  }, [searchQuery, showExecutableOnly, workspaces]);
  const projects = projectsQuery.data?.items ?? [];
  const environments = environmentsQuery.data?.items ?? [];
  const selectedWorkspace = filteredWorkspaces.find((item) => item.workspace_id === selectedWorkspaceId)
    ?? filteredWorkspaces[0]
    ?? null;
  const isOwner = selectedWorkspace?.owner_user_id === user?.id;
  const selectedWorkspaceUnavailableReason = selectedWorkspace
    ? projectionReasonLabel(locale, selectedWorkspace.cannot_execute_reason)
    : null;

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
        await updateDomainWorkspace(
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
      return updateDomainWorkspace(
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
      return unregisterDomainWorkspace(selectedWorkspace.workspace_id, key).then(() => key);
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
      <div className="mx-auto flex min-h-0 w-full max-w-[1600px] flex-1 flex-col gap-3 p-3 md:p-4">
        <header className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border)] bg-[var(--osci-color-surface)] px-4 py-3 shadow-[var(--osci-shadow-sm)]">
          <div className="min-w-0">
            <div className="flex items-baseline gap-3">
              <h1 className="text-xl font-semibold tracking-tight text-[var(--osci-color-text)] md:text-2xl">
                {t('pages.workspaces.title')}
              </h1>
              <span className="text-sm text-[var(--osci-color-text-muted)]">
                {t('pages.workspaces.workspaceCount', { count: workspaces.length })}
              </span>
            </div>
            <p className="mt-0.5 truncate text-xs text-[var(--osci-color-text-secondary)] md:text-sm">
              {t('pages.workspaces.consoleDescription')}
            </p>
          </div>
          <Button size="sm" onClick={() => setRegisterOpen(true)}>
            <span aria-hidden="true">＋</span>
            {t('pages.workspaces.newAction')}
          </Button>
        </header>

        {operationError ? <Alert variant="error">{extractErrorMessage(operationError)}</Alert> : null}
        {workspacesQuery.error instanceof Error ? (
          <Alert variant="error">{workspacesQuery.error.message}</Alert>
        ) : null}

        <div className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-3 xl:grid-cols-[360px_minmax(0,1fr)] xl:grid-rows-1">
          <Card className="hidden min-h-0 flex-col overflow-hidden xl:flex">
            <div className="space-y-2 border-b border-[var(--osci-color-border-subtle)] p-3">
              <label className="relative block">
                <span className="sr-only">{t('pages.workspaces.searchLabel')}</span>
                <span aria-hidden="true" className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-[var(--osci-color-text-muted)]">⌕</span>
                <Input
                  aria-label={t('pages.workspaces.searchLabel')}
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={t('pages.workspaces.searchPlaceholder')}
                  className="pl-9"
                />
              </label>
              <label className="flex min-h-8 items-center gap-2 px-1 text-xs leading-none text-[var(--osci-color-text-secondary)]">
                <Checkbox
                  checked={showExecutableOnly}
                  onCheckedChange={(checked) => setShowExecutableOnly(checked === true)}
                  aria-label={t('pages.workspaces.showAvailableOnly')}
                />
                <span className="whitespace-nowrap">{t('pages.workspaces.showAvailableOnly')}</span>
              </label>
            </div>
            <CardBody className="min-h-0 flex-1 space-y-1 overflow-auto p-2">
              {filteredWorkspaces.map((workspace) => (
                <button
                  key={workspace.workspace_id}
                  type="button"
                  onClick={() => setSelectedWorkspaceId(workspace.workspace_id)}
                  className={`w-full rounded-[var(--osci-radius-md)] border px-3 py-2.5 text-left transition ${
                    selectedWorkspace?.workspace_id === workspace.workspace_id
                      ? 'border-[var(--osci-color-primary-border)] bg-[var(--osci-color-primary-soft)]'
                      : 'border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface)] hover:bg-[var(--osci-color-surface-subtle)]'
                  }`}
                >
                  <span className="flex items-center justify-between gap-3">
                    <span className="truncate text-sm font-semibold text-[var(--osci-color-text)]">{workspace.label}</span>
                    <StatusBadge className="shrink-0 whitespace-nowrap" tone={workspace.can_execute ? 'success' : 'warning'}>
                      {workspace.can_execute ? t('pages.workspaces.available') : t('pages.workspaces.unavailable')}
                    </StatusBadge>
                  </span>
                  <span className="mt-1 block truncate font-mono text-[11px] text-[var(--osci-color-text-muted)]">{workspace.canonical_path}</span>
                  <span className="mt-1.5 flex items-center justify-between gap-3 text-xs text-[var(--osci-color-text-secondary)]">
                    <span className="truncate">{workspace.environment.display_name}</span>
                    <span className="shrink-0">{t('pages.workspaces.projectCount', { count: workspace.project_links.filter((link) => link.link_status === 'active').length })}</span>
                  </span>
                </button>
              ))}
              {!workspacesQuery.isLoading && filteredWorkspaces.length === 0 ? (
                <EmptyState title={t('pages.workspaces.emptyTitle')} message={t('pages.workspaces.emptyDescription')} />
              ) : null}
            </CardBody>
          </Card>

          <Card className="xl:hidden">
            <CardBody className="p-3">
              <NativeSelect
                aria-label={t('pages.workspaces.selectWorkspace')}
                value={selectedWorkspace?.workspace_id ?? ''}
                onChange={(event) => setSelectedWorkspaceId(event.target.value)}
              >
                {workspaces.map((workspace) => (
                  <option key={workspace.workspace_id} value={workspace.workspace_id}>
                    {workspace.label} · {workspace.can_execute ? t('pages.workspaces.available') : t('pages.workspaces.unavailable')}
                  </option>
                ))}
              </NativeSelect>
            </CardBody>
          </Card>

          {selectedWorkspace ? (
            <Card className="min-h-0 overflow-auto">
              <CardBody className="space-y-4 p-4 md:p-5">
                <div className="border-b border-[var(--osci-color-border-subtle)] pb-4">
                  <div className="flex flex-col items-start gap-3 xl:flex-row xl:justify-between">
                    <h2 className="w-full min-w-0 text-lg font-semibold text-[var(--osci-color-text)] md:text-xl xl:flex-1 xl:truncate">{selectedWorkspace.label}</h2>
                    <div className="flex flex-wrap gap-2">
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => navigate(`/workspace-browser?environment_id=${encodeURIComponent(selectedWorkspace.environment.environment_id)}&workspace_id=${encodeURIComponent(selectedWorkspace.workspace_id)}`)}
                      >
                        {t('pages.workspaces.files')}
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        onClick={() => navigate(`/terminal?environment_id=${encodeURIComponent(selectedWorkspace.environment.environment_id)}`)}
                      >
                        {t('pages.workspaces.terminal')}
                      </Button>
                      <Button
                        size="sm"
                        disabled={!selectedWorkspace.can_execute}
                        title={selectedWorkspaceUnavailableReason ?? undefined}
                        onClick={() => setTaskCreateOpen(true)}
                      >
                        {t('pages.tasks.newTask')}
                      </Button>
                    </div>
                  </div>
                  <div className="mt-2 flex min-w-0 items-center gap-2">
                    <StatusBadge className="shrink-0 whitespace-nowrap" tone={selectedWorkspace.can_execute ? 'success' : 'warning'}>
                      {selectedWorkspace.can_execute ? t('pages.workspaces.available') : t('pages.workspaces.unavailable')}
                    </StatusBadge>
                    <div className="flex min-w-0 flex-1 items-center gap-1.5 text-xs text-[var(--osci-color-text-muted)]">
                      <span className="truncate font-mono" title={selectedWorkspace.canonical_path}>{selectedWorkspace.canonical_path}</span>
                      <button
                        type="button"
                        className="flex h-6 w-8 shrink-0 items-center justify-center rounded-md hover:bg-[var(--osci-color-surface-subtle)] hover:text-[var(--osci-color-primary)]"
                        aria-label={t('pages.workspaces.copyPath')}
                        title={t('pages.workspaces.copyPath')}
                        onClick={() => { void copyText(selectedWorkspace.canonical_path); }}
                      >
                        <span aria-hidden="true" className="text-[10px]">{t('pages.workspaces.copy')}</span>
                      </button>
                    </div>
                  </div>
                  <p className="mt-2 w-full text-sm text-[var(--osci-color-text-secondary)]">{selectedWorkspace.description || t('pages.workspaces.noDescription')}</p>
                </div>

                {!selectedWorkspace.can_execute ? (
                  <div className="flex items-start gap-2 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-warning-border)] bg-[var(--osci-color-warning-soft)] px-3 py-2 text-sm text-[var(--osci-color-warning-foreground)]">
                    <span aria-hidden="true" className="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
                    <span><strong>{t('pages.workspaces.unavailableReason')}</strong>{selectedWorkspaceUnavailableReason}</span>
                  </div>
                ) : null}

                <dl className="grid overflow-hidden rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] text-sm sm:grid-cols-2 xl:grid-cols-3">
                  {[
                    [t('pages.workspaces.environment'), `${selectedWorkspace.environment.display_name} (${selectedWorkspace.environment.alias})`],
                    [t('pages.workspaces.owner'), selectedWorkspace.owner_user_id],
                    [t('pages.workspaces.tasks'), t('pages.workspaces.taskSummary', { active: selectedWorkspace.active_task_count, total: selectedWorkspace.task_count })],
                    [t('pages.workspaces.recentActivity'), formatDate(selectedWorkspace.recent_activity_at, locale)],
                    ['Git', selectedWorkspace.git_status.state === 'available' ? `${selectedWorkspace.git_status.branch ?? 'detached'}${selectedWorkspace.git_status.is_dirty ? ' · dirty' : ' · clean'}` : selectedWorkspace.git_status.state],
                    [t('pages.workspaces.lifecycle'), selectedWorkspace.status],
                  ].map(([label, value]) => (
                    <div key={label} className="border-b border-[var(--osci-color-border-subtle)] px-3 py-2.5 sm:border-r xl:last:border-r-0">
                      <dt className="text-[11px] text-[var(--osci-color-text-muted)]">{label}</dt>
                      <dd className="mt-0.5 truncate font-medium text-[var(--osci-color-text)]" title={value}>{value}</dd>
                    </div>
                  ))}
                </dl>

                <section className="space-y-3 border-t border-[var(--osci-color-border-subtle)] pt-4">
                  <div className="flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <h3 className="text-sm font-semibold text-[var(--osci-color-text)]">{t('pages.workspaces.projectLinks')}</h3>
                      <p className="text-xs text-[var(--osci-color-text-secondary)]">{t('pages.workspaces.projectLinksDescription')}</p>
                    </div>
                    {isOwner ? (
                      <div className="flex gap-2">
                        <Button size="sm" variant="secondary" onClick={() => { setEditState(editDraft(selectedWorkspace)); setEditOpen(true); }}>{t('pages.workspaces.edit')}</Button>
                        <Button size="sm" variant="danger" onClick={() => setUnregisterOpen(true)}>{t('pages.workspaces.unregister')}</Button>
                      </div>
                    ) : null}
                  </div>
                  <div className="space-y-2">
                    {selectedWorkspace.project_links.filter((link) => link.link_status === 'active').map((link) => (
                      <div key={link.project_id} className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] px-3 py-2">
                        <div><p className="text-sm font-medium text-[var(--osci-color-text)]">{link.project_name}</p><p className="text-[11px] text-[var(--osci-color-text-muted)]">{link.current_user_role} · {link.project_status}</p></div>
                        <div className="flex items-center gap-2">{link.is_primary ? <Badge>{t('pages.workspaces.primary')}</Badge> : null}<StatusBadge className="whitespace-nowrap" tone={link.can_execute ? 'success' : 'warning'}>{link.can_execute ? t('pages.workspaces.available') : projectionReasonLabel(locale, link.cannot_execute_reason)}</StatusBadge></div>
                      </div>
                    ))}
                    {selectedWorkspace.project_links.filter((link) => link.link_status === 'active').length === 0 ? <p className="text-sm text-[var(--osci-color-text-muted)]">{t('pages.workspaces.noProjectLinks')}</p> : null}
                  </div>
                </section>
              </CardBody>
            </Card>
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
