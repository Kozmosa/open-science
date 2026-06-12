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
        paperId="2401.00001"
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );

    const presetSelect = screen.getByLabelText('Task preset');
    expect(within(presetSelect).getAllByRole('option')).toHaveLength(4);
    fireEvent.change(presetSelect, { target: { value: 'structured-research-default' } });
    fireEvent.click(screen.getByRole('button', { name: 'Convert to Task' }));

    await waitFor(() => {
      expect(onConfirm).toHaveBeenCalledWith(expect.objectContaining({
        researcher_type: 'aris-researcher',
        harness_engine: 'claude-code',
      }));
      const payload = onConfirm.mock.calls[0]?.[0];
      expect(payload?.prompt).toContain('/research-pipeline');
      expect(payload?.prompt).toContain('https://arxiv.org/pdf/2401.00001');
      expect(payload?.prompt).toContain('Paper abstract');
    });
  });

  it('builds an overview prompt that asks for a saved Chinese markdown guide', async () => {
    const onConfirm = vi.fn<(payload: TaskCreatePayload) => void>();

    renderWithProviders(
      <ConvertToTaskDialog
        isOpen
        isSubmitting={false}
        paperId="2401.00001"
        paperTitle="Paper title"
        paperAbstract="Paper abstract"
        workspaces={[workspace]}
        environments={[environment]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );

    fireEvent.change(screen.getByLabelText('Task preset'), { target: { value: 'overview' } });
    fireEvent.click(screen.getByRole('button', { name: 'Convert to Task' }));

    await waitFor(() => {
      const payload = onConfirm.mock.calls[0]?.[0];
      expect(payload).toEqual(expect.objectContaining({
        researcher_type: 'vanilla',
        harness_engine: 'claude-code',
      }));
      expect(payload?.prompt).toContain('中文的文献导读 Markdown');
      expect(payload?.prompt).toContain('保存到工作区磁盘');
      expect(payload?.prompt).toContain('https://arxiv.org/abs/2401.00001');
    });
  });

  it('routes into the user default project by sending an empty project_id', async () => {
    const onConfirm = vi.fn<(payload: TaskCreatePayload) => void>();

    renderWithProviders(
      <ConvertToTaskDialog
        isOpen
        isSubmitting={false}
        paperId="2401.00001"
        paperTitle="Paper title"
        paperAbstract="Paper abstract"
        workspaces={[workspace]}
        environments={[environment]}
        onConfirm={onConfirm}
        onCancel={vi.fn()}
      />
    );

    fireEvent.click(screen.getByRole('button', { name: 'Convert to Task' }));

    await waitFor(() => {
      const payload = onConfirm.mock.calls[0]?.[0];
      // Empty project_id lets the backend resolve (and create) the user's
      // <username>_default project — never an orphan task.
      expect(payload?.project_id).toBe('');
    });
  });
  it('localizes researcher and engine controls in Chinese', () => {
    renderWithProviders(
      <ConvertToTaskDialog
        isOpen
        isSubmitting={false}
        paperId="2401.00001"
        paperTitle="Paper title"
        paperAbstract="Paper abstract"
        workspaces={[workspace]}
        environments={[environment]}
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
      { locale: 'zh' }
    );

    expect(screen.getByLabelText('研究员类型')).toBeInTheDocument();
    expect(screen.getByLabelText('执行引擎')).toBeInTheDocument();
    expect(screen.queryByText('Researcher Type')).not.toBeInTheDocument();
    expect(screen.queryByText('Execution Engine')).not.toBeInTheDocument();
  });
});
