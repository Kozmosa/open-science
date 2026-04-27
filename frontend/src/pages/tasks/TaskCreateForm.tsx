import { X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { useT } from '../../i18n';
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
  onClose?: () => void;
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
  onClose,
}: TaskCreateFormProps) {
  const t = useT();
  const [draft, setDraft] = useState({
    title: draftDefaults.title,
    task_input: draftDefaults.task_input,
    task_profile: 'claude-code',
  });
  const taskInputRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    taskInputRef.current?.focus();
  }, []);

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
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold tracking-tight text-[var(--foreground)]">
            {t('pages.tasks.createTitle')}
          </h2>
          <p className="mt-1 text-sm text-[var(--muted-foreground)]">
            {t('pages.tasks.createDescription')}
          </p>
        </div>
        {onClose ? (
          <button
            type="button"
            onClick={onClose}
            className="inline-flex h-8 w-8 items-center justify-center rounded-md text-[var(--muted-foreground)] transition hover:bg-[var(--muted)] hover:text-[var(--foreground)]"
            aria-label={t('pages.tasks.closeCreate')}
          >
            <X size={16} />
          </button>
        ) : null}
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--muted-foreground)]">
            {t('pages.tasks.workspaceLabel')}
          </span>
          <select
            aria-label={t('pages.tasks.workspaceLabel')}
            value={selectedWorkspaceId}
            onChange={(event) => onSelectWorkspace(event.target.value)}
            className="h-10 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--ring)]"
          >
            {workspaces.map((workspace) => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block space-y-2">
          <span className="text-xs font-medium text-[var(--muted-foreground)]">
            {t('pages.tasks.environmentLabel')}
          </span>
          <select
            aria-label={t('pages.tasks.environmentLabel')}
            value={selectedEnvironmentId}
            onChange={(event) => onSelectEnvironment(event.target.value)}
            className="h-10 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--ring)]"
          >
            {environments.map((environment) => (
              <option key={environment.id} value={environment.id}>
                {environment.alias} · {environment.display_name}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="block space-y-2">
        <span className="text-xs font-medium text-[var(--muted-foreground)]">
          {t('pages.tasks.profileLabel')}
        </span>
        <select
          aria-label={t('pages.tasks.profileLabel')}
          value={draft.task_profile}
          onChange={(event) =>
            setDraft((current) => ({ ...current, task_profile: event.target.value }))
          }
          className="h-10 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--ring)]"
        >
          <option value="claude-code">claude-code</option>
        </select>
      </label>

      <label className="block space-y-2">
        <span className="text-xs font-medium text-[var(--muted-foreground)]">
          {t('pages.tasks.titleLabel')}
        </span>
        <input
          aria-label={t('pages.tasks.titleLabel')}
          value={draft.title}
          onChange={(event) => setDraft((current) => ({ ...current, title: event.target.value }))}
          className="h-10 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3 text-sm text-[var(--foreground)] outline-none transition placeholder:text-[var(--muted-foreground)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--ring)]"
          placeholder={t('pages.tasks.optionalPlaceholder')}
        />
      </label>

      <label className="block space-y-2">
        <span className="text-xs font-medium text-[var(--muted-foreground)]">
          {t('pages.tasks.taskInputLabel')}
        </span>
        <textarea
          ref={taskInputRef}
          aria-label={t('pages.tasks.taskInputLabel')}
          value={draft.task_input}
          onChange={(event) =>
            setDraft((current) => ({ ...current, task_input: event.target.value }))
          }
          className="min-h-44 w-full rounded-lg border border-[var(--input)] bg-[var(--background)] px-3 py-3 text-sm text-[var(--foreground)] outline-none transition placeholder:text-[var(--muted-foreground)] focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--ring)]"
          placeholder={t('pages.tasks.taskInputPlaceholder')}
        />
      </label>

      {selectedWorkspace ? (
        <p className="rounded-lg bg-[var(--muted)] px-3 py-2 text-xs text-[var(--muted-foreground)]">
          {t('pages.tasks.defaultWorkdir')}{' '}
          <code className="rounded bg-[var(--code-background)] px-1.5 py-0.5 text-[var(--code-foreground)]">
            {selectedWorkspace.default_workdir ?? t('pages.tasks.unavailable')}
          </code>
        </p>
      ) : null}
      {createError ? <p className="text-sm text-[var(--destructive)]">{createError}</p> : null}

      <div className="flex flex-wrap items-center justify-end gap-3 border-t border-[var(--border)] pt-4">
        <button
          type="button"
          className="rounded-lg border border-[var(--border)] bg-[var(--background)] px-4 py-2 text-sm font-medium text-[var(--foreground)] transition hover:bg-[var(--muted)]"
          onClick={() =>
            setDraft({
              title: draftDefaults.title,
              task_input: draftDefaults.task_input,
              task_profile: 'claude-code',
            })
          }
        >
          {t('pages.tasks.resetDraft')}
        </button>

        <button
          type="submit"
          disabled={!canCreate}
          className="rounded-lg bg-[var(--primary)] px-4 py-2 text-sm font-medium text-[var(--primary-foreground)] transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
        >
          {isSubmitting ? t('pages.tasks.creatingAction') : t('pages.tasks.createAction')}
        </button>
      </div>
    </form>
  );
}
