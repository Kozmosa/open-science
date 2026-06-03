import { useState } from 'react';
import type { TaskCreatePayload, ResearcherType, HarnessEngine } from '../../types';

const FIELD_IDS = {
  researcherVanilla: 'task-create-researcher-vanilla',
  researcherAris: 'task-create-researcher-aris',
  harnessEngine: 'task-create-harness-engine',
  skills: 'task-create-skills',
  title: 'task-create-title',
  prompt: 'task-create-prompt',
};

interface Props {
  projectId: string;
  workspaceId: string;
  environmentId: string;
  onSubmit: (payload: TaskCreatePayload) => void;
  onCancel: () => void;
}

export default function TaskCreateForm({
  projectId,
  workspaceId,
  environmentId,
  onSubmit,
  onCancel,
}: Props) {
  const [researcherType, setResearcherType] = useState<ResearcherType>('vanilla');
  const [harnessEngine, setHarnessEngine] = useState<HarnessEngine>('claude-code');
  const [prompt, setPrompt] = useState('');
  const [skills, setSkills] = useState<string[]>([]);
  const [title, setTitle] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
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
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <span className="block text-sm font-medium mb-1">
          Researcher Type
        </span>
        <div className="flex gap-4">
          <label htmlFor={FIELD_IDS.researcherVanilla} className="flex items-center gap-2">
            <input
              id={FIELD_IDS.researcherVanilla}
              type="radio"
              name="researcher-type"
              value="vanilla"
              checked={researcherType === 'vanilla'}
              onChange={(e) => setResearcherType(e.target.value as ResearcherType)}
            />
            <span>Vanilla</span>
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
            <span>ARIS Researcher</span>
          </label>
        </div>
      </div>

      <div>
        <label htmlFor={FIELD_IDS.harnessEngine} className="block text-sm font-medium mb-1">
          Execution Engine
        </label>
        <select
          id={FIELD_IDS.harnessEngine}
          value={harnessEngine}
          onChange={(e) => setHarnessEngine(e.target.value as HarnessEngine)}
          className="w-full rounded border px-3 py-2"
        >
          <option value="claude-code">Claude Code</option>
          <option value="agent-sdk">Agent SDK</option>
          <option value="codex-app-server">Codex App Server</option>
        </select>
      </div>

      {researcherType === 'vanilla' && (
        <div>
          <label htmlFor={FIELD_IDS.skills} className="block text-sm font-medium mb-1">
            Skills
          </label>
          <input
            id={FIELD_IDS.skills}
            type="text"
            placeholder="skill1, skill2, ..."
            value={skills.join(', ')}
            onChange={(e) => setSkills(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
            className="w-full rounded border px-3 py-2"
          />
        </div>
      )}

      <div>
        <label htmlFor={FIELD_IDS.title} className="block text-sm font-medium mb-1">
          Title
        </label>
        <input
          id={FIELD_IDS.title}
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Optional task title"
          className="w-full rounded border px-3 py-2"
        />
      </div>

      <div>
        <label htmlFor={FIELD_IDS.prompt} className="block text-sm font-medium mb-1">
          Prompt
        </label>
        <textarea
          id={FIELD_IDS.prompt}
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          rows={6}
          className="w-full rounded border px-3 py-2"
          placeholder="Enter your research prompt..."
          required
        />
      </div>

      <div className="flex gap-2">
        <button
          type="submit"
          className="rounded bg-blue-600 px-4 py-2 text-white hover:bg-blue-700"
        >
          Create task
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded border px-4 py-2 hover:bg-gray-50"
        >
          Cancel
        </button>
      </div>
    </form>
  );
}
