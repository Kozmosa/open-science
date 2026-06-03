import { useState } from 'react';
import type { TaskCreatePayload, ResearcherType, HarnessEngine } from '../../types';

interface Props {
  onSubmit: (payload: TaskCreatePayload) => void;
  onCancel: () => void;
}

export default function TaskCreateForm({ onSubmit, onCancel }: Props) {
  const [researcherType, setResearcherType] = useState<ResearcherType>('vanilla');
  const [harnessEngine, setHarnessEngine] = useState<HarnessEngine>('claude-code');
  const [prompt, setPrompt] = useState('');
  const [skills, setSkills] = useState<string[]>([]);
  const [title, setTitle] = useState('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    onSubmit({
      project_id: 'default-project',
      workspace_id: 'default-workspace',
      environment_id: 'default-environment',
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
        <label className="block text-sm font-medium mb-1">
          Researcher Type
        </label>
        <div className="flex gap-4">
          <label className="flex items-center gap-2">
            <input
              type="radio"
              value="vanilla"
              checked={researcherType === 'vanilla'}
              onChange={(e) => setResearcherType(e.target.value as ResearcherType)}
            />
            <span>Vanilla</span>
          </label>
          <label className="flex items-center gap-2">
            <input
              type="radio"
              value="aris-researcher"
              checked={researcherType === 'aris-researcher'}
              onChange={(e) => setResearcherType(e.target.value as ResearcherType)}
            />
            <span>ARIS Researcher</span>
          </label>
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">
          Execution Engine
        </label>
        <select
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
          <label className="block text-sm font-medium mb-1">
            Skills
          </label>
          <input
            type="text"
            placeholder="skill1, skill2, ..."
            value={skills.join(', ')}
            onChange={(e) => setSkills(e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
            className="w-full rounded border px-3 py-2"
          />
        </div>
      )}

      <div>
        <label className="block text-sm font-medium mb-1">
          Title
        </label>
        <input
          type="text"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Optional task title"
          className="w-full rounded border px-3 py-2"
        />
      </div>

      <div>
        <label className="block text-sm font-medium mb-1">
          Prompt
        </label>
        <textarea
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
          Create
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
