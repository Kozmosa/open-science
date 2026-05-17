import { useCallback, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { getSession, getSessions } from '../api';
import PageShell from '../components/layout/PageShell';
import SplitPane from '../components/layout/SplitPane';
import { SessionDetail } from './sessions/SessionDetail';
import { SessionList } from './sessions/SessionList';

export default function SessionsPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [sidebarWidth, setSidebarWidth] = useState(320);

  const sessionsQuery = useQuery({
    queryKey: ['sessions'],
    queryFn: () => getSessions(),
    refetchInterval: 10000,
  });

  const sessions = useMemo(
    () => sessionsQuery.data?.items ?? [],
    [sessionsQuery.data],
  );

  const detailQuery = useQuery({
    queryKey: ['session', selectedId],
    queryFn: () => getSession(selectedId!),
    enabled: selectedId !== null,
  });

  const handleSelect = useCallback(
    (id: string) => {
      setSelectedId(id);
      queryClient.invalidateQueries({ queryKey: ['session', id] });
    },
    [queryClient],
  );

  return (
    <PageShell>
      <SplitPane
        sidebar={
          <SessionList
            sessions={sessions}
            selectedId={selectedId}
            onSelect={handleSelect}
            loading={sessionsQuery.isLoading}
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
