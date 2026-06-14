import { useCallback, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getTask, getTasks } from '@/shared/api';
import PageShell from '@design-system/layout/PageShell';
import SplitPane from '@design-system/layout/SplitPane';
import { SessionDetail } from './sessions/SessionDetail';
import { SessionList } from './sessions/SessionList';

export default function SessionsPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);

  const tasksQuery = useQuery({
    queryKey: ['session-task-runs'],
    queryFn: () => getTasks({ includeArchived: false, limit: 200, sort: 'updated' }),
    refetchInterval: 10000,
  });

  const tasks = useMemo(
    () => tasksQuery.data?.items ?? [],
    [tasksQuery.data],
  );

  const detailQuery = useQuery({
    queryKey: ['task', selectedId],
    queryFn: () => getTask(selectedId!),
    enabled: selectedId !== null,
  });

  const handleSelect = useCallback(
    (id: string) => {
      setSelectedId(id);
      queryClient.invalidateQueries({ queryKey: ['task', id] });
    },
    [queryClient],
  );

  return (
    <PageShell>
      <SplitPane
        sidebar={
          <SessionList
            tasks={tasks}
            selectedId={selectedId}
            onSelect={handleSelect}
            loading={tasksQuery.isLoading}
          />
        }
        sidebarWidth={sidebarWidth}
        onSidebarWidthChange={setSidebarWidth}
      >
        <SessionDetail
          detail={detailQuery.data ?? null}
          loading={detailQuery.isLoading}
          selectedId={selectedId}
        />
      </SplitPane>
    </PageShell>
  );
}
