import { useState } from 'react';
import type { EnvironmentRecord, TaskCreateRequest, WorkspaceRecord } from '../../types';

interface TaskCreateFormProps {
  workspaces: WorkspaceRecord[];
  environments: EnvironmentRecord[];
  selectedWorkspaceId: string;
  selectedEnvironmentId: string;
  selectedWorkspace: WorkspaceRecord | null;
  selectedEnvironment: EnvironmentRecord | null;
  draftDefaults: {
    title: string;
    task_input: string;
  };
  isSubmitting: boolean;
  createError: string | null;
  onSelectWorkspace: (workspaceId: string) => void;
  onSelectEnvironment: (environmentId: string) => void;
  onSubmit: (payload: TaskCreateRequest) => void;
}

export default function TaskCreateForm({
  workspaces,
  environments,
  selectedWorkspaceId,
  selectedEnvironmentId,
  selectedWorkspace,
  selectedEnvironment,
  draftDefaults,
  isSubmitting,
  createError,
  onSelectWorkspace,
  onSelectEnvironment,
  onSubmit,
}: TaskCreateFormProps) {
  const [draft, setDraft] = useState({
    title: draftDefaults.title,
    task_input: draftDefaults.task_input,
    task_profile: 'claude-code',
  });

  const canCreate =
    selectedWorkspace !== null &&
    selectedEnvironment !== null &&
    draft.task_input.trim().length > 0 &&
    !isSubmitting;

  return (
    <form
      className="space-y-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!selectedWorkspace || !selectedEnvironment) {
          return;
        }

        onSubmit({
          workspace_id: selectedWorkspace.workspace_id,
          environment_id: selectedEnvironment.id,
          task_profile: draft.task_profile,
          task_input: draft.task_input.trim(),
          title: draft.title.trim() || undefined,
        });
      }}
    >
      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Workspace</span>
        <select
          aria-label="Workspace"
          value={selectedWorkspaceId}
          onChange={(event) => onSelectWorkspace(event.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          {workspaces.map((workspace) => (
            <option key={workspace.workspace_id} value={workspace.workspace_id}>
              {workspace.label}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Environment</span>
        <select
          aria-label="Environment"
          value={selectedEnvironmentId}
          onChange={(event) => onSelectEnvironment(event.target.value)}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          {environments.map((environment) => (
            <option key={environment.id} value={environment.id}>
              {environment.alias} · {environment.display_name}
            </option>
          ))}
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Task profile</span>
        <select
          aria-label="Task profile"
          value={draft.task_profile}
          onChange={(event) =>
            setDraft((current) => ({ ...current, task_profile: event.target.value }))
          }
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
        >
          <option value="claude-code">claude-code</option>
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Title</span>
        <input
          aria-label="Title"
          value={draft.title}
          onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
          className="w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          placeholder="Optional"
        />
      </label>

      <label className="block space-y-2">
        <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">Task input</span>
        <textarea
          aria-label="Task input"
          value={draft.task_input}
          onChange={(event) =>
            setDraft((current) => ({ ...current, task_input: event.target.value }))
          }
          className="min-h-40 w-full rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text)] outline-none transition focus:border-[var(--apple-blue)] focus:ring-2 focus:ring-[var(--apple-blue)]/15"
          placeholder="Implement Task Harness v1 according to the current repository plan."
        />
      </label>

      <div className="flex flex-wrap items-center gap-3">
        <button
          type="button"
          className="rounded-lg border border-[var(--border)] bg-[var(--bg)] px-4 py-2 text-sm font-medium text-[var(--text)] transition hover:bg-[var(--bg-secondary)]"
          onClick={() =>
            setDraft({
              title: draftDefaults.title,
              task_input: draftDefaults.task_input,
              task_profile: 'claude-code',
            })
          }
        >
          Reset draft
        </button>

        <button
          type="submit"
          disabled={!canCreate}
          className="rounded-lg bg-[var(--apple-blue)] px-4 py-2 text-sm font-medium text-white transition hover:bg-[var(--apple-blue-hover)] disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isSubmitting ? 'Creating…' : 'Create task'}
        </button>
      </div>

      {selectedWorkspace ? (
        <p className="rounded-lg bg-[var(--bg-secondary)] px-4 py-3 text-sm tracking-[-0.224px] text-[var(--text-secondary)]">
          Default workdir: <code className="rounded bg-[var(--bg-tertiary)] px-1.5 py-0.5 text-xs">{selectedWorkspace.default_workdir ?? 'n/a'}</code>
        </p>
      ) : null}
      {createError ? <p className="text-sm text-[#ff3b30]">{createError}</p> : null}
    </form>
  );
}
