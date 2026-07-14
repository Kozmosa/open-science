import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';
import TaskActionsMenu from '@features/tasks/components/TaskActionsMenu';
import { renderWithProviders } from '@/shared/test/render';
import type { TaskRecord } from '@/shared/types';

const task: TaskRecord = {
  task_id: 'task-1',
  project_id: 'project-1',
  workspace_id: 'workspace-1',
  environment_id: 'env-1',
  title: 'Failed Task',
  prompt: 'Retry me',
  status: 'failed',
  owner_user_id: 'u1',
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:01:00Z',
  started_at: '2026-01-01T00:00:10Z',
  completed_at: '2026-01-01T00:01:00Z',
  error_summary: 'failed',
};

function actions() {
  return {
    onArchive: vi.fn(),
    onUnarchive: vi.fn(),
    onCancel: vi.fn(),
    onRetry: vi.fn(),
    onMove: vi.fn(),
    onFork: vi.fn(),
  };
}

describe('TaskActionsMenu', () => {
  it('keeps core actions visible in a keyboard menu and retries the same Task', async () => {
    const user = userEvent.setup();
    const handlers = actions();
    renderWithProviders(
      <TaskActionsMenu task={task} canMutate disabledReason={null} {...handlers} />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    await user.click(await screen.findByRole('menuitem', { name: 'Retry as new Attempt' }));
    expect(handlers.onRetry).toHaveBeenCalledTimes(1);
  });

  it('disables execution actions when ownership or Project state denies them', async () => {
    const user = userEvent.setup();
    renderWithProviders(
      <TaskActionsMenu
        task={task}
        canMutate={false}
        disabledReason="Project archived"
        {...actions()}
      />,
    );

    await user.click(screen.getByRole('button', { name: 'Task actions' }));
    expect(await screen.findByRole('menuitem', { name: 'Retry as new Attempt' }))
      .toHaveAttribute('data-disabled');
  });
});
