import { useState, useMemo } from 'react';
import { Button, Select } from '../ui';
import { useT } from '../../i18n';
import type { TaskCreateRequest, WorkspaceRecord, EnvironmentRecord } from '../../types';

interface Props {
  paperTitle: string;
  paperAbstract: string;
  workspaces: WorkspaceRecord[];
  environments: EnvironmentRecord[];
  isOpen: boolean;
  isSubmitting: boolean;
  onConfirm: (payload: TaskCreateRequest) => void;
  onCancel: () => void;
}

export default function ConvertToTaskDialog({
  paperTitle,
  paperAbstract,
  workspaces,
  environments,
  isOpen,
  isSubmitting,
  onConfirm,
  onCancel,
}: Props) {
  const t = useT();

  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState('');
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState('');
  const [executionEngine, setExecutionEngine] = useState('claude-code');

  const effectiveWorkspaceId = useMemo(
    () => selectedWorkspaceId || workspaces[0]?.workspace_id || '',
    [selectedWorkspaceId, workspaces]
  );
  const effectiveEnvironmentId = useMemo(
    () => selectedEnvironmentId || environments[0]?.id || '',
    [selectedEnvironmentId, environments]
  );

  if (!isOpen) return null;

  const handleConfirm = () => {
    onConfirm({
      project_id: 'default',
      workspace_id: effectiveWorkspaceId,
      environment_id: effectiveEnvironmentId,
      task_profile: 'claude-code',
      title: paperTitle.slice(0, 200),
      task_input: paperAbstract,
      execution_engine: executionEngine,
    });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-lg mx-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-xl">
        <h3 className="text-base font-semibold text-[var(--text)]">{t('literature.convertToTask')}</h3>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">{t('literature.convertConfirm')}</p>

        <div className="mt-4 space-y-3">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
            <p className="text-xs font-medium text-[var(--text)] truncate">{paperTitle}</p>
            <p className="mt-1 text-[11px] text-[var(--text-secondary)] line-clamp-3">{paperAbstract}</p>
          </div>

          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.workspaceLabel')}
            </label>
            <Select
              value={effectiveWorkspaceId}
              onChange={(e) => setSelectedWorkspaceId(e.target.value)}
              className="w-full text-xs py-2"
            >
              {workspaces.map((w: WorkspaceRecord) => (
                <option key={w.workspace_id} value={w.workspace_id}>{w.label}</option>
              ))}
            </Select>
          </div>

          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.environmentLabel')}
            </label>
            <Select
              value={effectiveEnvironmentId}
              onChange={(e) => setSelectedEnvironmentId(e.target.value)}
              className="w-full text-xs py-2"
            >
              {environments.map((env: EnvironmentRecord) => (
                <option key={env.id} value={env.id}>{env.alias} · {env.display_name}</option>
              ))}
            </Select>
          </div>

          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.profileLabel')}
            </label>
            <Select
              value={executionEngine}
              onChange={(e) => setExecutionEngine(e.target.value)}
              className="w-full text-xs py-2"
            >
              <option value="claude-code">Claude Code</option>
              <option value="agent-sdk">Claude Agent SDK</option>
              <option value="codex-app-server">Codex App Server</option>
            </Select>
          </div>
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="secondary" size="sm" onClick={onCancel} disabled={isSubmitting}>
            {t('common.cancel')}
          </Button>
          <Button size="sm" onClick={handleConfirm} isLoading={isSubmitting}>
            {t('literature.convertToTask')}
          </Button>
        </div>
      </div>
    </div>
  );
}
