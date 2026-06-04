import { useCallback, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Modal } from '../components/ui';
import { ProjectCanvas, ProjectSidebar } from '../components/project';
import { useT } from '../i18n';
import { PageShell, SplitPane } from '../components/layout';
import {
  createTask,
  getEnvironments,
  getProject,
  getProjects,
  getSkills,
  getProjectTasks,
  getTask,
  getTaskEdges,
  getWorkspaces,
} from '../api';
import { extractErrorMessage } from '../utils/error';
import type { TaskCreatePayload, TaskRecord } from '../types';
import TaskCreateForm from './tasks/TaskCreateForm';
import TaskDetail from './tasks/TaskDetail';


export default function ProjectsPage() {
  const t = useT();
  const queryClient = useQueryClient();

  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: getProjects });

  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [isCreateDialogOpen, setCreateDialogOpen] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);
  const effectiveProjectId = selectedProjectId ?? projects[0]?.project_id ?? null;

  const tasksQuery = useQuery({
    queryKey: ['project-tasks', effectiveProjectId],
    queryFn: () =>
      effectiveProjectId
        ? getProjectTasks(effectiveProjectId, { limit: 500 })
        : Promise.resolve({ items: [], has_more: false, next_cursor: null }),
    enabled: effectiveProjectId !== null,
  });

  const edgesQuery = useQuery({
    queryKey: ['task-edges', effectiveProjectId],
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
    queryKey: ['task', selectedTaskId],
    queryFn: () => getTask(selectedTaskId ?? ''),
    enabled: selectedTaskId !== null,
  });
  const selectedTask: TaskRecord | null = selectedTaskQuery.data ?? null;

  // Fetch defaults for task creation
  const projectDetailQuery = useQuery({
    queryKey: ['project', effectiveProjectId],
    queryFn: () => getProject(effectiveProjectId ?? ''),
    enabled: effectiveProjectId !== null,
  });
  const workspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: getWorkspaces,
  });
  const environmentsQuery = useQuery({
    queryKey: ['environments'],
    queryFn: getEnvironments,
  });
  const skillsQuery = useQuery({
    queryKey: ['skills'],
    queryFn: getSkills,
  });


  const projectDetail = projectDetailQuery.data ?? null;
  const defaultWorkspaceId =
    projectDetail?.default_workspace_id ?? workspacesQuery.data?.items[0]?.workspace_id ?? '';
  const defaultEnvironmentId =
    projectDetail?.default_environment_id ?? environmentsQuery.data?.items[0]?.id ?? '';
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

  const createMutation = useMutation({
    mutationFn: (payload: TaskCreatePayload) => createTask(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['project-tasks', effectiveProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['task-edges', effectiveProjectId] });
      void queryClient.invalidateQueries({ queryKey: ['tasks'] });
      closeCreateDialog();
    },
  });

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
      </PageShell>

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
          projectId={effectiveProjectId ?? ''}
          workspaceId={defaultWorkspaceId}
          environmentId={defaultEnvironmentId}
          availableSkills={skillsQuery.data?.items ?? []}
          onSubmit={(payload) => createMutation.mutate(payload)}
          onCancel={closeCreateDialog}
        />
      </Modal>
    </>
  );
}
