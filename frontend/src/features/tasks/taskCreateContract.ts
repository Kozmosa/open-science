import type { TaskPresetId } from './utils/taskPresets';

export interface LiteratureTaskCreateFixture {
  source: 'literature';
  paper_id: string;
  project_id: string;
  workspace_id: string;
  task_preset: TaskPresetId;
  title?: string;
}

export function buildLiteratureTaskCreateFixture(
  input: Omit<LiteratureTaskCreateFixture, 'source'>,
): LiteratureTaskCreateFixture {
  return { source: 'literature', ...input };
}
