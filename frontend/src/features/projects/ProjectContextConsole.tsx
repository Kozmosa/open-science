import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Badge, Button, Card, CardBody, EmptyState, FormField, NativeSelect, Textarea } from '@design-system';
import {
  acceptDomainContextCandidate,
  getDomainProjectContext,
  getDomainProjectContextCandidates,
  getDomainProjectContextDiff,
  getDomainProjectContextVersions,
  publishDomainProjectContext,
  rejectDomainContextCandidate,
  saveDomainProjectContextDraft,
  type DomainProjectProjection,
} from '@features/domain';
import { createIdempotencyKey, useIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import { extractErrorMessage } from '@/shared/utils/error';

export default function ProjectContextConsole({ project }: { project: DomainProjectProjection }) {
  const queryClient = useQueryClient();
  const [draftOverride, setDraftOverride] = useState<string | null>(null);
  const [beforeVersionId, setBeforeVersionId] = useState('');
  const [afterVersionId, setAfterVersionId] = useState('');
  const contextQuery = useQuery({ queryKey: queryKeys.domain.projectContext(project.project_id), queryFn: () => getDomainProjectContext(project.project_id) });
  const versionsQuery = useQuery({ queryKey: queryKeys.domain.projectContextVersions(project.project_id), queryFn: () => getDomainProjectContextVersions(project.project_id) });
  const candidatesQuery = useQuery({ queryKey: queryKeys.domain.projectContextCandidates(project.project_id), queryFn: () => getDomainProjectContextCandidates(project.project_id) });
  const draftContent = draftOverride ?? contextQuery.data?.draft?.content ?? contextQuery.data?.active_version?.content ?? '';
  const draftKey = useIdempotencyKey('project.context.draft', { projectId: project.project_id, draftContent });
  const diffQuery = useQuery({
    queryKey: ['domain', 'projects', project.project_id, 'context', 'diff', beforeVersionId, afterVersionId],
    queryFn: () => getDomainProjectContextDiff(project.project_id, afterVersionId, beforeVersionId),
    enabled: Boolean(beforeVersionId && afterVersionId && beforeVersionId !== afterVersionId),
  });

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projectContext(project.project_id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projectContextVersions(project.project_id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projectContextCandidates(project.project_id) });
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(true) });
  };
  const saveMutation = useMutation({
    mutationFn: () => saveDomainProjectContextDraft(project.project_id, draftContent, draftKey.idempotencyKey),
    onSuccess: () => { draftKey.markSucceeded(); setDraftOverride(null); invalidate(); },
  });
  const publishMutation = useMutation({
    mutationFn: () => publishDomainProjectContext(project.project_id, createIdempotencyKey(`project.context.publish.${project.project_id}`)),
    onSuccess: invalidate,
  });
  const acceptMutation = useMutation({
    mutationFn: (candidateId: string) => acceptDomainContextCandidate(project.project_id, candidateId, createIdempotencyKey(`project.context.candidate.accept.${candidateId}`)),
    onSuccess: invalidate,
  });
  const rejectMutation = useMutation({
    mutationFn: (candidateId: string) => rejectDomainContextCandidate(project.project_id, candidateId, 'Rejected from Project Context console', createIdempotencyKey(`project.context.candidate.reject.${candidateId}`)),
    onSuccess: invalidate,
  });
  const error = contextQuery.error ?? versionsQuery.error ?? candidatesQuery.error ?? saveMutation.error ?? publishMutation.error ?? acceptMutation.error ?? rejectMutation.error;
  const versions = versionsQuery.data?.items ?? [];
  const candidates = candidatesQuery.data?.items ?? [];

  return <div className="space-y-4">
    {error ? <Alert variant="error">{extractErrorMessage(error)}</Alert> : null}
    <Card><CardBody className="space-y-4 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3"><div><h3 className="font-semibold text-[var(--osci-color-text)]">Draft</h3><p className="text-sm text-[var(--osci-color-text-secondary)]">Edit the next durable Project Context version.</p></div><div className="flex gap-2"><Button variant="secondary" disabled={!project.permissions.can_edit || !draftContent.trim()} isLoading={saveMutation.isPending} onClick={() => saveMutation.mutate()}>Save draft</Button><Button disabled={!project.permissions.can_publish || !contextQuery.data?.draft} isLoading={publishMutation.isPending} onClick={() => publishMutation.mutate()}>Publish</Button></div></div>
      <Textarea aria-label="Project Context draft" className="min-h-64 font-mono text-sm" value={draftContent} disabled={!project.permissions.can_edit} onChange={(event) => setDraftOverride(event.target.value)} />
      <p className="text-xs text-[var(--osci-color-text-muted)]">Draft fingerprint: {contextQuery.data?.draft?.fingerprint ?? 'unsaved'}</p>
    </CardBody></Card>
    <Card><CardBody className="space-y-4 p-5"><div><h3 className="font-semibold text-[var(--osci-color-text)]">Active Version</h3><p className="text-sm text-[var(--osci-color-text-secondary)]">Tasks pin this immutable version when they are created or moved.</p></div>{contextQuery.data?.active_version ? <div className="rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-4"><div className="flex flex-wrap gap-2"><Badge>{contextQuery.data.active_version.context_version_id}</Badge><Badge variant={contextQuery.data.active_version.assembly_eligible ? 'success' : 'warning'}>{contextQuery.data.active_version.assembly_eligible ? 'assembly eligible' : 'not eligible'}</Badge></div><pre className="mt-3 max-h-56 overflow-auto whitespace-pre-wrap text-sm text-[var(--osci-color-text-secondary)]">{contextQuery.data.active_version.content}</pre></div> : <EmptyState message="No active Context Version has been published." />}</CardBody></Card>
    <Card><CardBody className="space-y-4 p-5"><h3 className="font-semibold text-[var(--osci-color-text)]">History and diff</h3><div className="grid gap-3 sm:grid-cols-2"><FormField label="Before"><NativeSelect aria-label="Before Context Version" value={beforeVersionId} onChange={(event) => setBeforeVersionId(event.target.value)}><option value="">Select version</option>{versions.map((version) => <option key={version.context_version_id} value={version.context_version_id}>{version.context_version_id}</option>)}</NativeSelect></FormField><FormField label="After"><NativeSelect aria-label="After Context Version" value={afterVersionId} onChange={(event) => setAfterVersionId(event.target.value)}><option value="">Select version</option>{versions.map((version) => <option key={version.context_version_id} value={version.context_version_id}>{version.context_version_id}</option>)}</NativeSelect></FormField></div>{diffQuery.data ? <pre className="max-h-80 overflow-auto whitespace-pre-wrap rounded-[var(--osci-radius-md)] bg-[var(--osci-color-surface-subtle)] p-4 text-xs text-[var(--osci-color-text)]">{diffQuery.data.diff}</pre> : null}<div className="space-y-2">{versions.map((version) => <div key={version.context_version_id} className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--osci-color-border-subtle)] pt-2 text-sm"><span className="font-mono text-[var(--osci-color-text)]">{version.context_version_id}</span><span className="text-[var(--osci-color-text-muted)]">{new Date(version.created_at).toLocaleString()}</span></div>)}</div></CardBody></Card>
    <Card><CardBody className="space-y-3 p-5"><div><h3 className="font-semibold text-[var(--osci-color-text)]">Candidates</h3><p className="text-sm text-[var(--osci-color-text-secondary)]">Accept appends a candidate into the editable Draft; reject preserves its audit record.</p></div>{candidates.map((candidate) => <div key={candidate.candidate_id} className="rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] p-3"><div className="flex flex-wrap items-center justify-between gap-2"><div className="flex items-center gap-2"><Badge variant="outline">{candidate.status}</Badge><span className="text-xs font-mono text-[var(--osci-color-text-muted)]">{candidate.candidate_id}</span></div>{candidate.status === 'pending' ? <div className="flex gap-2"><Button size="sm" variant="secondary" disabled={!project.permissions.can_edit} onClick={() => rejectMutation.mutate(candidate.candidate_id)}>Reject</Button><Button size="sm" disabled={!project.permissions.can_edit} onClick={() => acceptMutation.mutate(candidate.candidate_id)}>Accept</Button></div> : null}</div><p className="mt-2 whitespace-pre-wrap text-sm text-[var(--osci-color-text-secondary)]">{candidate.content}</p></div>)}{candidates.length === 0 ? <EmptyState message="No pending Context candidates." /> : null}</CardBody></Card>
  </div>;
}
