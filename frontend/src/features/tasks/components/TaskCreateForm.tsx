import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, FormField, Input, Select, Textarea } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import type { EnvironmentRecord, ProjectRecord, SkillItem, TaskCreatePayload, ResearcherType, HarnessEngine, WorkspaceRecord } from '@/shared/types';
import type { ResearchAgentProfileSettings } from '@features/settings/types';
import TaskSkillPicker from '../components/TaskSkillPicker';
import { getTaskPreset, TASK_PRESET_OPTIONS, type TaskPresetId } from '../utils/taskPresets';
import SeedFileUploader, { type SeedFileInfo } from '../components/SeedFileUploader';
import { readMigratedLocalStorage, removeLocalStorage } from '@/shared/utils/storage';

const FIELD_IDS = {
  project: 'task-create-project',
  workspace: 'task-create-workspace',
  environment: 'task-create-environment',
  taskPreset: 'task-create-preset',
  researcherVanilla: 'task-create-researcher-vanilla',
  researcherAris: 'task-create-researcher-aris',
  harnessEngine: 'task-create-harness-engine',
  title: 'task-create-title',
  prompt: 'task-create-prompt',
};

const TASK_DRAFT_KEY = 'openscience:task-draft';
const LEGACY_TASK_DRAFT_KEYS = ['scholar-agent:task-draft'];

interface TaskDraft {
  selectedTaskPresetId: TaskPresetId;
  researcherType: ResearcherType;
  harnessEngine: HarnessEngine;
  prompt: string;
  skills: string[];
  title: string;
  arxivUrls: string[];
}

function readDraft(): TaskDraft | null {
  try {
    const raw = readMigratedLocalStorage(TASK_DRAFT_KEY, LEGACY_TASK_DRAFT_KEYS);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object') return null;
    return parsed as TaskDraft;
  } catch {
    return null;
  }
}

function writeDraft(draft: TaskDraft): void {
  try {
    localStorage.setItem(TASK_DRAFT_KEY, JSON.stringify(draft));
  } catch {
    // localStorage full or unavailable — silently ignore
  }
}

function clearDraft(): void {
  try {
    removeLocalStorage(TASK_DRAFT_KEY, LEGACY_TASK_DRAFT_KEYS);
  } catch {
    // ignore
  }
}

interface Props {
  projectId: string;
  workspaceId: string;
  environmentId: string;
  availableProjects: ProjectRecord[];
  availableWorkspaces: WorkspaceRecord[];
  availableEnvironments: EnvironmentRecord[];
  availableSkills: SkillItem[];
  lockProject?: boolean;
  researchAgentProfile?: ResearchAgentProfileSettings | null;
  onSubmit: (payload: TaskCreatePayload) => void;
  onCancel: () => void;
}

