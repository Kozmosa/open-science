import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import ConvertToTaskDialog from '../../../src/components/literature/ConvertToTaskDialog';
import { renderWithProviders } from '../../../src/test/render';
import type { EnvironmentRecord, TaskCreatePayload, WorkspaceRecord } from '../../../src/types';

const workspace: WorkspaceRecord = {
  workspace_id: 'workspace-default',
  project_id: 'default',
  label: 'Default Workspace',
  description: '',
  default_workdir: '/workspace/default',
  workspace_prompt: '',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
};

const environment: EnvironmentRecord = {
  id: 'env-1',
  alias: 'localhost',
  display_name: 'Localhost',
  description: null,
  is_seed: false,
  tags: [],
  host: '127.0.0.1',
  port: 22,
  user: 'xuyang',
  auth_kind: 'ssh_key',
  identity_file: null,
  proxy_jump: null,
  proxy_command: null,
  ssh_options: {},
  default_workdir: '/workspace/default',
  preferred_python: null,
  preferred_env_manager: null,
  preferred_runtime_notes: null,
  task_harness_profile: null,
  code_server_path: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  latest_detection: null,
};

describe('ConvertToTaskDialog', () => {
  it('applies the selected task preset when converting a paper', async () => {
    const onConfirm = vi.fn<(payload: TaskCreatePayload) => void>();

    renderWithProviders(
      <ConvertToTaskDialog
        isOpen
        isSubmitting={false}
        paperTitle="Paper title"
        paperAbstract="Paper abstract"
        workspaces={[workspace]}
        environments={[environment]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );

    const presetSelect = screen.getByLabelText('Task preset');
    expect(within(presetSelect).getAllByRole('option')).toHaveLength(3);
    fireEvent.change(presetSelect, { target: { value: 'structured-research-default' } });
    fireEvent.click(screen.getByRole('button', { name: 'Convert to Task' }));

    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
        researcher_type: 'aris-researcher',
        harness_engine: 'claude-code',
        prompt: 'Paper abstract',
      }));
    });
  });
});
