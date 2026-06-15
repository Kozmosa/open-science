import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getProjects, getTasks } from '@/shared/api';
import PageShell from '@design-system/layout/PageShell';
import SectionStack from '@design-system/layout/SectionStack';
import { GanttChart } from './timeline/GanttChart';
import { TimelineControls } from './timeline/TimelineControls';
import type { TaskSummary } from '@/shared/types';
import { queryKeys } from '@/shared/api/queryKeys';

function taskStartTime(task: TaskSummary): number {
  return new Date(task.started_at ?? task.created_at).getTime();
}

function dateStart(value: string): number | null {
  return value ? new Date(`${value}T00:00:00`).getTime() : null;
}

function dateEnd(value: string): number | null {
  return value ? new Date(`${value}T23:59:59.999`).getTime() : null;
}

export default function TimelinePage() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');

  const tasksQuery = useQuery({
    queryKey: queryKeys.timeline.taskRuns,
    queryFn: () => getTasks({ includeArchived: false, limit: 1000, sort: 'created' }),
    refetchInterval: 15000,
  });

  const allTasks = useMemo(
    () => tasksQuery.data?.items ?? [],
    [tasksQuery.data],
  );

  const tasks = useMemo(() => {
    const min = dateStart(fromDate);
    const max = dateEnd(toDate);
    return allTasks.filter((task) => {
      if (projectId !== null && task.project_id !== projectId) {
        return false;
      }
      const start = taskStartTime(task);
      if (min !== null && start < min) {
        return false;
      }
      if (max !== null && start > max) {
        return false;
      }
      return true;
    });
  }, [allTasks, fromDate, projectId, toDate]);

  const projectsQuery = useQuery({
    queryKey: queryKeys.projects.all,
    queryFn: () => getProjects(),
  });

  return (
    <PageShell>
      <SectionStack gap={4} className="flex min-h-0 flex-1 flex-col">
        <TimelineControls
          projectId={projectId}
          onProjectChange={setProjectId}
          fromDate={fromDate}
          toDate={toDate}
          onFromDateChange={setFromDate}
          onToDateChange={setToDate}
          tasks={tasks}
          projects={projectsQuery.data?.items ?? []}
        />
        <GanttChart tasks={tasks} loading={tasksQuery.isLoading} />
      </SectionStack>
    </PageShell>
  );
}
