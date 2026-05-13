import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Modal } from '../components/ui';
import { ProjectCanvas, ProjectSidebar } from '../components/project';
import { useEnvironmentSelection } from '../components';
import { useT } from '../i18n';
import { SplitPane } from '../components/layout';
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
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);

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
      <SplitPane
        sidebar={
          <ProjectSidebar
            projects={projects}
            selectedProjectId={effectiveProjectId}
            onSelectProject={setSelectedProjectId}
            onCreateProject={handleCreateProject}
          />
        }
        sidebarWidth={sidebarWidth}
        onSidebarWidthChange={setSidebarWidth}
      >
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
      </SplitPane>

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
