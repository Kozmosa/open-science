import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Dialog, FormField, Input, PageShell, SplitPane, Textarea } from '@design-system';
import { ProjectCanvas, ProjectSidebar } from '../components/project';
import { useT } from '@/shared/i18n';
import {
  createProject,
  createTask,
  getEnvironments,
  getProject,
  getProjects,
  getSkills,
  getProjectTasks,
  getTask,
  getTaskEdges,
  getWorkspaces,
  updateTaskProject,
} from '@/shared/api';
import { extractErrorMessage } from '@/shared/utils/error';
import type { ProjectCreateRequest, TaskCreatePayload, TaskRecord } from '@/shared/types';
import TaskCreateForm from '@features/tasks/components/TaskCreateForm';
import TaskDetailPage from '@features/tasks/pages/TaskDetailPage';
import { useTaskStream } from '@features/tasks/hooks/useTaskStream';
import { queryKeys } from '@/shared/api/queryKeys';
import { useTaskConfiguration } from '@features/settings/contexts/TaskConfigurationContext';


export default function ProjectsPage() {
  const t = useT();
  const queryClient = useQueryClient();
  const { taskConfiguration } = useTaskConfiguration();

  const projectsQuery = useQuery({ queryKey: queryKeys.projects.all, queryFn: getProjects });

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [isCreateProjectOpen, setCreateProjectOpen] = useState(false);
  const [projectName, setProjectName] = useState('');
  const [projectDescription, setProjectDescription] = useState('');

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);
  const effectiveProjectId = selectedProjectId ?? projects[0]?.project_id ?? null;

  const tasksQuery = useQuery({
    queryKey: queryKeys.projectTasks.byProject(effectiveProjectId),
    queryFn: () =>
      effectiveProjectId
        ? getProjectTasks(effectiveProjectId, { limit: 500 })
        : Promise.resolve({ items: [], has_more: false, next_cursor: null }),
    enabled: effectiveProjectId !== null,
  });

  const edgesQuery = useQuery({
    queryKey: queryKeys.taskEdges.byProject(effectiveProjectId),
    queryFn: () =>
      effectiveProjectId ? getTaskEdges(effectiveProjectId) : Promise.resolve({ items: [] }),
    enabled: effectiveProjectId !== null,
  });

  const tasks = useMemo(
    () => tasksQuery.data?.items ?? [],
    [tasksQuery.data],
  );
  const edges = useMemo(() => edgesQuery.data?.items ?? [], [edgesQuery.data]);

  const selectedTaskQuery = useQuery({
    queryKey: queryKeys.tasks.detail(selectedTaskId),
    queryFn: () => getTask(selectedTaskId ?? ''),
    enabled: selectedTaskId !== null,
  });
  const selectedTask: TaskRecord | null = selectedTaskQuery.data ?? null;
  const { outputItems, outputError, hasMore, loadMore, isLoadingMore } = useTaskStream(selectedTaskId);

  // Fetch defaults for task creation
  const projectDetailQuery = useQuery({
    queryKey: queryKeys.projects.detail(effectiveProjectId),
    queryFn: () => getProject(effectiveProjectId ?? ''),
    enabled: effectiveProjectId !== null,
  });
  const workspacesQuery = useQuery({
    queryKey: queryKeys.workspaces.all,
    queryFn: getWorkspaces,
  });
  const environmentsQuery = useQuery({
    queryKey: queryKeys.environments.all,
    queryFn: getEnvironments,
  });
  const skillsQuery = useQuery({
    queryKey: queryKeys.skills.all,
    queryFn: getSkills,
  });


  const projectDetail = projectDetailQuery.data ?? null;
  const defaultWorkspaceId =
    projectDetail?.default_workspace_id ?? workspacesQuery.data?.items[0]?.workspace_id ?? '';
  const defaultEnvironmentId =
    projectDetail?.default_environment_id ?? environmentsQuery.data?.items[0]?.id ?? '';
  const availableProjects = projects;
  const availableWorkspaces = workspacesQuery.data?.items ?? [];

  const selectedResearchAgentProfile = useMemo(() => {
    const profileId = taskConfiguration.defaultResearchAgentProfileId;
    if (!profileId) return null;
    return taskConfiguration.researchAgentProfiles.find(p => p.profileId === profileId) ?? null;
  }, [taskConfiguration.defaultResearchAgentProfileId, taskConfiguration.researchAgentProfiles]);
  const availableEnvironments = environmentsQuery.data?.items ?? [];
  const handleResetLayout = useCallback(() => {
    if (effectiveProjectId) {
      localStorage.removeItem(`ainrf:project-layout:${effectiveProjectId}`);
      setLayoutVersion((v) => v + 1);
    }
  }, [effectiveProjectId]);

  const handleCreateProject = useCallback(() => {
    setProjectName('');
    setProjectDescription('');
    setCreateProjectOpen(true);
  }, []);

  const createProjectMutation = useMutation({
    mutationFn: (payload: ProjectCreateRequest) => createProject(payload),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all });
      setSelectedProjectId(created.project_id);
      setCreateProjectOpen(false);
    },
  });

  const handleCreateProjectSubmit = useCallback(() => {
    const name = projectName.trim();
    if (!name || createProjectMutation.isPending) return;
    createProjectMutation.mutate({ name, description: projectDescription.trim() || null });
  }, [projectName, projectDescription, createProjectMutation]);

  const handleNodeClick = useCallback((taskId: string) => {
    setSelectedTaskId(taskId);
  }, []);

  const closeCreateDialog = useCallback(() => {
    setCreateDialogOpen(false);
  }, []);

  const createMutation = useMutation({
    mutationFn: (payload: TaskCreatePayload) => createTask(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks.byProject(effectiveProjectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.taskEdges.byProject(effectiveProjectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tasks.all });
      closeCreateDialog();
    },
  });

  const handleMoveTaskToProject = useCallback(
    async (taskId: string, targetProjectId: string) => {
      await updateTaskProject(taskId, targetProjectId);
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks.byProject(effectiveProjectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projectTasks.byProject(targetProjectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.taskEdges.byProject(effectiveProjectId) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.taskEdges.byProject(targetProjectId) });
    },
    [effectiveProjectId, queryClient]
  );

  return (
    <>
      <PageShell>
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
            projects={projects}
            onNodeClick={handleNodeClick}
            onNewTask={() => setCreateDialogOpen(true)}
            onResetLayout={handleResetLayout}
            onMoveTaskToProject={handleMoveTaskToProject}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-sm text-[var(--text-secondary)]">
            {t('pages.projects.noProjects')}
          </div>
        )}
      </SplitPane>
      </PageShell>

      <Dialog
        isOpen={selectedTaskId !== null}
        onClose={() => setSelectedTaskId(null)}
        title={selectedTask?.title ?? null}
        size="lg"
      >
        {selectedTask ? (
          <TaskDetailPage
            key={selectedTaskId ?? 'none'}
            taskId={selectedTaskId}
            selectedTask={selectedTask}
            detailError={extractErrorMessage(selectedTaskQuery.error)}
            outputItems={outputItems}
            outputError={outputError}
            hasMore={hasMore}
            loadMore={loadMore}
            isLoadingMore={isLoadingMore}
          />
        ) : null}
      </Dialog>

      <Dialog
        isOpen={isCreateDialogOpen}
        onClose={closeCreateDialog}
        title={null}
        ariaLabel={t('pages.tasks.createTitle')}
        size="lg"
      >
        <TaskCreateForm
          projectId={effectiveProjectId ?? ''}
          workspaceId={defaultWorkspaceId}
          environmentId={defaultEnvironmentId}
          availableProjects={availableProjects}
          availableWorkspaces={availableWorkspaces}
          availableEnvironments={availableEnvironments}
          availableSkills={skillsQuery.data?.items ?? []}
          lockProject
          researchAgentProfile={selectedResearchAgentProfile}
          onSubmit={(payload) => createMutation.mutate(payload)}
          onCancel={closeCreateDialog}
        />
      </Dialog>
      <Dialog
        isOpen={isCreateProjectOpen}
        onClose={() => setCreateProjectOpen(false)}
        title={t('pages.projects.createTitle')}
        ariaLabel={t('pages.projects.createTitle')}
        size="md"
      >
        <div className="space-y-4">
          <FormField label={t('pages.projects.createNameLabel')}>
            <Input
              value={projectName}
              onChange={(e) => setProjectName(e.target.value)}
              placeholder={t('pages.projects.createNameLabel')}
              autoFocus
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreateProjectSubmit();
              }}
            />
          </FormField>
          <FormField label={t('pages.projects.createDescriptionLabel')}>
            <Textarea
              value={projectDescription}
              onChange={(e) => setProjectDescription(e.target.value)}
              rows={3}
            />
          </FormField>
          {createProjectMutation.isError ? (
            <p className="text-xs text-[var(--danger)]">
              {extractErrorMessage(createProjectMutation.error)}
            </p>
          ) : null}
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCreateProjectOpen(false)}>
              {t('common.cancel')}
            </Button>
            <Button
              onClick={handleCreateProjectSubmit}
              disabled={!projectName.trim() || createProjectMutation.isPending}
              isLoading={createProjectMutation.isPending}
            >
              {t('pages.projects.createSubmit')}
            </Button>
          </div>
        </div>
      </Dialog>
    </>
  );
}
