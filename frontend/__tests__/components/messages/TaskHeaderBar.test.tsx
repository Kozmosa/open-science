import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import TaskHeaderBar from '@features/tasks/components/messages/TaskHeaderBar';
import { renderWithProviders } from '@/test-support/render';
import type { TaskSummary } from '@features/tasks/types';
import { updateTask } from '@features/tasks/api';

vi.mock('@features/tasks/api', () => ({ updateTask: vi.fn().mockResolvedValue({}) }));

function makeTask(overrides?: Partial<TaskSummary>): TaskSummary {
  return {
    task_id: 'task-1',
    title: 'Research paper analysis',
    status: 'running',
    project_id: 'default',
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
    ...overrides,
  } as TaskSummary;
}

describe('TaskHeaderBar', () => {
  it('renders the task title', () => {
    renderWithProviders(<TaskHeaderBar task={makeTask()} />);
    expect(screen.getByText('Research paper analysis')).toBeInTheDocument();
  });

  it('renders the task status badge', () => {
    renderWithProviders(<TaskHeaderBar task={makeTask({ status: 'running' })} />);
    expect(screen.getByText(/running/i)).toBeInTheDocument();
  });

  it('humanizes an unknown runtime status instead of exposing an i18n key', () => {
    renderWithProviders(
      <TaskHeaderBar task={makeTask({ status: 'completed' as TaskSummary['status'] })} />
    );

    expect(screen.getByText('Completed')).toBeInTheDocument();
    expect(screen.queryByText('pages.tasks.status.completed')).not.toBeInTheDocument();
  });

  it('enters edit mode when title is clicked and commits on Enter', async () => {
    renderWithProviders(<TaskHeaderBar task={makeTask()} />);

    const title = screen.getByText('Research paper analysis');

    // Click the title to enter edit mode — wrap in act for React state updates
    await act(async () => {
      fireEvent.click(title);
    });

    // After clicking, an input should appear with the title as its value
    const input = screen.getByDisplayValue('Research paper analysis');
    expect(input.tagName).toBe('INPUT');

    // Change the value and press Enter
    fireEvent.change(input, { target: { value: 'Updated title' } });
    fireEvent.keyDown(input, { key: 'Enter' });

    // The mutation should have been called
    await waitFor(() => {
      expect(updateTask).toHaveBeenCalledWith(
        'task-1',
        { title: 'Updated title' },
        expect.stringMatching(/^task\.rename:/),
      );
    });
  });

  it('cancels edit mode on Escape and restores original title', async () => {
    renderWithProviders(<TaskHeaderBar task={makeTask()} />);

    fireEvent.click(screen.getByText('Research paper analysis'));

    const input = screen.getByDisplayValue('Research paper analysis');
    fireEvent.change(input, { target: { value: 'Changed but escaped' } });
    fireEvent.keyDown(input, { key: 'Escape' });

    await waitFor(() => {
      expect(screen.getByText('Research paper analysis')).toBeInTheDocument();
    });
  });

  it('shows interrupt button for an active Turn', () => {
    renderWithProviders(
      <TaskHeaderBar task={makeTask()} showInterrupt onInterrupt={vi.fn()} />
    );
    expect(screen.getByRole('button', { name: /interrupt/i })).toBeInTheDocument();
  });

  it('calls onInterrupt when interrupt is clicked', () => {
    const onInterrupt = vi.fn();
    renderWithProviders(
      <TaskHeaderBar task={makeTask()} showInterrupt onInterrupt={onInterrupt} />
    );

    fireEvent.click(screen.getByRole('button', { name: /interrupt/i }));
    expect(onInterrupt).toHaveBeenCalledTimes(1);
  });

  it('renders toggle sidebar button when onToggleTaskSidebar is provided', () => {
    const toggle = vi.fn();
    renderWithProviders(
      <TaskHeaderBar
        task={makeTask()}
        taskSidebarCollapsed={false}
        onToggleTaskSidebar={toggle}
      />
    );

    const button = screen.getByRole('button', { name: /collapse/i });
    fireEvent.click(button);
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('renders metadata toggle button when onToggleMetadataSidebar is provided', () => {
    const toggle = vi.fn();
    renderWithProviders(
      <TaskHeaderBar
        task={makeTask()}
        metadataSidebarOpen
        onToggleMetadataSidebar={toggle}
      />
    );

    const button = screen.getByRole('button', { name: /collapse/i });
    fireEvent.click(button);
    expect(toggle).toHaveBeenCalledTimes(1);
  });

  it('shows expand label when sidebar is collapsed', () => {
    renderWithProviders(
      <TaskHeaderBar
        task={makeTask()}
        taskSidebarCollapsed
        onToggleTaskSidebar={vi.fn()}
      />
    );

    expect(screen.getByRole('button', { name: /expand/i })).toBeInTheDocument();
  });
});
