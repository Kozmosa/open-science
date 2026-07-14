import { useState, useMemo } from 'react';
import { Button, NativeSelect } from '@design-system/primitives';
import { useT } from '@/shared/i18n';
import type { TaskCreatePayload, WorkspaceRecord, EnvironmentRecord } from '@/shared/types';
import type { ResearchAgentProfileSettings } from '@features/settings/types';
import { getTaskPreset, TASK_PRESET_OPTIONS, type TaskPresetId } from '@features/tasks/utils/taskPresets';

const FIELD_IDS = {
  taskPreset: 'convert-task-preset',
  workspace: 'convert-task-workspace',
  environment: 'convert-task-environment',
  researcherType: 'convert-task-researcher-type',
  harnessEngine: 'convert-task-harness-engine',
};

function arxivAbsUrl(paperId: string): string {
  return paperId ? `https://arxiv.org/abs/${paperId}` : '';
}

function arxivPdfUrl(paperId: string): string {
  return paperId ? `https://arxiv.org/pdf/${paperId}` : '';
}

function buildStructuredResearchPrompt(paperId: string, title: string, abstract: string): string {
  const absUrl = arxivAbsUrl(paperId);
  const pdfUrl = arxivPdfUrl(paperId);
  return `请使用 ARIS 的 /research-pipeline skill 对下面这篇论文进行系统研究。

必须先阅读全文，再开始结构化分析。全文来源：
- arXiv 页面：${absUrl}
- 全文 PDF：${pdfUrl}

论文标题：
${title}

论文摘要：
${abstract}

执行要求：
1. 调用 /research-pipeline skill，围绕论文的问题定义、方法、实验、结论、局限和可复现性进行系统研究。
2. 不要只基于摘要下结论；必须读取全文 PDF/原文页面后再分析。
3. 输出中文研究报告 Markdown，包含：核心贡献、方法拆解、实验与证据、与相关工作的关系、局限性、可复现步骤、后续可转化为任务的行动项。
4. 将最终 Markdown 报告保存到工作区磁盘，例如 docs/literature/${paperId || 'paper'}-structured-research.md。`;
}

function buildOverviewPrompt(paperId: string, title: string, abstract: string): string {
  const absUrl = arxivAbsUrl(paperId);
  return `请基于下面的论文标题、摘要和原文链接，产出一篇中文的文献导读 Markdown。

论文标题：
${title}

论文摘要：
${abstract}

原文链接：${absUrl}

要求：
1. 面向需要快速判断是否精读的研究者，写成中文文献导读。
2. 包含：一句话总结、研究问题、核心方法、主要发现、适合谁读、可能的启发、是否值得精读。
3. 不需要做完整系统研究；不要调用复杂 pipeline。
4. 注意保存到工作区磁盘，路径建议为 docs/literature/${paperId || 'paper'}-overview.md。`;
}

function buildPaperTaskPrompt(presetId: TaskPresetId, paperId: string, title: string, abstract: string): string {
  if (presetId === 'structured-research-default') {
    return buildStructuredResearchPrompt(paperId, title, abstract);
  }
  if (presetId === 'overview') {
    return buildOverviewPrompt(paperId, title, abstract);
  }
  return abstract;
}

interface Props {
  paperId: string;
  paperTitle: string;
  paperAbstract: string;
  workspaces: WorkspaceRecord[];
  environments: EnvironmentRecord[];
  isOpen: boolean;
  isSubmitting: boolean;
  researchAgentProfile?: ResearchAgentProfileSettings | null;
  onConfirm: (payload: TaskCreatePayload) => void;
  onCancel: () => void;
}

