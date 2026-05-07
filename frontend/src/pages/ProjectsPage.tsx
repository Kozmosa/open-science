import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Modal } from '../components/ui';
import { ProjectCanvas, ProjectSidebar } from '../components/project';
import { useT } from '../i18n';
import { getProjects, getProjectTasks, getTaskEdges } from '../api';
import type { TaskRecord } from '../types';
import TaskDetail from './tasks/TaskDetail';

const sidebarMinWidth = 260;
const sidebarMaxWidth = 520;
const sidebarDefaultWidth = 320;

export default function ProjectsPage() {
  const t = useT();
  const projectsQuery = useQuery({ queryKey: ['projects'], queryFn: getProjects });
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(sidebarDefaultWidth);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [, setCreateDialogOpen] = useState(false);
  const isResizing = useRef(false);
  const startX = useRef(0);
  const startWidth = useRef(sidebarDefaultWidth);

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
      const newWidth = Math.min(sidebarMaxWidth, Math.max(sidebarMinWidth, startWidth.current + delta));
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

  const projects = useMemo(() => projectsQuery.data?.items ?? [], [projectsQuery.data]);
  const effectiveProjectId = selectedProjectId ?? projects[0]?.project_id ?? null;

  const tasksQuery = useQuery({
    queryKey: ['project-tasks', effectiveProjectId],
    queryFn: () => (effectiveProjectId ? getProjectTasks(effectiveProjectId) : Promise.resolve({ items: [] })),
    enabled: effectiveProjectId !== null,
  });

  const edgesQuery = useQuery({
    queryKey: ['task-edges', effectiveProjectId],
    queryFn: () => (effectiveProjectId ? getTaskEdges(effectiveProjectId) : Promise.resolve({ items: [] })),
    enabled: effectiveProjectId !== null,
  });

  const tasks = useMemo(() => tasksQuery.data?.items ?? [], [tasksQuery.data]);
  const edges = useMemo(() => edgesQuery.data?.items ?? [], [edgesQuery.data]);

  const handleResetLayout = useCallback(() => {
    if (effectiveProjectId) {
      edgesQuery.refetch();
    }
  }, [effectiveProjectId, edgesQuery]);

  const handleCreateProject = useCallback(() => {
    // TODO: open create project modal
  }, []);

  const selectedTask = useMemo(
    () => tasks.find((t) => t.task_id === selectedTaskId) ?? null,
    [tasks, selectedTaskId]
  );

  return (
    <div className="flex min-h-0 flex-1 bg-[var(--bg)] p-4">
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
              projectId={effectiveProjectId}
              tasks={tasks}
              edges={edges}
              onNodeClick={setSelectedTaskId}
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
            selectedTask={selectedTask as TaskRecord}
            detailError={null}
            outputItems={[]}
            outputError={null}
          />
        ) : null}
      </Modal>
    </div>
  );
}
