import { useMemo, useState } from 'react';
import { useQueries, useQuery } from '@tanstack/react-query';
import { getProjects, getSession, getSessions } from '../api';
import PageShell from '../components/layout/PageShell';
import SectionStack from '../components/layout/SectionStack';
import type { SessionDetailRecord } from '../types';
import { GanttChart } from './timeline/GanttChart';
import { TimelineControls } from './timeline/TimelineControls';

export default function TimelinePage() {
  // Will be wired in Task 2+3
  const [projectId, setProjectId] = useState<string | null>(null);
  const [fromDate, setFromDate] = useState<string>('');
  const [toDate, setToDate] = useState<string>('');

  const sessionsQuery = useQuery({
    queryKey: ['sessions', projectId],
    queryFn: () => getSessions(projectId ?? undefined),
    refetchInterval: 15000,
  });

  const sessions = useMemo(
    () => sessionsQuery.data?.items ?? [],
    [sessionsQuery.data],
  );

  const sessionDetails = useQueries({
    queries: sessions.map((s) => ({
      queryKey: ['session', s.id],
      queryFn: () => getSession(s.id),
      enabled: sessions.length > 0,
      refetchInterval: 30000,
    })),
  });

  const details = useMemo(
    () =>
      sessionDetails
        .map((q) => q.data)
        .filter(Boolean) as SessionDetailRecord[],
    [sessionDetails],
  );

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
