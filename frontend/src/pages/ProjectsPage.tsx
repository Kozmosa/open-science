import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Modal } from '../components/ui';
import { ProjectCanvas, ProjectSidebar } from '../components/project';
import { useEnvironmentSelection } from '../components';
import { useT } from '../i18n';
import {
  createTask,
  getEnvironments,
  getProjects,
  getProjectTasks,
  getSkills,
  getTask,
  getTaskEdges,
  getWorkspaces,
} from '../api';
import { useSettings, createEmptyEnvironmentTaskDefaults } from '../settings';
import { extractErrorMessage } from '../utils/error';
import type { TaskCreateRequest, TaskRecord } from '../types';
import TaskCreateForm from './tasks/TaskCreateForm';
import TaskDetail from './tasks/TaskDetail';

const sidebarMinWidth = 260;
const sidebarMaxWidth = 520;
const sidebarDefaultWidth = 320;

export default function ProjectsPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const { settings } = useSettings();
  const environmentSelection = useEnvironmentSelection();

  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: getProjects });
  const workspacesQuery = useQuery({ queryKey: ['workspaces'], queryFn: getWorkspaces });
  const environmentsQuery = useQuery({ queryKey: ['environments'], queryFn: getEnvironments });
  const skillsQuery = useQuery({ queryKey: ['skills'], queryFn: getSkills });

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(sidebarDefaultWidth);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const isResizing = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(sidebarDefaultWidth);

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);
  const workspaces = useMemo(() => workspacesQuery.data?.items ?? [], [workspacesQuery.data]);
  const environments = useMemo(
    () => environmentsQuery.data?.items ?? [],
    [environmentsQuery.data]
  );
  const availableSkills = useMemo(() => skillsQuery.data?.items ?? [], [skillsQuery.data]);
  const effectiveProjectId = selectedProjectId ?? projects[0]?.project_id ?? null;

  const tasksQuery = useQuery({
    queryKey: ['project-tasks', effectiveProjectId],
    queryFn: () =>
      effectiveProjectId ? getProjectTasks(effectiveProjectId) : Promise.resolve({ items: [] }),
    enabled: effectiveProjectId !== null,
  });

  const edgesQuery = useQuery({
    queryKey: ['task-edges', effectiveProjectId],
    queryFn: () =>
      effectiveProjectId ? getTaskEdges(effectiveProjectId) : Promise.resolve({ items: [] }),
    enabled: effectiveProjectId !== null,
  });

  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const edges = useMemo(() => edgesQuery.data?.items ?? [], [edgesQuery.data]);

  const selectedTaskQuery = useQuery({
    queryKey: ['task', selectedTaskId],
    queryFn: () => getTask(selectedTaskId ?? ''),
    enabled: selectedTaskId !== null,
  });

  const selectedTask: TaskRecord | null = selectedTaskQuery.data ?? null;

  const handleResizeStart = useCallback((event: React.MouseEvent) => {
    isResizing.current = true;
    startX.current = event.clientX;
    startWidth.current = sidebarWidth;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  }, [sidebarWidth]);

  useEffect(() => {
    function handleMouseMove(event: MouseEvent) {
      if (!isResizing.current) return;
      const delta = event.clientX - startX.current;
      const newWidth = Math.min(
        sidebarMaxWidth,
        Math.max(sidebarMinWidth, startWidth.current + delta)
      );
      setSidebarWidth(newWidth);
    }
    function handleMouseUp() {
      if (!isResizing.current) return;
      isResizing.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    }
    document.addEventListener('mousemove', handleMouseMove);
    document.addEventListener('mouseup', handleMouseUp);
    return () => {
      document.removeEventListener('mousemove', handleMouseMove);
      document.removeEventListener('mouseup', handleMouseUp);
    };
  }, []);

  const handleResetLayout = useCallback(() => {
    if (effectiveProjectId) {
      localStorage.removeItem(`ainrf:project-layout:${effectiveProjectId}`);
      setLayoutVersion((v) => v + 1);
    }
  }, [effectiveProjectId]);

  const handleCreateProject = useCallback(() => {
    // TODO: open create project modal
  }, []);

  const handleNodeClick = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
  }, []);

  const closeCreateDialog = useCallback(() => {
    setCreateDialogOpen(false);
  }, []);

  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string>(
    settings.projectDefaults.default?.defaultWorkspaceId ?? ''
  );
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState<string>(
    environmentSelection.selectedEnvironmentId ?? ''
  );
  const [draftResetVersion, setDraftResetVersion] = useState(0);

  const effectiveWorkspaceId = selectedWorkspaceId || workspaces[0]?.workspace_id || '';
  const effectiveEnvironmentId = selectedEnvironmentId || environments[0]?.id || '';
  const selectedWorkspace =
    workspaces.find((w) => w.workspace_id === effectiveWorkspaceId) ?? null;
  const selectedEnvironment =
    environments.find((e) => e.id === effectiveEnvironmentId) ?? null;

  const draftDefaults = useMemo(() => {
    const environmentDefaults =
      (effectiveEnvironmentId
        ? settings.projectDefaults.default?.environmentDefaults?.[effectiveEnvironmentId]
        : null) ?? createEmptyEnvironmentTaskDefaults();
    return {
      title: environmentDefaults.titleTemplate,
      task_input: environmentDefaults.taskInputTemplate,
      researchAgentProfileId: environmentDefaults.researchAgentProfileId,
      taskConfigurationId: environmentDefaults.taskConfigurationId,
    };
  }, [effectiveEnvironmentId, settings.projectDefaults.default?.environmentDefaults]);

  const createMutation = useMutation({
    mutationFn: (payload: TaskCreateRequest) => createTask(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['project-tasks', effectiveProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['task-edges', effectiveProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
      closeCreateDialog();
      setDraftResetVersion((v) => v + 1);
    },
  });

  const createError = extractErrorMessage(createMutation.error);

  return (
    <div className="flex min-h-0 flex-1 bg-[var(--bg)] p-3">
      <div className="flex min-h-0 w-full overflow-hidden rounded-2xl border border-[var(--border)] bg-[var(--surface)] shadow-sm">
        <aside
          className="flex shrink-0 flex-col bg-[var(--sidebar)] p-3"
          style={{ width: sidebarWidth }}
        >
          <ProjectSidebar
            projects={projects}
            selectedProjectId={effectiveProjectId}
            onSelectProject={setSelectedProjectId}
            onCreateProject={handleCreateProject}
          />
        </aside>

        <div
          role="separator"
          aria-orientation="vertical"
          tabIndex={0}
          onMouseDown={handleResizeStart}
          className="group flex w-2 shrink-0 cursor-col-resize items-stretch justify-center bg-[var(--surface)]"
        >
          <span className="my-3 w-px rounded-full bg-[var(--border)]" />
        </div>

        <main className="flex min-w-0 flex-1 flex-col bg-[var(--bg)]">
          {effectiveProjectId ? (
            <ProjectCanvas
              key={`${effectiveProjectId}:${layoutVersion}`}
              projectId={effectiveProjectId}
              tasks={tasks}
              edges={edges}
              onNodeClick={handleNodeClick}
              onNewTask={() => setCreateDialogOpen(true)}
              onResetLayout={handleResetLayout}
            />
          ) : (
            <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
              {t('pages.projects.noProjects')}
            </div>
          )}
        </main>
      </div>

      <Modal
        isOpen={selectedTaskId !== null}
        onClose={() => setSelectedTaskId(null)}
        title={selectedTask?.title ?? null}
        size="lg"
      >
        {selectedTask ? (
          <TaskDetail
            selectedTask={selectedTask}
            detailError={extractErrorMessage(selectedTaskQuery.error)}
            outputItems={[]}
            outputError={null}
          />
        ) : null}
      </Modal>

      <Modal
        isOpen={isCreateDialogOpen}
        onClose={closeCreateDialog}
        title={null}
        ariaLabel={t('pages.tasks.createTitle')}
        size="lg"
      >
        <TaskCreateForm
          key={`${effectiveEnvironmentId}:${draftResetVersion}`}
          workspaces={workspaces}
          environments={environments}
          projects={projects}
          selectedWorkspaceId={effectiveWorkspaceId}
          selectedEnvironmentId={effectiveEnvironmentId}
          selectedProjectId={effectiveProjectId ?? undefined}
          selectedWorkspace={selectedWorkspace}
          selectedEnvironment={selectedEnvironment}
          draftDefaults={draftDefaults}
          researchAgentProfiles={settings.taskConfiguration.researchAgentProfiles}
          taskConfigurations={settings.taskConfiguration.taskConfigurations}
          availableSkills={availableSkills}
          isSubmitting={createMutation.isPending}
          createError={createError}
          onSelectWorkspace={setSelectedWorkspaceId}
          onSelectEnvironment={setSelectedEnvironmentId}
          onSelectProject={(projectId) => setSelectedProjectId(projectId)}
          onSubmit={(payload) => createMutation.mutate(payload)}
          onClose={closeCreateDialog}
        />
      </Modal>
    </div>
  );
}