export default function ConvertToTaskDialog({
  paperId,
  paperTitle,
  paperAbstract,
  workspaces,
  environments,
  isOpen,
  isSubmitting,
  researchAgentProfile,
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
    const profile = researchAgentProfile;
    onConfirm({
      project_id: '',
      workspace_id: effectiveWorkspaceId,
      environment_id: effectiveEnvironmentId,
      researcher_type: researcherType,
      harness_engine: harnessEngine,
      prompt: buildPaperTaskPrompt(selectedTaskPresetId, paperId, paperTitle, paperAbstract),
      title: paperTitle.slice(0, 200),
      skills: [],
      mcp_servers: [],
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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-sm">
      <div className="w-full max-w-lg mx-4 rounded-2xl border border-[var(--border)] bg-[var(--surface)] p-6 shadow-xl">
        <h3 className="text-base font-semibold text-[var(--text)]">{t('literature.convertToTask')}</h3>
        <p className="mt-1 text-xs text-[var(--text-secondary)]">{t('literature.convertConfirm')}</p>

        <div className="mt-4 space-y-3">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--bg-secondary)] p-3">
            <p className="text-xs font-medium text-[var(--text)] truncate">{paperTitle}</p>
            <p className="mt-1 text-[11px] text-[var(--text-secondary)] line-clamp-3">{paperAbstract}</p>
          </div>

          <label className="block" htmlFor={FIELD_IDS.taskPreset}>
            <span className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.create.taskPreset')}
            </span>
            <NativeSelect
              id={FIELD_IDS.taskPreset}
              value={selectedTaskPresetId}
              onChange={(e) => applyTaskPreset(e.target.value as TaskPresetId)}
              className="w-full text-xs py-2"
            >
              {TASK_PRESET_OPTIONS.map((preset) => (
                <option key={preset.id} value={preset.id}>{t(preset.labelKey)}</option>
              ))}
            </NativeSelect>
          </label>

          <div>
            <label htmlFor={FIELD_IDS.workspace} className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.workspaceLabel')}
            </label>
            <NativeSelect
              id={FIELD_IDS.workspace}
              value={effectiveWorkspaceId}
              onChange={(e) => setSelectedWorkspaceId(e.target.value)}
              className="w-full text-xs py-2"
            >
              {workspaces.map((w: WorkspaceRecord) => (
                <option key={w.workspace_id} value={w.workspace_id}>{w.label}</option>
              ))}
            </NativeSelect>
          </div>

          <div>
            <label htmlFor={FIELD_IDS.environment} className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.environmentLabel')}
            </label>
            <NativeSelect
              id={FIELD_IDS.environment}
              value={effectiveEnvironmentId}
              onChange={(e) => setSelectedEnvironmentId(e.target.value)}
              className="w-full text-xs py-2"
            >
              {environments.map((env: EnvironmentRecord) => (
                <option key={env.id} value={env.id}>{env.alias} · {env.display_name}</option>
              ))}
            </NativeSelect>
          </div>

          <div>
            <label htmlFor={FIELD_IDS.researcherType} className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.create.researcherType')}
            </label>
            <NativeSelect
              id={FIELD_IDS.researcherType}
              value={researcherType}
              onChange={(e) => setResearcherType(e.target.value as 'vanilla' | 'aris-researcher')}
              className="w-full text-xs py-2"
            >
              <option value="vanilla">{t('pages.tasks.create.researcherVanilla')}</option>
              <option value="aris-researcher">{t('pages.tasks.create.researcherAris')}</option>
            </NativeSelect>
          </div>

          <div>
            <label htmlFor={FIELD_IDS.harnessEngine} className="mb-1 block text-[11px] font-medium text-[var(--text-secondary)]">
              {t('pages.tasks.create.executionEngine')}
            </label>
            <NativeSelect
              id={FIELD_IDS.harnessEngine}
              value={harnessEngine}
              onChange={(e) => setHarnessEngine(e.target.value as 'claude-code' | 'agent-sdk' | 'codex-app-server')}
              className="w-full text-xs py-2"
            >
              <option value="claude-code">{t('pages.tasks.create.engineClaudeCode')}</option>
              <option value="agent-sdk">{t('pages.tasks.create.engineAgentSdk')}</option>
              <option value="codex-app-server">{t('pages.tasks.create.engineCodexAppServer')}</option>
            </NativeSelect>
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
