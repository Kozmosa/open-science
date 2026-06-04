import { useState, useMemo } from 'react';
import { Button, Select } from '../ui';
import { useT } from '../../i18n';
import type { TaskCreatePayload, WorkspaceRecord, EnvironmentRecord } from '../../types';
import { getTaskPreset, TASK_PRESET_OPTIONS, type TaskPresetId } from '../../pages/tasks/taskPresets';

interface Props {
  paperTitle: string;
  paperAbstract: string;
  workspaces: WorkspaceRecord[];
  environments: EnvironmentRecord[];
  isOpen: boolean;
  isSubmitting: boolean;
  onConfirm: (payload: TaskCreatePayload) => void;
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
  const [selectedTaskPresetId, setSelectedTaskPresetId] = useState<TaskPresetId>('raw-prompt');
  const [harnessEngine, setHarnessEngine] = useState<'claude-code' | 'agent-sdk' | 'codex-app-server'>('claude-code');
  const [researcherType, setResearcherType] = useState<'vanilla' | 'aris-researcher'>('vanilla');

  const effectiveWorkspaceId = useMemo(
    () => selectedWorkspaceId || workspaces[0]?.workspace_id || '',
    [selectedWorkspaceId, workspaces]
  );
  const effectiveEnvironmentId = useMemo(
    () => selectedEnvironmentId || environments[0]?.id || '',
    [selectedEnvironmentId, environments]
  );

  const applyTaskPreset = (presetId: TaskPresetId) => {
    const preset = getTaskPreset(presetId);
    setSelectedTaskPresetId(preset.id);
    setResearcherType(preset.researcherType);
    setHarnessEngine(preset.harnessEngine);
  };


  if (!isOpen) return null;

  const handleConfirm = () => {
    onConfirm({
      project_id: 'default',
      workspace_id: effectiveWorkspaceId,
      environment_id: effectiveEnvironmentId,
      researcher_type: researcherType,
      harness_engine: harnessEngine,
      prompt: paperAbstract,
      title: paperTitle.slice(0, 200),
      skills: [],
      mcp_servers: [],
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

          <label className="block">
            <span className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.create.taskPreset')}
            </span>
            <Select
              value={selectedTaskPresetId}
              onChange={(e) => applyTaskPreset(e.target.value as TaskPresetId)}
              className="w-full text-xs py-2"
            >
              {TASK_PRESET_OPTIONS.map((preset) => (
                <option key={preset.id} value={preset.id}>{t(preset.labelKey)}</option>
              ))}
            </Select>
          </label>

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
              Researcher Type
            </label>
            <Select
              value={researcherType}
              onChange={(e) => setResearcherType(e.target.value as 'vanilla' | 'aris-researcher')}
              className="w-full text-xs py-2"
            >
              <option value="vanilla">Vanilla</option>
              <option value="aris-researcher">ARIS Researcher</option>
            </Select>
          </div>

          <div>
            <label className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              Execution Engine
            </label>
            <Select
              value={harnessEngine}
              onChange={(e) => setHarnessEngine(e.target.value as 'claude-code' | 'agent-sdk' | 'codex-app-server')}
              className="w-full text-xs py-2"
            >
              <option value="claude-code">Claude Code</option>
              <option value="agent-sdk">Agent SDK</option>
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
