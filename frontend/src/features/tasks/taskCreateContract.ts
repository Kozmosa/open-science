import type { TaskPresetId } from './utils/taskPresets';

export interface LiteratureTaskCreateFixture {
  source: 'literature';
  paper_id: string;
  project_id: string;
  workspace_id: string | null;
  title: string;
  prompt: string;
  preset_id: TaskPresetId;
}

export function buildLiteratureTaskCreateFixture(
  input: Omit<LiteratureTaskCreateFixture, 'source'>,
): LiteratureTaskCreateFixture {
  return { source: 'literature', ...input };
}
