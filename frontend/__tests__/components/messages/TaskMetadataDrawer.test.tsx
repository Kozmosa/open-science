import { screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import TaskMetadataDrawer from '../../../src/components/messages/TaskMetadataDrawer';
import { renderWithProviders } from '@/shared/test/render';
import type { TaskRecord } from '@/shared/types';
import { formatTaskDateTime, shortIdentifier } from '@features/tasks/utils/metadataPresentation';

function makeTask(overrides?: Partial<TaskRecord>): TaskRecord {
  return {
    task_id: 'task-1',
    title: 'Research task',
    status: 'succeeded',
    project_id: 'default',
    created_at: '2026-06-01T08:00:00Z',
    updated_at: '2026-06-01T10:30:00Z',
    started_at: '2026-06-01T08:01:00Z',
    completed_at: '2026-06-01T10:29:00Z',
    command: ['codex', 'run', '--task'],
    working_directory: '/workspace/project',
    workspace_summary: { label: 'Default Workspace' },
    environment_summary: { display_name: 'GPU Lab', alias: 'gpu-lab' },
    prompt: 'Analyze this research paper',
    result: {
      exit_code: 0,
      completed_at: '2026-06-01T10:29:00Z',
    },
    ...overrides,
  } as TaskRecord;
}

describe('TaskMetadataDrawer', () => {
  it('renders the summary section title', () => {
    renderWithProviders(<TaskMetadataDrawer task={makeTask()} />);
    expect(screen.getByText(/summary/i)).toBeInTheDocument();
  });

  it('renders workspace metadata section', () => {
    renderWithProviders(<TaskMetadataDrawer task={makeTask()} />);

    expect(screen.getByText('/workspace/project')).toBeInTheDocument();
    expect(screen.getByText('Default Workspace')).toBeInTheDocument();
    expect(screen.getByText('GPU Lab')).toBeInTheDocument();
  });

  it('renders command metadata', () => {
    renderWithProviders(<TaskMetadataDrawer task={makeTask()} />);

    // The command should be joined with spaces
    expect(screen.getByText('codex run --task')).toBeInTheDocument();
  });

  it('moves the shortened task ID into copyable Technical details', () => {
    const taskId = 'task-1234567890-abcdefghijklmnopqrstuvwxyz';
    renderWithProviders(<TaskMetadataDrawer task={makeTask({ task_id: taskId })} />);

    expect(screen.getByText('Technical details')).toBeInTheDocument();
    expect(screen.getByText(shortIdentifier(taskId))).toHaveAttribute('title', taskId);
    expect(screen.getByRole('button', { name: 'Copy Task ID' })).toBeInTheDocument();
  });

  it('renders locale-aware timestamps instead of raw ISO values', () => {
    renderWithProviders(<TaskMetadataDrawer task={makeTask()} />);

    expect(screen.getByText(formatTaskDateTime('2026-06-01T08:00:00Z', 'en'))).toBeInTheDocument();
    expect(screen.getByText(formatTaskDateTime('2026-06-01T10:30:00Z', 'en'))).toBeInTheDocument();
    expect(screen.queryByText('2026-06-01T08:00:00Z')).not.toBeInTheDocument();
  });

  it('renders exit code from result', () => {
    renderWithProviders(<TaskMetadataDrawer task={makeTask()} />);
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('shows fallback text for null values', () => {
    renderWithProviders(
      <TaskMetadataDrawer
        task={makeTask({
          working_directory: null,
          workspace_summary: undefined,
          environment_summary: undefined,
          command: undefined,
          prompt: null,
          result: undefined,
        })}
      />
    );

    // "n/a" is the English translation for t('pages.tasks.unavailable')
    const fallbackElements = screen.getAllByText('n/a');
    expect(fallbackElements.length).toBeGreaterThanOrEqual(1);
  });

  it('renders error summary as Alert when present', () => {
    renderWithProviders(
      <TaskMetadataDrawer
        task={makeTask({ error_summary: 'Connection timeout during execution' })}
      />
    );

    expect(screen.getByText('Connection timeout during execution')).toBeInTheDocument();
  });

  it('does not render error alert when no error_summary', () => {
    renderWithProviders(<TaskMetadataDrawer task={makeTask()} />);

    // The error Alert should not be in the document
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('uses runtime.command as fallback for command field', () => {
    const taskWithoutCommand = makeTask({ command: undefined });
    (taskWithoutCommand as Record<string, unknown>).runtime = {
      command: ['python', 'main.py'],
    };
    renderWithProviders(<TaskMetadataDrawer task={taskWithoutCommand} />);

    expect(screen.getByText('python main.py')).toBeInTheDocument();
  });
});
