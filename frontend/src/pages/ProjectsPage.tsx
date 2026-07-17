import { useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Alert,
  Badge,
  Button,
  Card,
  CardBody,
  Dialog,
  EmptyState,
  FormField,
  Input,
  NativeSelect,
  PageHeader,
  PageShell,
  StatusBadge,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
  Textarea,
  ViewToolbar,
} from '@design-system';
import { ProjectCanvas } from '../components/project';
import { getProjectTasks, getTaskEdges, moveTask } from '@/shared/api';
import { IdempotencyKeyManager, semanticMutationValue, useIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import { useLocale, useT } from '@/shared/i18n';
import { extractErrorMessage } from '@/shared/utils/error';
import type { ProjectRecord } from '@/shared/types';
import {
  attachDomainWorkspace,
  createDomainProject,
  detachDomainWorkspace,
  getDomainProjectContext,
  getDomainProjects,
  getDomainWorkspaces,
  replaceDomainPrimaryWorkspace,
  setDomainPrimaryWorkspace,
  type DomainProjectProjection,
  type DomainWorkspaceProjection,
} from '@features/domain';
import { projectionReasonLabel, projectionReasonList } from '@features/domain/projectionReasons';
import TaskCreateFlow from '@features/tasks/components/TaskCreateFlow';
import { ProjectContextConsole, ProjectSettingsConsole } from '@features/projects';
import { useAuth } from '@features/auth';

type ProjectTab = 'overview' | 'tasks' | 'workspaces' | 'context' | 'settings';
type TaskView = 'list' | 'graph';
const PROJECT_TABS = new Set<ProjectTab>(['overview', 'tasks', 'workspaces', 'context', 'settings']);

function asCanvasProject(project: DomainProjectProjection): ProjectRecord {
  return {
    project_id: project.project_id,
    name: project.name,
    description: project.description,
    default_workspace_id: project.primary_workspace?.workspace_id ?? null,
    default_environment_id: project.primary_workspace?.environment_id ?? null,
    created_at: project.created_at,
    updated_at: project.updated_at,
    owner_user_id: project.owner_user_id,
  };
}

function workspaceLink(workspace: DomainWorkspaceProjection, projectId: string) {
  return workspace.project_links.find((link) => link.project_id === projectId && link.link_status === 'active');
}

export default function ProjectsPage() {
  const t = useT();
  const locale = useLocale();
  const { user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const [taskCreateOpen, setTaskCreateOpen] = useState(false);
  const [createProjectOpen, setCreateProjectOpen] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');
  const [attachWorkspaceId, setAttachWorkspaceId] = useState('');
  const [layoutVersion, setLayoutVersion] = useState(0);

  const projectsQuery = useQuery({
    queryKey: queryKeys.domain.projects(true),
    queryFn: () => getDomainProjects(true),
  });
  const workspacesQuery = useQuery({
    queryKey: queryKeys.domain.workspaces(false),
    queryFn: () => getDomainWorkspaces(false),
  });
  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);
  const workspaces = useMemo(() => workspacesQuery.data?.items ?? [], [workspacesQuery.data]);
  const requestedProjectId = searchParams.get('project');
  const selectedProject = projects.find((project) => project.project_id === requestedProjectId)
    ?? projects[0]
    ?? null;
  const rawTab = searchParams.get('tab') as ProjectTab | null;
  const tab: ProjectTab = rawTab && PROJECT_TABS.has(rawTab) ? rawTab : 'overview';
  const view: TaskView = searchParams.get('view') === 'graph' ? 'graph' : 'list';

  const setRouteState = (updates: Record<string, string>) => {
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(updates)) next.set(key, value);
      return next;
    });
  };

  const projectId = selectedProject?.project_id ?? null;
  const tasksQuery = useQuery({
    queryKey: queryKeys.projectTasks.byProject(projectId),
    queryFn: () => projectId ? getProjectTasks(projectId, { limit: 500 }) : Promise.resolve({ items: [], has_more: false }),
    enabled: projectId !== null,
  });
  const edgesQuery = useQuery({
    queryKey: queryKeys.taskEdges.byProject(projectId),
    queryFn: () => projectId ? getTaskEdges(projectId) : Promise.resolve({ items: [] }),
    enabled: projectId !== null,
  });
  const tasks = tasksQuery.data?.items ?? [];
  const edges = edgesQuery.data?.items ?? [];
  const linkedWorkspaces = selectedProject
    ? workspaces.filter((workspace) => workspaceLink(workspace, selectedProject.project_id))
    : [];
  const attachableWorkspaces = selectedProject
    ? workspaces.filter((workspace) => !workspaceLink(workspace, selectedProject.project_id) && workspace.status === 'active')
    : [];
  const canCreateTask = Boolean(selectedProject?.permissions.can_create_task && selectedProject.executable_workspace_count > 0 && selectedProject.status === 'active');
  const attentionReasonLabels = selectedProject
    ? projectionReasonList(locale, selectedProject.attention_reasons)
    : [];
  const createTaskUnavailableReason = attentionReasonLabels.join(' ')
    || projectionReasonLabel(locale, 'no_executable_workspace');
  const eligibleTargetProjects = projects.filter(
    (project) => project.status === 'active' && project.permissions.can_create_task,
  );
  const canMoveTask = (taskId: string): boolean => {
    const task = tasks.find((candidate) => candidate.task_id === taskId);
    return Boolean(
      task
      && user
      && selectedProject?.status === 'active'
      && (user.role === 'admin' || task.owner_user_id === user.id),
    );
  };

  const createKey = useIdempotencyKey('project.create', { projectName, projectDescription });
  const attachKey = useIdempotencyKey('project.workspace.attach', { projectId, attachWorkspaceId });
  const detachKeyManager = useRef(new IdempotencyKeyManager('project.workspace.detach')).current;
  const primaryKeyManager = useRef(new IdempotencyKeyManager('project.workspace.primary')).current;
  const moveTaskKeyManager = useRef(new IdempotencyKeyManager('task.move.project')).current;
  const createMutation = useMutation({
    mutationFn: () => createDomainProject({ name: projectName.trim(), description: projectDescription.trim() || null }, createKey.idempotencyKey),
    onSuccess: (project) => {
      createKey.markSucceeded();
      setCreateProjectOpen(false);
      setProjectName('');
      setProjectDescription('');
      setRouteState({ project: project.project_id, tab: 'overview' });
      void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(true) });
    },
  });

  const invalidateWorkspaceState = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(true) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.workspaces(false) });
  };

  const attachMutation = useMutation({
    mutationFn: () => {
      if (!projectId || !attachWorkspaceId) throw new Error('Project and Workspace are required');
      return attachDomainWorkspace(projectId, attachWorkspaceId, attachKey.idempotencyKey);
    },
    onSuccess: () => { attachKey.markSucceeded(); setAttachWorkspaceId(''); invalidateWorkspaceState(); },
  });

  const detachMutation = useMutation({
    mutationFn: (workspaceId: string) => {
      if (!projectId) throw new Error('Project is required');
      const key = detachKeyManager.keyFor(semanticMutationValue({ projectId, workspaceId }));
      return detachDomainWorkspace(projectId, workspaceId, key).then(() => key);
    },
    onSuccess: (key) => { detachKeyManager.markSucceeded(key); invalidateWorkspaceState(); },
  });

  const primaryMutation = useMutation({
    mutationFn: (workspaceId: string) => {
      if (!selectedProject) throw new Error('Project is required');
      const semantic = semanticMutationValue({ projectId: selectedProject.project_id, workspaceId, previousPrimaryId: selectedProject.primary_workspace?.workspace_id ?? null });
      const key = primaryKeyManager.keyFor(semantic);
      const request = selectedProject.primary_workspace
        ? replaceDomainPrimaryWorkspace(selectedProject.project_id, selectedProject.primary_workspace.workspace_id, workspaceId, key)
        : setDomainPrimaryWorkspace(selectedProject.project_id, workspaceId, key);
      return request.then(() => key);
    },
    onSuccess: (key) => { primaryKeyManager.markSucceeded(key); invalidateWorkspaceState(); },
  });

  const moveTaskToProject = async (taskId: string, targetProjectId: string) => {
    if (!canMoveTask(taskId)) throw new Error('Only the Task owner or an administrator can move this Task');
    if (!eligibleTargetProjects.some((project) => project.project_id === targetProjectId)) {
      throw new Error('The target Project is not available for Task creation');
    }
    const targetContext = await getDomainProjectContext(targetProjectId);
    const contextVersionId = targetContext.active_version?.context_version_id;
    if (!contextVersionId) throw new Error('Target Project has no active Context Version');
    const payload = { project_id: targetProjectId, context_version_id: contextVersionId };
    const key = moveTaskKeyManager.keyFor(semanticMutationValue({ taskId, ...payload }));
    await moveTask(taskId, payload, key);
    moveTaskKeyManager.markSucceeded(key);
    void queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks.byProject(projectId) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks.byProject(targetProjectId) });
  };

  const operationError = createMutation.error ?? attachMutation.error ?? detachMutation.error ?? primaryMutation.error;

  return (
    <PageShell variant="canvas">
      <div className="mx-auto flex w-full max-w-[1550px] flex-col gap-5 p-4 md:p-6">
        <PageHeader
          eyebrow={t('pages.projects.eyebrow')}
          title={t('pages.projects.title')}
          description={t('pages.projects.description')}
          actions={<Button onClick={() => setCreateProjectOpen(true)}>{t('pages.projects.newProject')}</Button>}
        />
        {operationError ? <Alert variant="error">{extractErrorMessage(operationError)}</Alert> : null}
        <div className="grid gap-5 lg:grid-cols-[300px_minmax(0,1fr)]">
          <Card><CardBody className="space-y-2 p-3">
            {projects.map((project) => (
              <button key={project.project_id} type="button" onClick={() => setRouteState({ project: project.project_id, tab })} className={`w-full rounded-[var(--osci-radius-md)] border p-3 text-left ${selectedProject?.project_id === project.project_id ? 'border-[var(--osci-color-primary-border)] bg-[var(--osci-color-primary-soft)]' : 'border-[var(--osci-color-border-subtle)] hover:bg-[var(--osci-color-surface-subtle)]'}`}>
                <span className="flex items-center justify-between gap-2"><span className="truncate font-semibold text-[var(--osci-color-text)]">{project.name}</span>{project.attention_required ? <StatusBadge tone="warning">Attention</StatusBadge> : null}</span>
                <span className="mt-1 block text-xs text-[var(--osci-color-text-muted)]">{project.running_task_count} running · {project.workspace_count} workspaces</span>
                <span className="mt-1 block text-xs text-[var(--osci-color-text-secondary)]">{new Date(project.recent_activity_at).toLocaleString()}</span>
              </button>
            ))}
            {!projectsQuery.isLoading && projects.length === 0 ? <EmptyState title={t('pages.projects.noProjects')} message={t('pages.projects.noProjects')} /> : null}
          </CardBody></Card>

          {selectedProject ? (
            <div className="min-w-0 space-y-4">
              <Card><CardBody className="p-5">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div><div className="flex flex-wrap items-center gap-2"><h2 className="text-xl font-semibold text-[var(--osci-color-text)]">{selectedProject.name}</h2><Badge variant="outline">{selectedProject.status}</Badge><Badge variant="secondary">{selectedProject.current_user_role}</Badge></div><p className="mt-2 text-sm text-[var(--osci-color-text-secondary)]">{selectedProject.description || 'No description'}</p></div>
                  <Button disabled={!canCreateTask} title={!canCreateTask ? createTaskUnavailableReason : undefined} onClick={() => setTaskCreateOpen(true)}>{t('pages.tasks.newTask')}</Button>
                </div>
                {!canCreateTask ? <Alert variant="warning" className="mt-4">{createTaskUnavailableReason}</Alert> : null}
              </CardBody></Card>

              <Tabs value={tab} onValueChange={(value) => setRouteState({ tab: value })}>
                <TabsList className="flex w-full overflow-x-auto"><TabsTrigger value="overview">Overview</TabsTrigger><TabsTrigger value="tasks">Tasks</TabsTrigger><TabsTrigger value="workspaces">Workspaces</TabsTrigger><TabsTrigger value="context">Context</TabsTrigger><TabsTrigger value="settings">Settings</TabsTrigger></TabsList>
                <TabsContent value="overview"><Card><CardBody className="grid gap-4 p-5 sm:grid-cols-2 xl:grid-cols-4"><Metric label="Active Tasks" value={selectedProject.active_task_count} /><Metric label="Running Tasks" value={selectedProject.running_task_count} /><Metric label="Workspaces" value={selectedProject.workspace_count} /><Metric label="Executable" value={selectedProject.executable_workspace_count} /><div className="sm:col-span-2 xl:col-span-4"><p className="text-sm font-medium text-[var(--osci-color-text)]">Attention</p><p className="mt-1 text-sm text-[var(--osci-color-text-secondary)]">{attentionReasonLabels.join(' ') || 'No action required.'}</p></div></CardBody></Card></TabsContent>
                <TabsContent value="tasks">
                  <ViewToolbar><div className="flex gap-2"><Button size="sm" variant={view === 'list' ? 'primary' : 'secondary'} onClick={() => setRouteState({ view: 'list' })}>List</Button><Button size="sm" variant={view === 'graph' ? 'primary' : 'secondary'} onClick={() => setRouteState({ view: 'graph' })}>Relationship graph</Button></div></ViewToolbar>
                  {view === 'graph' ? <div className="mt-3 h-[620px] overflow-hidden rounded-[var(--osci-radius-lg)] border border-[var(--osci-color-border-subtle)] bg-[var(--osci-color-surface)]"><ProjectCanvas key={`${projectId}:${layoutVersion}`} projectId={projectId!} tasks={tasks} edges={edges} projects={eligibleTargetProjects.map(asCanvasProject)} onNodeClick={(taskId) => navigate(`/tasks?task=${encodeURIComponent(taskId)}`)} onNewTask={() => setTaskCreateOpen(true)} onResetLayout={() => { localStorage.removeItem(`openscience:project-layout:${projectId}`); setLayoutVersion((value) => value + 1); }} onMoveTaskToProject={(taskId, targetProjectId) => { void moveTaskToProject(taskId, targetProjectId); }} canCreateTask={canCreateTask} canEditRelationships={selectedProject.status === 'active' && selectedProject.permissions.can_edit} canMoveTask={canMoveTask} /></div> : <Card className="mt-3"><CardBody className="divide-y divide-[var(--osci-color-border-subtle)] p-0">{tasks.map((task) => <button key={task.task_id} type="button" onClick={() => navigate(`/tasks?task=${encodeURIComponent(task.task_id)}`)} className="flex w-full items-center justify-between gap-3 p-4 text-left hover:bg-[var(--osci-color-surface-subtle)]"><div><p className="font-medium text-[var(--osci-color-text)]">{task.title}</p><p className="text-xs text-[var(--osci-color-text-muted)]">{task.task_id}</p></div><StatusBadge tone={task.status === 'running' ? 'success' : task.status === 'failed' ? 'danger' : 'neutral'}>{task.status}</StatusBadge></button>)}{tasks.length === 0 ? <EmptyState message="No Tasks in this Project." /> : null}</CardBody></Card>}
                </TabsContent>
                <TabsContent value="workspaces"><Card><CardBody className="space-y-4 p-5">
                  {selectedProject.permissions.can_edit ? <form className="flex flex-wrap gap-2" onSubmit={(event) => { event.preventDefault(); attachMutation.mutate(); }}><NativeSelect aria-label="Workspace to attach" value={attachWorkspaceId} onChange={(event) => setAttachWorkspaceId(event.target.value)} className="min-w-64"><option value="">Select a Workspace to attach</option>{attachableWorkspaces.map((workspace) => <option key={workspace.workspace_id} value={workspace.workspace_id}>{workspace.label}</option>)}</NativeSelect><Button type="submit" disabled={!attachWorkspaceId} isLoading={attachMutation.isPending}>Attach</Button></form> : null}
                  <div className="space-y-2">{linkedWorkspaces.map((workspace) => { const link = workspaceLink(workspace, selectedProject.project_id)!; return <div key={workspace.workspace_id} className="flex flex-wrap items-center justify-between gap-3 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] p-3"><div><p className="font-medium text-[var(--osci-color-text)]">{workspace.label}</p><p className="text-xs text-[var(--osci-color-text-muted)]">{workspace.environment.display_name} · {workspace.canonical_path}</p><p className="mt-1 text-xs text-[var(--osci-color-text-secondary)]">{link.can_execute ? 'Executable for new Tasks' : `Linked but unavailable: ${projectionReasonLabel(locale, link.cannot_execute_reason)}`}</p></div><div className="flex gap-2">{link.is_primary ? <Badge>Primary</Badge> : <Button size="sm" variant="secondary" disabled={!selectedProject.permissions.can_edit} onClick={() => primaryMutation.mutate(workspace.workspace_id)}>Set Primary</Button>}<Button size="sm" variant="secondary" disabled={!selectedProject.permissions.can_edit || link.is_primary} title={link.is_primary ? 'Replace the Primary Workspace before detaching it.' : undefined} onClick={() => detachMutation.mutate(workspace.workspace_id)}>Detach</Button></div></div>; })}{linkedWorkspaces.length === 0 ? <EmptyState title="No linked Workspaces" message="Attach a Workspace before creating execution Tasks." /> : null}</div>
                </CardBody></Card></TabsContent>
                <TabsContent value="context"><ProjectContextConsole key={selectedProject.project_id} project={selectedProject} /></TabsContent>
                <TabsContent value="settings"><ProjectSettingsConsole key={selectedProject.project_id} project={selectedProject} /></TabsContent>
              </Tabs>
            </div>
          ) : null}
        </div>
      </div>

      <TaskCreateFlow isOpen={taskCreateOpen} source="project" lockedProjectId={projectId} onClose={() => setTaskCreateOpen(false)} onCreated={() => void queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks.byProject(projectId) })} />
      <Dialog isOpen={createProjectOpen} onClose={() => setCreateProjectOpen(false)} title={t('pages.projects.createTitle')} size="md"><form className="space-y-4" onSubmit={(event) => { event.preventDefault(); createMutation.mutate(); }}><FormField label={t('pages.projects.createNameLabel')}><Input aria-label={t('pages.projects.createNameLabel')} required value={projectName} onChange={(event) => setProjectName(event.target.value)} /></FormField><FormField label={t('pages.projects.createDescriptionLabel')}><Textarea aria-label={t('pages.projects.createDescriptionLabel')} value={projectDescription} onChange={(event) => setProjectDescription(event.target.value)} /></FormField><div className="flex justify-end gap-2"><Button type="button" variant="secondary" onClick={() => setCreateProjectOpen(false)}>{t('common.cancel')}</Button><Button type="submit" isLoading={createMutation.isPending}>{t('pages.projects.createSubmit')}</Button></div></form></Dialog>
    </PageShell>
  );
}

function Metric({ label, value }: { label: string; value: number }) {
  return <div className="rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-4"><p className="text-xs font-medium uppercase tracking-wide text-[var(--osci-color-text-muted)]">{label}</p><p className="mt-2 text-2xl font-semibold text-[var(--osci-color-text)]">{value}</p></div>;
}