export default function TaskCreateForm({
  projectId,
  workspaceId,
  environmentId,
  availableProjects,
  availableWorkspaces,
  availableEnvironments,
  availableSkills,
  lockProject = false,
  researchAgentProfile,
  onSubmit,
  onCancel,
}: Props) {
  const t = useT();

  const [selectedProjectId, setSelectedProjectId] = useState(projectId);
  const [selectedWorkspaceId, setSelectedWorkspaceId] = useState(workspaceId);
  const [selectedEnvironmentId, setSelectedEnvironmentId] = useState(environmentId);
  const [selectedTaskPresetId, setSelectedTaskPresetId] = useState<TaskPresetId>('raw-prompt');
  const [researcherType, setResearcherType] = useState<ResearcherType>('vanilla');
  const [harnessEngine, setHarnessEngine] = useState<HarnessEngine>('claude-code');
  const [prompt, setPrompt] = useState('');
  const [skills, setSkills] = useState<string[]>([]);
  const [title, setTitle] = useState('');
  const [seedFiles, setSeedFiles] = useState<SeedFileInfo[]>([]);
  const [arxivUrls, setArxivUrls] = useState<string[]>([]);
  const [arxivInput, setArxivInput] = useState('');
  const [arxivInputError, setArxivInputError] = useState<string | null>(null);

  // ── Draft persistence ─────────────────────────────────────────
  const draftRestoredRef = useRef(false);
  const [showDraftNotice, setShowDraftNotice] = useState(false);

  // Restore draft on mount (must be after useState declarations for the lint rule)
  useEffect(() => {
    const saved = readDraft();
    if (saved) {
      setSelectedTaskPresetId(saved.selectedTaskPresetId ?? 'raw-prompt');
      setResearcherType(saved.researcherType ?? 'vanilla');
      setHarnessEngine(saved.harnessEngine ?? 'claude-code');
      setPrompt(saved.prompt ?? '');
      setSkills(saved.skills ?? []);
      setTitle(saved.title ?? '');
      setArxivUrls(saved.arxivUrls ?? []);
      draftRestoredRef.current = true;
      setShowDraftNotice(true);
    }
  }, []);

  const handleDiscardDraft = useCallback(() => {
    clearDraft();
    setShowDraftNotice(false);
  }, []);

  // Sync form state → localStorage on changes
  useEffect(() => {
    const d: TaskDraft = {
      selectedTaskPresetId,
      researcherType,
      harnessEngine,
      prompt,
      skills,
      title,
      arxivUrls,
    };
    writeDraft(d);
  }, [
    selectedTaskPresetId,
    researcherType,
    harnessEngine,
    prompt,
    skills,
    title,
    arxivUrls,
  ]);

  const ARXIV_URL_RE = /^https?:\/\/arxiv\.org\/(abs|pdf)\/[\w.-]+(\/)?(\.pdf)?$/;

  const SEED_FILE_PRESETS: TaskPresetId[] = ['reproduce-baseline-default', 'structured-research-default', 'overview'];
  const showSeedUploader = SEED_FILE_PRESETS.includes(selectedTaskPresetId);
  const showPaperInput = selectedTaskPresetId === 'overview';

  useEffect(() => {
    setSelectedProjectId(projectId);
  }, [projectId]);

  useEffect(() => {
    setSelectedWorkspaceId(workspaceId);
  }, [workspaceId]);

  useEffect(() => {
    setSelectedEnvironmentId(environmentId);
  }, [environmentId]);

  const handleProjectChange = (nextProjectId: string) => {
    setSelectedProjectId(nextProjectId);
    const project = availableProjects.find(item => item.project_id === nextProjectId);
    if (project?.default_workspace_id && availableWorkspaces.some(item => item.workspace_id === project.default_workspace_id)) {
      setSelectedWorkspaceId(project.default_workspace_id);
    }
    if (project?.default_environment_id && availableEnvironments.some(item => item.id === project.default_environment_id)) {
      setSelectedEnvironmentId(project.default_environment_id);
    }
  };

  const applyTaskPreset = (presetId: TaskPresetId) => {
    const preset = getTaskPreset(presetId);
    setSelectedTaskPresetId(preset.id);
    setResearcherType(preset.researcherType);
    setHarnessEngine(preset.harnessEngine);
    setSeedFiles([]);
    setArxivUrls([]);
    setArxivInput('');
    setArxivInputError(null);
  };

  const handleAddArxivUrl = () => {
    const trimmed = arxivInput.trim();
    if (!trimmed) return;

    if (!ARXIV_URL_RE.test(trimmed)) {
      setArxivInputError(t('pages.tasks.create.arxiv.invalidUrl'));
      return;
    }
    if (arxivUrls.includes(trimmed)) {
      setArxivInputError(t('pages.tasks.create.arxiv.duplicateUrl'));
      return;
    }

    setArxivUrls((prev) => [...prev, trimmed]);
    setArxivInput('');
    setArxivInputError(null);
  };

  const handleRemoveArxivUrl = (index: number) => {
    setArxivUrls((prev) => prev.filter((_, i) => i !== index));
  };

  const handleArxivInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      handleAddArxivUrl();
    }
  };

  const buildPromptWithPapers = (userPrompt: string, files: SeedFileInfo[], urls: string[]): string => {
    const uploaded = files.filter(f => f.status === 'uploaded');
    const parts: string[] = [];

    if (urls.length > 0) {
      const urlRefs = urls.map(u => `- ${u}`).join('\n');
      parts.push(`请总结以下论文：\n${urlRefs}\n`);
    }
    if (uploaded.length > 0) {
      const fileRefs = uploaded.map(f => `- ${f.serverPath}`).join('\n');
      parts.push(`请参考以下论文文件作为研究和分析的参考材料：\n${fileRefs}\n`);
    }

    if (parts.length === 0) return userPrompt;
    return parts.join('\n') + userPrompt;
  };

  const canSubmit = selectedProjectId !== '' && selectedWorkspaceId !== '' && selectedEnvironmentId !== '' && prompt.trim() !== '';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) {
      return;
    }
    clearDraft();
    const profile = researchAgentProfile;
    onSubmit({
      project_id: selectedProjectId,
      workspace_id: selectedWorkspaceId,
      environment_id: selectedEnvironmentId,
      researcher_type: researcherType,
      harness_engine: harnessEngine,
      prompt: buildPromptWithPapers(prompt, seedFiles, arxivUrls),
      skills: researcherType === 'vanilla' ? skills : [],
      mcp_servers: [],
      title: title || undefined,
      research_agent_profile: profile ? {
        profile_id: profile.profileId,
        label: profile.label,
        api_base_url: profile.apiBaseUrl || null,
        api_key: profile.apiKey || null,
        codex_base_url: profile.codexBaseUrl || null,
        codex_api_key: profile.codexApiKey || null,
        codex_model: profile.codexModel || null,
        codex_app_server_command: profile.codexAppServerCommand || null,
        codex_approval_policy: profile.codexApprovalPolicy || null,
      } : null,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 text-[var(--text)]">
      {showDraftNotice && (
        <div className="flex items-center justify-between rounded-lg border border-[var(--success-border)] bg-[var(--success-soft)] px-3 py-2 text-xs text-[var(--success-foreground)]">
          <span>{t('pages.tasks.create.draftNotice')}</span>
          <button
            type="button"
            onClick={handleDiscardDraft}
            className="ml-2 shrink-0 rounded px-2 py-0.5 text-[var(--text-tertiary)] hover:text-[var(--text)] hover:bg-[var(--bg-secondary)] transition-colors"
          >
            {t('pages.tasks.create.draftDiscard')}
          </button>
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-3">
        <FormField label={t('pages.tasks.projectLabel')}>
          <Select
            id={FIELD_IDS.project}
            value={selectedProjectId}
            onChange={(e) => handleProjectChange(e.target.value)}
            disabled={lockProject || availableProjects.length === 0}
          >
            {availableProjects.map(project => (
              <option key={project.project_id} value={project.project_id}>
                {project.name}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label={t('pages.tasks.workspaceLabel')}>
          <Select
            id={FIELD_IDS.workspace}
            value={selectedWorkspaceId}
            onChange={(e) => setSelectedWorkspaceId(e.target.value)}
            disabled={availableWorkspaces.length === 0}
          >
            {availableWorkspaces.map(workspace => (
              <option key={workspace.workspace_id} value={workspace.workspace_id}>
                {workspace.label}
              </option>
            ))}
          </Select>
        </FormField>

        <FormField label={t('pages.tasks.environmentLabel')}>
          <Select
            id={FIELD_IDS.environment}
            value={selectedEnvironmentId}
            onChange={(e) => setSelectedEnvironmentId(e.target.value)}
            disabled={availableEnvironments.length === 0}
          >
            {availableEnvironments.map(environment => (
              <option key={environment.id} value={environment.id}>
                {environment.display_name || environment.alias}
              </option>
            ))}
          </Select>
        </FormField>
      </div>

      <FormField label={t('pages.tasks.create.taskPreset')}>
        <Select
          id={FIELD_IDS.taskPreset}
          value={selectedTaskPresetId}
          onChange={(e) => applyTaskPreset(e.target.value as TaskPresetId)}
        >
          {TASK_PRESET_OPTIONS.map((preset) => (
            <option key={preset.id} value={preset.id}>
              {t(preset.labelKey)}
            </option>
          ))}
        </Select>
      </FormField>

      {showSeedUploader && (
        <div className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {showPaperInput ? t('pages.tasks.create.papers.label') : t('pages.tasks.create.seedFiles.label')}
          </span>
          <SeedFileUploader
            environmentId={selectedEnvironmentId}
            workspaceId={selectedWorkspaceId}
            disabled={selectedEnvironmentId === '' || selectedWorkspaceId === ''}
            onFilesChange={setSeedFiles}
          />
          {seedFiles.filter(f => f.status === 'uploaded').length > 0 && (
            <p className="text-xs text-[var(--text-secondary)]">
              {t('pages.tasks.create.seedFiles.fileCount', { count: String(seedFiles.filter(f => f.status === 'uploaded').length) })}
            </p>
          )}
        </div>
      )}

      {showPaperInput && (
        <div className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.tasks.create.arxiv.label')}
          </span>
          <div className="flex gap-2">
            <Input
              type="url"
              value={arxivInput}
              onChange={(e) => {
                setArxivInput(e.target.value);
                if (arxivInputError) setArxivInputError(null);
              }}
              onKeyDown={handleArxivInputKeyDown}
              placeholder={t('pages.tasks.create.arxiv.placeholder')}
              className="flex-1"
            />
            <Button
              type="button"
              variant="secondary"
              size="sm"
              onClick={handleAddArxivUrl}
            >
              {t('pages.tasks.create.arxiv.add')}
            </Button>
          </div>
          {arxivInputError && (
            <p className="text-xs text-[var(--danger)]">{arxivInputError}</p>
          )}
          {arxivUrls.length > 0 && (
            <ul className="space-y-1">
              {arxivUrls.map((url, idx) => (
                <li
                  key={`${url}-${idx}`}
                  className="flex items-center justify-between py-1 px-2 text-sm rounded bg-[var(--surface-2)]"
                >
                  <span className="truncate mr-2 font-mono text-xs text-[var(--text-secondary)]">
                    {url}
                  </span>
                  <button
                    type="button"
                    onClick={() => handleRemoveArxivUrl(idx)}
                    className="shrink-0 text-[var(--text-secondary)] hover:text-[var(--danger)] transition-colors"
                    aria-label={t('pages.tasks.create.arxiv.remove', { url })}
                  >
                    ✕
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <fieldset className="space-y-2" aria-labelledby="task-create-researcher-type-label">
        <legend id="task-create-researcher-type-label" className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
          {t('pages.tasks.create.researcherType')}
        </legend>
        <div className="flex flex-wrap gap-4 text-sm text-[var(--text-secondary)]">
          <label htmlFor={FIELD_IDS.researcherVanilla} className="flex items-center gap-2">
            <input
              id={FIELD_IDS.researcherVanilla}
              type="radio"
              name="researcher-type"
              value="vanilla"
              checked={researcherType === 'vanilla'}
              onChange={(e) => setResearcherType(e.target.value as ResearcherType)}
            />
            <span>{t('pages.tasks.create.researcherVanilla')}</span>
          </label>
          <label htmlFor={FIELD_IDS.researcherAris} className="flex items-center gap-2">
            <input
              id={FIELD_IDS.researcherAris}
              type="radio"
              name="researcher-type"
              value="aris-researcher"
              checked={researcherType === 'aris-researcher'}
              onChange={(e) => setResearcherType(e.target.value as ResearcherType)}
            />
            <span>{t('pages.tasks.create.researcherAris')}</span>
          </label>
        </div>
      </fieldset>

      <FormField label={t('pages.tasks.create.executionEngine')}>
        <Select
          id={FIELD_IDS.harnessEngine}
          value={harnessEngine}
          onChange={(e) => setHarnessEngine(e.target.value as HarnessEngine)}
        >
          <option value="claude-code">{t('pages.tasks.create.engineClaudeCode')}</option>
          <option value="agent-sdk">{t('pages.tasks.create.engineAgentSdk')}</option>
          <option value="codex-app-server">{t('pages.tasks.create.engineCodexAppServer')}</option>
        </Select>
      </FormField>

      {researcherType === 'vanilla' && (
        <div className="space-y-2">
          <span className="text-sm font-medium tracking-[-0.224px] text-[var(--text)]">
            {t('pages.tasks.skillsLabel')}
          </span>
          <TaskSkillPicker
            skills={availableSkills}
            selectedSkillIds={skills}
            onChange={setSkills}
          />
        </div>
      )}

      <FormField label={t('pages.tasks.titleLabel')}>
        <Input
          id={FIELD_IDS.title}
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={t('pages.tasks.create.titlePlaceholder')}
        />
      </FormField>

      <FormField label={t('pages.tasks.create.promptLabel')}>
        <Textarea
          id={FIELD_IDS.prompt}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          placeholder={t('pages.tasks.create.promptPlaceholder')}
          required
        />
      </FormField>

      {selectedWorkspaceId === '' || selectedEnvironmentId === '' ? (
        <p className="rounded-lg border border-[var(--warning-border)] bg-[var(--warning-soft)] px-3 py-2 text-xs text-[var(--warning-foreground)]">
          {t('pages.tasks.create.missingBinding')}
        </p>
      ) : null}

      <div className="flex gap-2">
        <Button type="submit" disabled={!canSubmit}>
          {t('pages.tasks.createAction')}
        </Button>
        <Button type="button" variant="secondary" onClick={onCancel}>
          {t('common.cancel')}
        </Button>
      </div>
    </form>
  );
}
