import { useCallback, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getTask, getTasks, getTaskTurns } from '@features/tasks';
import { getProjectUsageSummary } from '@features/projects';
import { PageShell, SplitPane } from '@design-system';
import { RunDetail } from './runs/RunDetail';
import { RunList } from './runs/RunList';
import { queryKeys } from '@/shared/api/queryKeys';

export default function RunsPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);

  const tasksQuery = useQuery({
    queryKey: queryKeys.runs.taskRuns,
    queryFn: () => getTasks({ includeArchived: false, limit: 200, sort: 'updated' }),
    refetchInterval: 10000,
  });

  const tasks = useMemo(
    () => tasksQuery.data?.items ?? [],
    [tasksQuery.data],
  );

  const detailQuery = useQuery({
    queryKey: queryKeys.tasks.detail(selectedId),
    queryFn: () => getTask(selectedId!),
    enabled: selectedId !== null,
  });

  const turnsQuery = useQuery({
    queryKey: queryKeys.tasks.turns(selectedId),
    queryFn: () => getTaskTurns(selectedId!),
    enabled: selectedId !== null,
  });

  const projectId = detailQuery.data?.project_id ?? null;
  const usageQuery = useQuery({
    queryKey: queryKeys.domain.projectUsage(projectId),
    queryFn: () => getProjectUsageSummary(projectId!),
    enabled: projectId !== null,
  });

  const handleSelect = useCallback(
    (id: string) => {
      setSelectedId(id);
      queryClient.invalidateQueries({ queryKey: queryKeys.tasks.detail(id) });
    },
    [queryClient],
  );

  return (
    <PageShell>
      <SplitPane
        sidebar={
          <RunList
            tasks={tasks}
            selectedId={selectedId}
            onSelect={handleSelect}
            loading={tasksQuery.isLoading}
          />
        }
        sidebarWidth={sidebarWidth}
        onSidebarWidthChange={setSidebarWidth}
      >
        <RunDetail
          detail={detailQuery.data ?? null}
          turns={turnsQuery.data?.items ?? []}
          usage={usageQuery.data ?? null}
          loading={detailQuery.isLoading}
          selectedId={selectedId}
        />
      </SplitPane>
    </PageShell>
  );
}
