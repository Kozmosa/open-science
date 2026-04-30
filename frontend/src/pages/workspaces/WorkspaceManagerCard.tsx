import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { createWorkspace, deleteWorkspace, getWorkspaces, updateWorkspace } from '../../api';
import { useT } from '../../i18n';
import type { WorkspaceCreateRequest, WorkspaceRecord, WorkspaceUpdateRequest } from '../../types';
import { SectionCard, SectionHeader, Button, FormField, Input, Textarea, Alert } from '../../components/ui';

interface WorkspaceDraft {
  label: string;
  description: string;
  default_workdir: string;
  workspace_prompt: string;
}

const emptyDraft: WorkspaceDraft = {
  label: '',
  description: '',
  default_workdir: '',
  workspace_prompt: '',
};

function toDraft(workspace: WorkspaceRecord | null): WorkspaceDraft {
  if (!workspace) {
    return emptyDraft;
  }
  return {
    label: workspace.label,
    description: workspace.description ?? '',
    default_workdir: workspace.default_workdir ?? '',
    workspace_prompt: workspace.workspace_prompt,
  };
}

function toCreatePayload(draft: WorkspaceDraft): WorkspaceCreateRequest {
  return {
    label: draft.label.trim(),
    description: draft.description.trim() || null,
    default_workdir: draft.default_workdir.trim() || null,
    workspace_prompt: draft.workspace_prompt,
  };
}

function toUpdatePayload(draft: WorkspaceDraft): WorkspaceUpdateRequest {
  return toCreatePayload(draft);
}

