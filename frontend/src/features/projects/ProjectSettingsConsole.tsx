import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Alert, Badge, Button, Card, CardBody, Checkbox, ConfirmDialog, FormField, Input, NativeSelect, Textarea } from '@design-system';
import { updateProject } from '@/shared/api';
import { IdempotencyKeyManager, semanticMutationValue, useIdempotencyKey } from '@/shared/api/idempotency';
import { queryKeys } from '@/shared/api/queryKeys';
import { extractErrorMessage } from '@/shared/utils/error';
import {
  archiveDomainProject,
  getDomainProjectMembers,
  removeDomainProjectMember,
  unarchiveDomainProject,
  upsertDomainProjectMember,
  type DomainProjectProjection,
} from '@features/domain';

export default function ProjectSettingsConsole({ project }: { project: DomainProjectProjection }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? '');
  const [memberUserId, setMemberUserId] = useState('');
  const [memberRole, setMemberRole] = useState<'viewer' | 'editor'>('viewer');
  const [memberCanPublish, setMemberCanPublish] = useState(false);
  const [archiveConfirmOpen, setArchiveConfirmOpen] = useState(false);
  const membersQuery = useQuery({ queryKey: ['domain', 'projects', project.project_id, 'members'], queryFn: () => getDomainProjectMembers(project.project_id) });
  const metadataKey = useIdempotencyKey('project.metadata', { projectId: project.project_id, name, description });
  const memberKey = useIdempotencyKey('project.member.upsert', { projectId: project.project_id, memberUserId, memberRole, memberCanPublish });
  const removeKeyManager = useRef(new IdempotencyKeyManager('project.member.remove')).current;
  const lifecycleKeyManager = useRef(new IdempotencyKeyManager('project.lifecycle')).current;
  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.domain.projects(true) });
    void queryClient.invalidateQueries({ queryKey: ['domain', 'projects', project.project_id, 'members'] });
  };
  const updateMutation = useMutation({ mutationFn: () => updateProject(project.project_id, { name: name.trim(), description: description.trim() || null }, metadataKey.idempotencyKey), onSuccess: () => { metadataKey.markSucceeded(); invalidate(); } });
  const memberMutation = useMutation({ mutationFn: () => upsertDomainProjectMember(project.project_id, memberUserId.trim(), memberRole, memberCanPublish, memberKey.idempotencyKey), onSuccess: () => { memberKey.markSucceeded(); setMemberUserId(''); setMemberRole('viewer'); setMemberCanPublish(false); invalidate(); } });
  const removeMutation = useMutation({
    mutationFn: async (userId: string) => {
      const key = removeKeyManager.keyFor(semanticMutationValue({ projectId: project.project_id, userId }));
      await removeDomainProjectMember(project.project_id, userId, key);
      return key;
    },
    onSuccess: (key) => { removeKeyManager.markSucceeded(key); invalidate(); },
  });
  const lifecycleMutation = useMutation({
    mutationFn: async () => {
      const action = project.status === 'active' ? 'archive' : 'unarchive';
      const key = lifecycleKeyManager.keyFor(semanticMutationValue({ projectId: project.project_id, action }));
      if (action === 'archive') await archiveDomainProject(project.project_id, key);
      else await unarchiveDomainProject(project.project_id, key);
      return key;
    },
    onSuccess: (key) => { lifecycleKeyManager.markSucceeded(key); invalidate(); },
  });
  const error = membersQuery.error ?? updateMutation.error ?? memberMutation.error ?? removeMutation.error ?? lifecycleMutation.error;

  return <div className="space-y-4">
    {error ? <Alert variant="error">{extractErrorMessage(error)}</Alert> : null}
    <Card><CardBody className="space-y-4 p-5"><div><h3 className="font-semibold text-[var(--osci-color-text)]">Basic information</h3><p className="text-sm text-[var(--osci-color-text-secondary)]">Editor permission is required to change Project metadata.</p></div><FormField label="Project name"><Input aria-label="Project name" value={name} disabled={!project.permissions.can_edit} onChange={(event) => setName(event.target.value)} /></FormField><FormField label="Description"><Textarea aria-label="Project description" value={description} disabled={!project.permissions.can_edit} onChange={(event) => setDescription(event.target.value)} /></FormField><Button disabled={!project.permissions.can_edit || !name.trim()} isLoading={updateMutation.isPending} onClick={() => updateMutation.mutate()}>Save Project</Button></CardBody></Card>
    <Card><CardBody className="space-y-4 p-5"><div><h3 className="font-semibold text-[var(--osci-color-text)]">Members</h3><p className="text-sm text-[var(--osci-color-text-secondary)]">Add the first release member by exact user ID; no user search is performed.</p></div>{project.permissions.can_manage_members ? <form className="grid gap-3 md:grid-cols-[minmax(0,1fr)_160px_auto_auto] md:items-end" onSubmit={(event) => { event.preventDefault(); memberMutation.mutate(); }}><FormField label="User ID"><Input aria-label="Member user ID" required value={memberUserId} onChange={(event) => setMemberUserId(event.target.value)} /></FormField><FormField label="Role"><NativeSelect aria-label="Member role" value={memberRole} onChange={(event) => setMemberRole(event.target.value as 'viewer' | 'editor')}><option value="viewer">viewer</option><option value="editor">editor</option></NativeSelect></FormField><label className="flex min-h-10 items-center gap-2 text-sm text-[var(--osci-color-text)]"><Checkbox aria-label="Member can publish" checked={memberCanPublish} onCheckedChange={(value) => setMemberCanPublish(value === true)} />can_publish</label><Button type="submit" disabled={!memberUserId.trim()} isLoading={memberMutation.isPending}>Add / update</Button></form> : null}<div className="space-y-2">{membersQuery.data?.items.map((member) => <div key={member.user_id} className="flex flex-wrap items-center justify-between gap-2 rounded-[var(--osci-radius-md)] border border-[var(--osci-color-border-subtle)] p-3"><div><p className="font-medium text-[var(--osci-color-text)]">{member.display_name || member.username || member.user_id}</p><p className="font-mono text-xs text-[var(--osci-color-text-muted)]">{member.user_id}</p></div><div className="flex items-center gap-2"><Badge variant="outline">{member.role}</Badge>{member.can_publish ? <Badge>can_publish</Badge> : null}{project.permissions.can_manage_members ? <Button size="sm" variant="danger" onClick={() => removeMutation.mutate(member.user_id)}>Remove</Button> : null}</div></div>)}</div></CardBody></Card>
    <Card><CardBody className="space-y-3 p-5"><h3 className="font-semibold text-[var(--osci-color-text)]">Lifecycle</h3>{project.is_default ? <Alert variant="info">The default Project is permanent and cannot be archived.</Alert> : null}<Button variant={project.status === 'active' ? 'danger' : 'primary'} disabled={project.is_default || (project.status === 'active' ? !project.permissions.can_archive : !project.permissions.can_unarchive)} isLoading={lifecycleMutation.isPending} onClick={() => project.status === 'active' ? setArchiveConfirmOpen(true) : lifecycleMutation.mutate()}>{project.status === 'active' ? 'Archive Project' : 'Unarchive Project'}</Button></CardBody></Card>
    <ConfirmDialog open={archiveConfirmOpen} onOpenChange={setArchiveConfirmOpen} title="Archive Project" description="Running and queued execution will be stopped according to the domain lifecycle policy. The Project remains auditable and may be unarchived later." confirmLabel="Archive Project" danger onConfirm={() => lifecycleMutation.mutate()} />
  </div>;
}
