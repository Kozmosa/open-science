import { useState } from 'react';
import { Button, FormField, Input, Select, Textarea } from '../../components/ui';
import { useT } from '../../i18n';
import type { SkillItem, TaskCreatePayload, ResearcherType, HarnessEngine } from '../../types';
import TaskSkillPicker from './TaskSkillPicker';

const FIELD_IDS = {
  researcherVanilla: 'task-create-researcher-vanilla',
  researcherAris: 'task-create-researcher-aris',
  harnessEngine: 'task-create-harness-engine',
  title: 'task-create-title',
  prompt: 'task-create-prompt',
};

interface Props {
  projectId: string;
  workspaceId: string;
  environmentId: string;
  availableSkills: SkillItem[];
  onSubmit: (payload: TaskCreatePayload) => void;
  onCancel: () => void;
}

export default function TaskCreateForm({
  projectId,
  workspaceId,
  environmentId,
  onSubmit,
  availableSkills,
  onCancel,
}: Props) {
  const t = useT();
  const [researcherType, setResearcherType] = useState<ResearcherType>('vanilla');
  const [harnessEngine, setHarnessEngine] = useState<HarnessEngine>('claude-code');
  const [prompt, setPrompt] = useState('');
  const [skills, setSkills] = useState<string[]>([]);
  const [title, setTitle] = useState('');

  const canSubmit = workspaceId !== '' && environmentId !== '' && prompt.trim() !== '';

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!canSubmit) {
      return;
    }
    onSubmit({
      project_id: projectId,
      workspace_id: workspaceId,
      environment_id: environmentId,
      researcher_type: researcherType,
      harness_engine: harnessEngine,
      prompt,
      skills: researcherType === 'vanilla' ? skills : [],
      mcp_servers: [],
      title: title || undefined,
    });
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-4 text-[var(--text)]">
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

      {workspaceId === '' || environmentId === '' ? (
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
