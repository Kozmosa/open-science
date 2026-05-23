import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { getProjects, getSessions, getSessionsBatchDetail } from '../api';
import PageShell from '../components/layout/PageShell';
import SectionStack from '../components/layout/SectionStack';
import { GanttChart } from './timeline/GanttChart';
import { TimelineControls } from './timeline/TimelineControls';

export default function TimelinePage() {
  // Will be wired in Task 2+3
  const [projectId, setProjectId] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');

  const sessionsQuery = useQuery({
    queryKey: ['sessions', projectId],
    queryFn: () => getSessions({ projectId: projectId ?? undefined }),
    refetchInterval: 15000,
  });

  const sessions = useMemo(
    () => sessionsQuery.data?.items ?? [],
    [sessionsQuery.data],
  );

  const detailQuery = useQuery({
    queryKey: ['session-batch-detail', sessions.map((s) => s.id)],
    queryFn: () => getSessionsBatchDetail(sessions.map((s) => s.id)),
    enabled: sessions.length > 0,
    refetchInterval: 30000,
  });

  const details = useMemo(() => detailQuery.data?.items ?? {}, [detailQuery.data]);

  const projectsQuery = useQuery({
    queryKey: ['projects'],
    queryFn: () => getProjects(),
  });

  return (
    <PageShell>
      <SectionStack gap={4}>
        <TimelineControls
          projectId={projectId}
          onProjectChange={setProjectId}
          fromDate={fromDate}
          toDate={toDate}
          onFromDateChange={setFromDate}
          onToDateChange={setToDate}
          sessions={sessions}
          projects={projectsQuery.data?.items ?? []}
        />
        <GanttChart sessions={sessions} details={details} loading={sessionsQuery.isLoading} />
      </SectionStack>
    </PageShell>
  );
}
