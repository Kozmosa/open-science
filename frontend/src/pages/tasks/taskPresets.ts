import type { HarnessEngine, ResearcherType } from '../../types';


export type TaskPresetLabelKey =
  | 'pages.tasks.create.presets.rawPrompt'
  | 'pages.tasks.create.presets.structuredResearch'
  | 'pages.tasks.create.presets.reproduceBaseline';
export type TaskPresetId = 'raw-prompt' | 'structured-research-default' | 'reproduce-baseline-default';

export interface TaskPresetOption {
  id: TaskPresetId;
  researcherType: ResearcherType;
  harnessEngine: HarnessEngine;
  labelKey: TaskPresetLabelKey;
}

export const TASK_PRESET_OPTIONS: TaskPresetOption[] = [
  {
    id: 'raw-prompt',
    labelKey: 'pages.tasks.create.presets.rawPrompt',
    researcherType: 'vanilla',
    harnessEngine: 'claude-code',
  },
  {
    id: 'structured-research-default',
    labelKey: 'pages.tasks.create.presets.structuredResearch',
    researcherType: 'aris-researcher',
    harnessEngine: 'claude-code',
  },
  {
    id: 'reproduce-baseline-default',
    labelKey: 'pages.tasks.create.presets.reproduceBaseline',
    researcherType: 'vanilla',
    harnessEngine: 'codex-app-server',
  },
];

export function getTaskPreset(id: string): TaskPresetOption {
  return TASK_PRESET_OPTIONS.find((option) => option.id === id) ?? TASK_PRESET_OPTIONS[0];
}