export default function WorkspaceManagerCard() {
  const t = useT();
  const queryClient = useQueryClient();
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);
  const workspacesQuery = useQuery({
    queryKey: ['workspaces'],
    queryFn: getWorkspaces,
  });
  const workspaces = useMemo(() => workspacesQuery.data?.items ?? [], [workspacesQuery.data]);
  const selectedWorkspace =
    workspaces.find((workspace) => workspace.workspace_id === selectedWorkspaceId) ??
    workspaces[0] ??
    null;
  const [draft, setDraft] = useState<WorkspaceDraft>(toDraft(selectedWorkspace));

  useEffect(() => {
    if (!selectedWorkspaceId && workspaces[0]) {
      setSelectedWorkspaceId(workspaces[0].workspace_id);
    }
  }, [selectedWorkspaceId, workspaces]);

  useEffect(() => {
    setDraft(toDraft(isCreating ? null : selectedWorkspace));
    setIsConfirmingDelete(false);
  }, [isCreating, selectedWorkspace]);

  const invalidateWorkspaces = () => {
    void queryClient.invalidateQueries({ queryKey: ['workspaces'] });
  };

  const createMutation = useMutation({
    mutationFn: createWorkspace,
    onSuccess: (workspace) => {
      setIsCreating(false);
      setSelectedWorkspaceId(workspace.workspace_id);
      invalidateWorkspaces();
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ workspaceId, payload }: { workspaceId: string; payload: WorkspaceUpdateRequest }) =>
      updateWorkspace(workspaceId, payload),
    onSuccess: (workspace) => {
      setSelectedWorkspaceId(workspace.workspace_id);
      invalidateWorkspaces();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: deleteWorkspace,
    onSuccess: () => {
      setSelectedWorkspaceId(workspaces[0]?.workspace_id ?? null);
      setIsConfirmingDelete(false);
      invalidateWorkspaces();
    },
  });

  const canDelete = selectedWorkspace !== null && selectedWorkspace.workspace_id !== 'workspace-default';
  const isBusy = createMutation.isPending || updateMutation.isPending || deleteMutation.isPending;

  return (
    <SectionCard>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SectionHeader
          title={t('pages.workspaces.managerTitle')}
          description={t('pages.workspaces.managerDescription')}
        />
        <Button
          onClick={() => {
            setIsCreating(true);
            setSelectedWorkspaceId(null);
          }}
        >
          {t('pages.workspaces.newWorkspace')}
        </Button>
      </div>

      {workspacesQuery.isLoading ? (
        <p className="text-sm text-[var(--text-tertiary)]">{t('common.loading')}</p>
      ) : null}
      {workspacesQuery.error instanceof Error ? (
        <Alert variant="error">{workspacesQuery.error.message}</Alert>
      ) : null}

      <div className="grid gap-5 xl:grid-cols-[minmax(220px,320px)_1fr]">
        <div className="space-y-2">
          {workspaces.map((workspace) => (
            <button
              key={workspace.workspace_id}
              type="button"
              aria-label={workspace.label}
              onClick={() => {
                setSelectedWorkspaceId(workspace.workspace_id);
                setIsCreating(false);
              }}
              className={`w-full rounded-lg border px-4 py-3 text-left transition ${
                selectedWorkspace?.workspace_id === workspace.workspace_id && !isCreating
                  ? 'border-[var(--apple-blue)] bg-[var(--bg-secondary)]'
                  : 'border-[var(--border)] bg-[var(--bg)] hover:bg-[var(--bg-secondary)]'
              }`}
            >
              <span className="block text-sm font-medium text-[var(--text)]">{workspace.label}</span>
              <span className="mt-1 block truncate text-xs text-[var(--text-tertiary)]">
                {workspace.default_workdir ?? t('pages.workspaces.noDefaultWorkdir')}
              </span>
            </button>
          ))}
        </div>

        <form
          className="space-y-4 rounded-lg bg-[var(--bg-secondary)] p-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (isCreating) {
              createMutation.mutate(toCreatePayload(draft));
              return;
            }
            if (selectedWorkspace) {
              updateMutation.mutate({
                workspaceId: selectedWorkspace.workspace_id,
                payload: toUpdatePayload(draft),
              });
            }
          }}
        >
          <FormField label={t('pages.workspaces.labelField')}>
            <Input
              aria-label={t('pages.workspaces.labelField')}
              required
              value={draft.label}
              onChange={(event) => setDraft((current) => ({ ...current, label: event.target.value }))}
            />
          </FormField>
          <FormField label={t('pages.workspaces.descriptionField')}>
            <Input
              aria-label={t('pages.workspaces.descriptionField')}
              value={draft.description}
              onChange={(event) =>
                setDraft((current) => ({ ...current, description: event.target.value }))
              }
            />
          </FormField>
          <FormField label={t('pages.workspaces.defaultWorkdirField')}>
            <Input
              aria-label={t('pages.workspaces.defaultWorkdirField')}
              value={draft.default_workdir}
              onChange={(event) =>
                setDraft((current) => ({ ...current, default_workdir: event.target.value }))
              }
            />
          </FormField>
          <FormField label={t('pages.workspaces.promptField')}>
            <Textarea
              aria-label={t('pages.workspaces.promptField')}
              required
              value={draft.workspace_prompt}
              onChange={(event) =>
                setDraft((current) => ({ ...current, workspace_prompt: event.target.value }))
              }
              className="min-h-32"
            />
          </FormField>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap gap-3">
              {!isCreating && canDelete ? (
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setIsConfirmingDelete((current) => !current)}
                  className="border-[#ff3b30]/40 text-[#ff3b30] hover:bg-[#ff3b30]/10 hover:text-[#ff3b30]"
                >
                  {t('pages.workspaces.deleteWorkspace')}
                </Button>
              ) : null}
              {isConfirmingDelete && selectedWorkspace ? (
                <Button
                  type="button"
                  variant="danger"
                  onClick={() => deleteMutation.mutate(selectedWorkspace.workspace_id)}
                  disabled={isBusy}
                >
                  {t('pages.workspaces.confirmDelete')}
                </Button>
              ) : null}
            </div>
            <Button type="submit" disabled={isBusy}>
              {isCreating
                ? t('pages.workspaces.createWorkspace')
                : t('pages.workspaces.saveWorkspace')}
            </Button>
          </div>
        </form>
      </div>
    </SectionCard>
  );
}
